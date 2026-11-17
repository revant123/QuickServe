"""Order placement and lifecycle."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import Conflict, Forbidden, InvalidTransition, NotFound, OutOfStock
from app.core.money import rupees
from app.database.session import transaction
from app.modules.menu import repository as menu_repo
from app.modules.menu.model import MenuItem
from app.modules.orders import repository as repo
from app.modules.orders.model import Order, OrderItem, OrderStatus, OrderStatusEvent
from app.modules.orders.pricing import compute_bill
from app.modules.orders.schema import OrderCreate, TimeoutReport
from app.modules.orders.state_machine import (
    ACTORS,
    CUSTOMER_CANCELLABLE,
    FAILED_ENDINGS,
    RELEASE_STOCK_FROM,
    WASTE_STOCK_FROM,
    can_transition,
)
from app.modules.payments.refunds import refund_for_order
from app.modules.restaurants.model import Restaurant
from app.modules.restaurants.service import owns_restaurant
from app.modules.users.model import Role, User

# Riders see orders only once they're ready for pickup.
RIDER_VISIBLE = {OrderStatus.READY, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED}


def place_order(db: Session, data: OrderCreate, customer: User, settings: Settings | None = None) -> Order:
    """Reserve stock for every line and create the order, all or nothing.

    If the third item is out of stock, the first two reservations are undone by
    the rollback. The customer never ends up with half an order, and stock never
    stays reserved for an order that doesn't exist.
    """
    settings = settings or get_settings()

    # The same dish twice in one request becomes one line with the summed quantity.
    qty_by_item: dict[uuid.UUID, int] = defaultdict(int)
    for line in data.items:
        qty_by_item[line.menu_item_id] += line.quantity

    with transaction(db):
        restaurant = db.get(Restaurant, data.restaurant_id)
        if restaurant is None:
            raise NotFound("Restaurant not found")
        if not restaurant.is_open:
            raise Conflict("Restaurant is not accepting orders right now")
        if customer.role is not Role.CUSTOMER:
            raise Forbidden("Only customer accounts can place orders")

        reserved = []
        # Always lock rows in the same order (sorted ids). If order A locks
        # paneer then naan while order B locks naan then paneer, each waits for
        # the other forever: a deadlock. A fixed order makes that impossible.
        for item_id in sorted(qty_by_item):
            qty = qty_by_item[item_id]
            row = menu_repo.consume_atomically(db, item_id, restaurant.id, qty)
            if row is None:
                raise _why_unavailable(db, item_id, restaurant.id, qty)
            reserved.append((row, qty))

        bill = compute_bill(sum(row.price * qty for row, qty in reserved), restaurant.packaging_charge, settings)
        now = menu_repo.db_now(db)
        order = Order(
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            delivery_address=data.delivery_address,
            status=OrderStatus.PLACED,
            pay_by=now + timedelta(seconds=settings.unpaid_order_timeout_seconds),
            item_total=bill.item_total,
            packaging_charge=bill.packaging_charge,
            delivery_fee=bill.delivery_fee,
            platform_fee=bill.platform_fee,
            gst_food=bill.gst_food,
            gst_fees=bill.gst_fees,
            grand_total=bill.grand_total,
            items=[
                OrderItem(
                    menu_item_id=row.id,
                    item_name=row.name,
                    unit_price=row.price,
                    quantity=qty,
                    line_total=rupees(row.price * qty),
                    cycle_no=row.cycle_no,
                )
                for row, qty in reserved
            ],
        )
        db.add(order)
        db.flush()
        db.add(OrderStatusEvent(order_id=order.id, from_status=None, to_status=OrderStatus.PLACED, actor="customer"))
    return order


def _why_unavailable(db: Session, item_id: uuid.UUID, restaurant_id: uuid.UUID, qty: int) -> Exception:
    item = db.execute(select(MenuItem).where(MenuItem.id == item_id)).scalar_one_or_none()
    if item is None or item.restaurant_id != restaurant_id:
        return NotFound(f"Menu item {item_id} not found in this restaurant")
    if not item.switched_on_at(menu_repo.db_now(db)):
        return OutOfStock(f"{item.name} is unavailable right now")
    return OutOfStock(f"Only {item.available} left of {item.name}, you asked for {qty}")


def _actor_for(db: Session, order: Order, user: User) -> str:
    """Which part does this user play for THIS order?

    Raises NotFound (not Forbidden) when the user has no business seeing the
    order. Answering "403 Forbidden" would confirm that an order with that id
    exists; "404" reveals nothing.
    """
    if user.role is Role.ADMIN:
        return "support"
    if user.role is Role.CUSTOMER and order.customer_id == user.id:
        return "customer"
    if user.role is Role.RESTAURANT_OWNER and owns_restaurant(db, order.restaurant_id, user):
        return "restaurant"
    if user.role is Role.RIDER and order.status in RIDER_VISIBLE:
        return "rider"
    raise NotFound("Order not found")


def get_order(db: Session, order_id: uuid.UUID, user: User) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise NotFound("Order not found")
    _actor_for(db, order, user)
    return order


def timeline(db: Session, order_id: uuid.UUID, user: User) -> list[OrderStatusEvent]:
    get_order(db, order_id, user)
    return repo.list_events(db, order_id)


def _apply(db: Session, order: Order, target: OrderStatus, actor: str, note: str | None = None) -> None:
    """Validate one status change and run its side effects. Caller holds the row lock."""
    current = order.status
    if not can_transition(current, target):
        raise InvalidTransition(f"Cannot move an order from {current.value} to {target.value}")
    if actor not in ACTORS.get(target, set()):
        raise InvalidTransition(f"'{actor}' cannot move an order to {target.value}")
    if target is OrderStatus.CANCELLED and actor == "customer" and current not in CUSTOMER_CANCELLABLE:
        raise InvalidTransition("The restaurant has already accepted this order; please contact support")

    if target in FAILED_ENDINGS:
        if current in RELEASE_STOCK_FROM:
            _release_stock(db, order)
        elif current in WASTE_STOCK_FROM:
            _record_waste(db, order)
        if current is not OrderStatus.PLACED:  # money was taken, give it back
            refund_for_order(db, order.id)
        order.cancel_reason = note

    order.status = target
    db.add(OrderStatusEvent(order_id=order.id, from_status=current, to_status=target, actor=actor, note=note))


def _release_stock(db: Session, order: Order) -> None:
    for line in sorted(order.items, key=lambda i: i.menu_item_id):
        released = menu_repo.release_from_current_cycle(db, line.menu_item_id, line.cycle_no, line.quantity)
        if not released:
            # The item was restocked after this order was placed. The units belong
            # to an archived cycle: record them as returned there, and leave the
            # new cycle's counters alone.
            menu_repo.add_to_cycle_counter(db, line.menu_item_id, line.cycle_no, returned=line.quantity)


def _record_waste(db: Session, order: Order) -> None:
    for line in sorted(order.items, key=lambda i: i.menu_item_id):
        menu_repo.add_to_cycle_counter(db, line.menu_item_id, line.cycle_no, wasted=line.quantity)


def mark_paid(db: Session, order: Order, now: datetime, settings: Settings | None = None) -> None:
    """Called by the payments module, inside its transaction, after a successful charge."""
    settings = settings or get_settings()
    order.paid_at = now
    order.accept_by = now + timedelta(seconds=settings.restaurant_accept_timeout_seconds)
    _apply(db, order, OrderStatus.PAID, "system")


def lock_order(db: Session, order_id: uuid.UUID) -> Order:
    order = repo.lock_order(db, order_id)
    if order is None:
        raise NotFound("Order not found")
    return order


def change_status(db: Session, order_id: uuid.UUID, target: OrderStatus, user: User, note: str | None = None) -> Order:
    with transaction(db):
        order = lock_order(db, order_id)
        actor = _actor_for(db, order, user)  # decided by the token, never by the request body
        if actor not in ACTORS.get(target, set()):
            raise Forbidden(f"As {actor} you can't move an order to {target.value}")
        _apply(db, order, target, actor, note)
    return order


def cancel(db: Session, order_id: uuid.UUID, user: User, reason: str) -> Order:
    return change_status(db, order_id, OrderStatus.CANCELLED, user, reason)


def run_timeouts(db: Session, batch: int = 100) -> TimeoutReport:
    """The background job. Later it runs on a schedule; today you can trigger it by hand.

    1. PLACED orders past pay_by     -> PAYMENT_FAILED, stock released
    2. PAID orders past accept_by    -> REJECTED, stock released, payment refunded
    """
    with transaction(db):
        now = menu_repo.db_now(db)
        unpaid = repo.claim_expired(db, OrderStatus.PLACED, Order.pay_by, now, batch)
        for order in unpaid:
            _apply(db, order, OrderStatus.PAYMENT_FAILED, "system", "Payment not completed in time")
        stale = repo.claim_expired(db, OrderStatus.PAID, Order.accept_by, now, batch)
        for order in stale:
            _apply(db, order, OrderStatus.REJECTED, "system", "Restaurant did not accept in time")
    return TimeoutReport(payment_expired=len(unpaid), auto_rejected=len(stale))
