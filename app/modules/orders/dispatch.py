"""Riders: the pool of orders waiting for a rider, claiming one, and a rider's day (Phase 14).

How the real apps do it: Swiggy and Zomato *push* each order to the rider
their models pick (nearest, already heading that way, likely to accept), and
can batch two orders on one trip. That needs live rider locations and an
optimiser. QuickServe uses the simpler *pull* model several delivery
platforms started with: accepted orders wait in a pool, a rider claims one,
and the database guarantees nobody else gets it.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import Conflict, InvalidTransition, NotFound
from app.database.session import transaction
from app.modules.orders.model import Order, OrderItem, OrderStatus
from app.modules.orders.schema import PoolOrder, RiderDay, RiderOrder
from app.modules.outbox import service as outbox
from app.modules.restaurants.model import Restaurant
from app.modules.users.model import User

# A rider may claim an order once the restaurant has accepted it: they ride
# over while it cooks ("just in time"), instead of waiting until it's packed.
POOL = (OrderStatus.ACCEPTED, OrderStatus.PREPARING, OrderStatus.READY)
ACTIVE = (*POOL, OrderStatus.OUT_FOR_DELIVERY)


def business_day(day: date, settings: Settings) -> tuple[datetime, datetime]:
    """[start, end) of one calendar day in the business's time zone, as aware datetimes.

    "Today" for a Chandigarh restaurant starts at midnight IST, which is 18:30
    UTC the day before. Grouping by the UTC date would put a 1 a.m. order on
    the previous day's report.
    """
    tz = ZoneInfo(settings.pricing_timezone)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def today(now: datetime, settings: Settings) -> date:
    return now.astimezone(ZoneInfo(settings.pricing_timezone)).date()


def rider_pay_expression(settings: Settings):
    """base + per_km x distance, rounded to whole rupees, computed in SQL so the
    claim stays a single UPDATE."""
    return func.round(
        settings.rider_base_pay + settings.rider_pay_per_km * func.coalesce(Order.distance_km, 0),
        0,
    )


def rider_pay_for(distance_km: Decimal | None, settings: Settings) -> Decimal:
    raw = settings.rider_base_pay + settings.rider_pay_per_km * (distance_km or Decimal("0"))
    return raw.quantize(Decimal("1"))


def pool(db: Session, settings: Settings | None = None, limit: int = 20) -> list[PoolOrder]:
    """Orders waiting for a rider: food nearly ready first, then oldest first.

    No customer address here. A rider sees the drop location only after they
    claim the order, so a customer's address isn't shown to every rider in the city.
    """
    settings = settings or get_settings()
    readiness = case(
        (Order.status == OrderStatus.READY, 0),
        (Order.status == OrderStatus.PREPARING, 1),
        else_=2,
    )
    item_count = (
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id == Order.id)
        .correlate(Order)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Order, Restaurant.name, Restaurant.address, item_count)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(Order.rider_id.is_(None), Order.status.in_(POOL))
        .order_by(readiness, Order.created_at)
        .limit(limit)
    ).all()
    return [
        PoolOrder(
            id=o.id,
            status=o.status,
            restaurant_name=name,
            restaurant_address=address,
            distance_km=o.distance_km,
            item_count=count,
            rider_pay=rider_pay_for(o.distance_km, settings),
            created_at=o.created_at,
        )
        for o, name, address, count in rows
    ]


def claim(db: Session, order_id: uuid.UUID, rider: User, settings: Settings | None = None) -> Order:
    """Give this order to this rider, if nobody else has it.

    One conditional UPDATE does the check and the write together, like the
    stock counter in Phase 1: `WHERE rider_id IS NULL AND status IN (...)`.
    If two riders tap "Accept" at the same moment, the second UPDATE waits for
    the first one's row lock, re-checks the WHERE clause, finds rider_id set,
    and changes nothing.
    """
    settings = settings or get_settings()
    try:
        with transaction(db):
            claimed = db.execute(
                update(Order)
                .where(Order.id == order_id, Order.rider_id.is_(None), Order.status.in_(POOL))
                .values(rider_id=rider.id, rider_assigned_at=func.now(), rider_pay=rider_pay_expression(settings))
                .returning(Order.id)
            ).scalar_one_or_none()
            if claimed is None:
                raise _why_not_claimable(db, order_id, rider)
            order = db.get(Order, order_id, populate_existing=True)
            _publish_assigned(db, order, rider)
    except IntegrityError as exc:
        # uq_orders_one_active_delivery_per_rider: this rider already has an
        # order in flight (two claims at once, from two taps or two phones).
        if "uq_orders_one_active_delivery_per_rider" in str(exc.orig):
            raise Conflict("Finish your current delivery before taking another") from None
        raise
    return order


def _why_not_claimable(db: Session, order_id: uuid.UUID, rider: User) -> Exception:
    order = db.get(Order, order_id, populate_existing=True)
    if order is None or order.status not in (*POOL, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED):
        # Unpaid, rejected or cancelled orders are none of a rider's business.
        return NotFound("Order not found")
    if order.rider_id == rider.id:
        return Conflict("This order is already yours")
    if order.rider_id is not None:
        return Conflict("Another delivery partner has taken this order")
    return Conflict("This order can't be picked up any more")


def _publish_assigned(db: Session, order: Order, rider: User) -> None:
    restaurant = db.get(Restaurant, order.restaurant_id)
    outbox.record(
        db,
        "order.rider_assigned",
        "order",
        order.id,
        {
            "order_id": str(order.id),
            "customer_id": str(order.customer_id),
            "restaurant_id": str(order.restaurant_id),
            "restaurant_name": restaurant.name,
            "owner_id": str(restaurant.owner_id),
            "status": order.status.value,
            "rider_name": rider.name,
            "grand_total": str(order.grand_total),
        },
    )


def release(db: Session, order_id: uuid.UUID, rider: User) -> Order:
    """The rider can't make it (a flat tyre): put the order back in the pool.
    Only before pickup; once the food is on the bike, it's theirs to deliver."""
    with transaction(db):
        order = db.execute(
            select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if order is None or order.rider_id != rider.id:
            raise NotFound("Order not found")
        if order.status not in POOL:
            raise InvalidTransition("The order has been picked up; it can't go back to the pool")
        order.rider_id = None
        order.rider_assigned_at = None
        order.rider_pay = None
    return order


def rider_order(db: Session, order: Order) -> RiderOrder:
    restaurant = db.get(Restaurant, order.restaurant_id)
    return RiderOrder(
        id=order.id,
        status=order.status,
        restaurant_name=restaurant.name,
        restaurant_address=restaurant.address,
        restaurant_latitude=restaurant.latitude,
        restaurant_longitude=restaurant.longitude,
        delivery_address=order.delivery_address,
        delivery_latitude=order.delivery_latitude,
        delivery_longitude=order.delivery_longitude,
        distance_km=order.distance_km,
        item_count=sum(line.quantity for line in order.items),
        rider_pay=order.rider_pay,
        assigned_at=order.rider_assigned_at,
        created_at=order.created_at,
    )


def my_day(db: Session, rider: User, settings: Settings | None = None) -> RiderDay:
    """The rider app's home: the delivery in progress (if any) and today's earnings."""
    settings = settings or get_settings()
    now = db.execute(select(func.now())).scalar_one()
    start, end = business_day(today(now, settings), settings)
    active = db.execute(select(Order).where(Order.rider_id == rider.id, Order.status.in_(ACTIVE))).scalar_one_or_none()
    delivered = (
        db.execute(
            select(Order)
            .where(
                Order.rider_id == rider.id,
                Order.status == OrderStatus.DELIVERED,
                Order.created_at >= start,
                Order.created_at < end,
            )
            .order_by(Order.created_at.desc())
        )
        .scalars()
        .all()
    )
    return RiderDay(
        active=rider_order(db, active) if active else None,
        delivered_today=[rider_order(db, o) for o in delivered],
        deliveries_today=len(delivered),
        earnings_today=sum((o.rider_pay or Decimal("0") for o in delivered), Decimal("0")),
    )
