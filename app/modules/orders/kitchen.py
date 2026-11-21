"""The restaurant partner's view: the live order board and the day's sales (Phase 14)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFound
from app.core.money import rupees
from app.modules.coupons.model import Coupon, CouponFunder
from app.modules.orders.dispatch import business_day, today
from app.modules.orders.model import Order, OrderItem, OrderStatus, OrderStatusEvent
from app.modules.orders.schema import KitchenItem, KitchenOrder, SalesReport, TopItem
from app.modules.orders.state_machine import AUTO_REJECT_REASON
from app.modules.restaurants.model import Restaurant
from app.modules.restaurants.service import owns_restaurant
from app.modules.users.model import User

# The board's "To do" column: everything the kitchen still has to act on.
# Once a rider has the food, the kitchen is done with it.
ACTIVE = (OrderStatus.PAID, OrderStatus.ACCEPTED, OrderStatus.PREPARING, OrderStatus.READY)
# The restaurant never sees unpaid orders (Zomato and Swiggy don't show them either).
NEVER_SHOWN = (OrderStatus.PLACED, OrderStatus.PAYMENT_FAILED)


def _owned(db: Session, restaurant_id: uuid.UUID, user: User) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    # 404, not 403, for someone else's restaurant: don't confirm what exists.
    if restaurant is None or not owns_restaurant(db, restaurant_id, user):
        raise NotFound("Restaurant not found")
    return restaurant


def board(db: Session, restaurant_id: uuid.UUID, user: User, view: str, limit: int = 50) -> list[KitchenOrder]:
    """The order board in a constant number of queries, however many orders.

    1. the orders;  2. all their items (selectin: one `WHERE order_id IN (...)`);
    3. the names of every customer and rider on the page, in one query.
    Fetching the names order by order would be the N+1 problem again.
    """
    _owned(db, restaurant_id, user)
    stmt = select(Order).where(Order.restaurant_id == restaurant_id)
    if view == "active":
        # Oldest first: the kitchen works first in, first out.
        stmt = stmt.where(Order.status.in_(ACTIVE)).order_by(Order.created_at)
    else:
        stmt = stmt.where(Order.status.not_in((*ACTIVE, *NEVER_SHOWN))).order_by(Order.created_at.desc()).limit(limit)
    orders = db.execute(stmt).scalars().all()

    people = {o.customer_id for o in orders} | {o.rider_id for o in orders if o.rider_id}
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_(people))).all()) if people else {}
    return [
        KitchenOrder(
            id=o.id,
            short_id=str(o.id)[-4:].upper(),
            status=o.status,
            created_at=o.created_at,
            accept_by=o.accept_by,
            items=[KitchenItem(name=line.item_name, quantity=line.quantity) for line in o.items],
            item_total=o.item_total,
            packaging_charge=o.packaging_charge,
            customer_first_name=names.get(o.customer_id, "Customer").split()[0],
            rider_name=names.get(o.rider_id) if o.rider_id else None,
            cancel_reason=o.cancel_reason,
        )
        for o in orders
    ]


def sales(
    db: Session, restaurant_id: uuid.UUID, user: User, day: date | None = None, settings: Settings | None = None
) -> SalesReport:
    """One day's numbers for one restaurant, in the restaurant's time zone.

    Payout follows the shape of an aggregator settlement: food sales, minus the
    discounts the restaurant itself funded, minus the platform's commission on
    what's left, minus GST on that commission. Delivery and platform fees and
    platform-funded discounts are the platform's business, not the restaurant's.
    """
    settings = settings or get_settings()
    _owned(db, restaurant_id, user)
    now = db.execute(select(func.now())).scalar_one()
    day = day or today(now, settings)
    start, end = business_day(day, settings)
    in_day = and_(Order.restaurant_id == restaurant_id, Order.created_at >= start, Order.created_at < end)

    delivered = Order.status == OrderStatus.DELIVERED
    restaurant_funded = Coupon.funded_by == CouponFunder.RESTAURANT
    # One pass over the day's orders, several totals at once: aggregate FILTER
    # (PostgreSQL) counts and sums different subsets in a single scan.
    row = db.execute(
        select(
            func.count().filter(delivered),
            func.count().filter(Order.status.in_((*ACTIVE, OrderStatus.OUT_FOR_DELIVERY))),
            func.count().filter(Order.status.in_((OrderStatus.REJECTED, OrderStatus.CANCELLED))),
            func.count().filter(Order.status == OrderStatus.REJECTED, Order.cancel_reason == AUTO_REJECT_REASON),
            func.coalesce(func.sum(Order.item_total + Order.packaging_charge).filter(delivered), 0),
            func.coalesce(func.sum(Order.discount).filter(delivered, restaurant_funded), 0),
        )
        .select_from(Order)
        .outerjoin(Coupon, Coupon.code == Order.coupon_code)
        .where(in_day)
    ).one()
    n_delivered, n_in_progress, n_cancelled, n_missed, food_sales, own_discounts = row

    net = Decimal(food_sales) - Decimal(own_discounts)
    commission = rupees(net * settings.restaurant_commission_percent / 100)
    gst = rupees(commission * settings.gst_on_commission_percent / 100)

    # Kitchen speed: from ACCEPTED to READY, per order, averaged. Each order's two
    # timestamps come from its status events; FILTER picks each one per group.
    accepted_at = func.min(OrderStatusEvent.created_at).filter(OrderStatusEvent.to_status == OrderStatus.ACCEPTED)
    ready_at = func.min(OrderStatusEvent.created_at).filter(OrderStatusEvent.to_status == OrderStatus.READY)
    per_order = (
        select((func.extract("epoch", ready_at - accepted_at) / 60).label("minutes"))
        .join(Order, Order.id == OrderStatusEvent.order_id)
        .where(in_day)
        .group_by(OrderStatusEvent.order_id)
        .having(ready_at.is_not(None), accepted_at.is_not(None))
        .subquery()
    )
    avg_prep = db.execute(select(func.avg(per_order.c.minutes))).scalar_one()

    top = db.execute(
        select(OrderItem.item_name, func.sum(OrderItem.quantity).label("qty"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(in_day, delivered)
        .group_by(OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.item_name)
        .limit(5)
    ).all()

    return SalesReport(
        day=day,
        timezone=settings.pricing_timezone,
        orders_delivered=n_delivered,
        orders_in_progress=n_in_progress,
        orders_cancelled=n_cancelled,
        orders_missed=n_missed,
        food_sales=rupees(food_sales),
        restaurant_discounts=rupees(own_discounts),
        commission_percent=settings.restaurant_commission_percent,
        commission=commission,
        gst_on_commission=gst,
        estimated_payout=rupees(net - commission - gst),
        avg_prep_minutes=round(float(avg_prep), 1) if avg_prep is not None else None,
        top_items=[TopItem(name=name, quantity=qty) for name, qty in top],
    )
