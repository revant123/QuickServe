"""Order placement and lifecycle."""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    Conflict,
    CouponRejected,
    Forbidden,
    InvalidTransition,
    NotFound,
    OutOfStock,
    PriceChanged,
)
from app.core.logging import log_event
from app.core.metrics import (
    COUPON_DISCOUNT,
    ORDER_STATUS_CHANGES,
    ORDER_VALUE,
    ORDERS_PLACED,
    SURGE_ORDERS,
    after_commit,
)
from app.core.money import rupees
from app.database.session import transaction
from app.modules.coupons import service as coupons
from app.modules.coupons.model import Coupon
from app.modules.menu import repository as menu_repo
from app.modules.menu.model import MenuItem
from app.modules.orders import repository as repo
from app.modules.orders.model import Order, OrderItem, OrderStatus, OrderStatusEvent
from app.modules.orders.schema import OrderCreate, TimeoutReport
from app.modules.orders.state_machine import (
    ACTORS,
    CUSTOMER_CANCELLABLE,
    FAILED_ENDINGS,
    RELEASE_STOCK_FROM,
    WASTE_STOCK_FROM,
    can_transition,
)
from app.modules.outbox import service as outbox
from app.modules.payments.refunds import refund_for_order
from app.modules.pricing import service as pricing
from app.modules.pricing.calculator import Bill, Conditions, price
from app.modules.restaurants.model import Restaurant
from app.modules.restaurants.service import owns_restaurant
from app.modules.users.model import Role, User

log = logging.getLogger("quickserve.orders")

# Riders see orders only once they're ready for pickup.
RIDER_VISIBLE = {OrderStatus.READY, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED}


def _open_restaurant_for(db: Session, data: OrderCreate, customer: User) -> Restaurant:
    restaurant = db.get(Restaurant, data.restaurant_id)
    if restaurant is None:
        raise NotFound("Restaurant not found")
    if not restaurant.is_open:
        raise Conflict("Restaurant is not accepting orders right now")
    if customer.role is not Role.CUSTOMER:
        raise Forbidden("Only customer accounts can place orders")
    return restaurant


def _qty_by_item(data: OrderCreate) -> dict[uuid.UUID, int]:
    # The same dish twice in one request becomes one line with the summed quantity.
    qty: dict[uuid.UUID, int] = defaultdict(int)
    for line in data.items:
        qty[line.menu_item_id] += line.quantity
    return qty


def _bill(
    restaurant: Restaurant, item_total, conditions: Conditions, coupon: Coupon | None, settings: Settings
) -> Bill:
    return price(
        item_total, restaurant.packaging_charge, conditions, settings, coupons.terms(coupon) if coupon else None
    )


def quote(db: Session, data: OrderCreate, customer: User, settings: Settings | None = None) -> tuple[Bill, str | None]:
    """The price of this cart right now, without reserving anything.

    Same rules and same code as place_order, so the quote and the order can
    only differ if the world changed in between. A coupon that doesn't apply
    doesn't fail the quote: the customer gets the price without it, and why.
    """
    settings = settings or get_settings()
    restaurant = _open_restaurant_for(db, data, customer)
    now = menu_repo.db_now(db)
    conditions = pricing.conditions_for(
        db, restaurant, data.delivery_location.lat, data.delivery_location.lng, now, settings
    )
    qty_by_item = _qty_by_item(data)
    # One query for the whole cart, not one per line (that would be N+1).
    rows = db.execute(select(MenuItem).where(MenuItem.id.in_(qty_by_item))).scalars()
    by_id = {row.id: row for row in rows}
    item_total = Decimal("0")
    for item_id, qty in qty_by_item.items():
        row = by_id.get(item_id)
        if row is None or row.restaurant_id != restaurant.id or not row.switched_on_at(now):
            raise _why_unavailable(db, item_id, restaurant.id, qty)
        if row.available is not None and row.available < qty:
            raise _why_unavailable(db, item_id, restaurant.id, qty)
        item_total += row.price * qty

    coupon, coupon_error = None, None
    if data.coupon_code:
        try:
            coupon = coupons.find_usable(db, data.coupon_code, restaurant.id, customer, now)
            return _bill(restaurant, item_total, conditions, coupon, settings), None
        except CouponRejected as exc:
            coupon_error = exc.message
    return _bill(restaurant, item_total, conditions, None, settings), coupon_error


def place_order(db: Session, data: OrderCreate, customer: User, settings: Settings | None = None) -> Order:
    """Reserve stock for every line, price it, and create the order, all or nothing.

    If the third item is out of stock, the first two reservations are undone by
    the rollback. The customer never ends up with half an order, and stock never
    stays reserved for an order that doesn't exist. The same goes for the coupon.
    """
    settings = settings or get_settings()
    qty_by_item = _qty_by_item(data)

    with transaction(db):
        restaurant = _open_restaurant_for(db, data, customer)
        now = menu_repo.db_now(db)
        # Cheap checks first: too far away, or a bad coupon, fails before any stock is locked.
        conditions = pricing.conditions_for(
            db, restaurant, data.delivery_location.lat, data.delivery_location.lng, now, settings
        )
        coupon = coupons.find_usable(db, data.coupon_code, restaurant.id, customer, now) if data.coupon_code else None

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

        bill = _bill(restaurant, sum(row.price * qty for row, qty in reserved), conditions, coupon, settings)
        if data.expected_total is not None and rupees(data.expected_total) != bill.grand_total:
            raise PriceChanged(
                f"The price changed from Rs {rupees(data.expected_total)} to Rs {bill.grand_total}. "
                "Check the new bill and order again.",
                bill.grand_total,
            )
        order = Order(
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            delivery_address=data.delivery_address,
            delivery_latitude=Decimal(str(data.delivery_location.lat)),
            delivery_longitude=Decimal(str(data.delivery_location.lng)),
            distance_km=bill.distance_km,
            status=OrderStatus.PLACED,
            pay_by=now + timedelta(seconds=settings.unpaid_order_timeout_seconds),
            item_total=bill.item_total,
            discount=bill.discount,
            coupon_code=bill.coupon_code,
            packaging_charge=bill.packaging_charge,
            delivery_fee=bill.delivery_fee,
            small_order_fee=bill.small_order_fee,
            surge_fee=bill.surge_fee,
            surge_reasons=",".join(bill.surge_reasons) or None,
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
        if coupon is not None:
            coupons.redeem(db, coupon, customer, order)
        db.add(OrderStatusEvent(order_id=order.id, from_status=None, to_status=OrderStatus.PLACED, actor="customer"))
        # Same transaction as the order itself: the event exists if and only if the order does.
        _publish(db, order, "order.placed", previous=None, actor="customer")
    # The transaction has committed by this point, so the order really exists.
    ORDERS_PLACED.inc()
    ORDER_VALUE.observe(float(order.grand_total))
    if coupon is not None:
        COUPON_DISCOUNT.labels(coupon.funded_by.value).inc(float(order.discount))
    for reason in bill.surge_reasons:
        SURGE_ORDERS.labels(reason).inc()
    log_event(
        log, logging.INFO, "order placed", order_id=order.id, restaurant_id=order.restaurant_id, total=order.grand_total
    )
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
        coupons.release_for_order(db, order.id)  # the customer can use the coupon again
        order.cancel_reason = note

    order.status = target
    db.add(OrderStatusEvent(order_id=order.id, from_status=current, to_status=target, actor=actor, note=note))
    # Counted only if this transaction commits (see app/core/metrics.py).
    after_commit(db, lambda: ORDER_STATUS_CHANGES.labels(target.value, actor).inc())
    # Tell the notifications service, in the same transaction (the outbox pattern).
    _publish(db, order, "order.status_changed", previous=current, actor=actor, note=note)

    log_event(
        log, logging.INFO, "order status changed", order_id=order.id, frm=current.value, to=target.value, actor=actor
    )


def _publish(
    db: Session, order: Order, event_type: str, previous: OrderStatus | None, actor: str, note: str | None = None
) -> None:
    """Write an outbox event carrying everything a consumer needs, so the
    notifications service never has to read the orders or restaurants tables."""
    restaurant = db.get(Restaurant, order.restaurant_id)
    outbox.record(
        db,
        event_type,
        "order",
        order.id,
        {
            "order_id": str(order.id),
            "customer_id": str(order.customer_id),
            "restaurant_id": str(order.restaurant_id),
            "restaurant_name": restaurant.name,
            "owner_id": str(restaurant.owner_id),
            "status": order.status.value,
            "previous_status": previous.value if previous else None,
            "actor": actor,
            "note": note,
            "grand_total": str(order.grand_total),
            "item_count": sum(line.quantity for line in order.items),
        },
    )


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
