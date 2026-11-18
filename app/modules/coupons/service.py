"""Coupons: who may use which code, and using it safely when thousands try at once.

Two kinds of check, in two places:

1. find_usable(): BEFORE the order. Exists, active, in date, right
   restaurant, not used up, not used by you already, first-order rule.
   These only read, so the quote endpoint can run them too and explain
   "why not" to the customer.

2. redeem(): INSIDE the order's transaction, the race-safe version. Two
   checks that passed in step 1 for two customers at the same moment can't
   both be true if only one use is left. The UPDATE ... WHERE times_used <
   max_uses_total is atomic (the same trick as stock in Phase 2), and it
   locks the coupon row until the order commits, so the per-customer count
   right after it can't be raced either.
"""

import uuid
from datetime import datetime

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, CouponRejected, Forbidden
from app.database.session import transaction
from app.modules.coupons.model import Coupon, CouponFunder, CouponRedemption, RedemptionStatus
from app.modules.coupons.schema import CouponCreate
from app.modules.orders.model import Order
from app.modules.orders.state_machine import FAILED_ENDINGS
from app.modules.pricing.calculator import CouponTerms
from app.modules.restaurants.service import ensure_can_manage
from app.modules.users.model import Role, User


def normalise(code: str) -> str:
    return code.strip().upper()


def terms(coupon: Coupon) -> CouponTerms:
    return CouponTerms(coupon.code, coupon.kind, coupon.value, coupon.max_discount, coupon.min_order_value)


def _uses_by(db: Session, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        CouponRedemption.coupon_id == coupon_id,
        CouponRedemption.user_id == user_id,
        CouponRedemption.status == RedemptionStatus.APPLIED,
    )
    return db.execute(stmt).scalar_one()


def _has_previous_order(db: Session, user_id: uuid.UUID, exclude: uuid.UUID | None = None) -> bool:
    """Any order that didn't fail counts: a cancelled first order doesn't use up "first order"."""
    cond = [Order.customer_id == user_id, Order.status.not_in(FAILED_ENDINGS)]
    if exclude is not None:
        cond.append(Order.id != exclude)
    return db.execute(select(exists().where(*cond))).scalar_one()


def find_usable(db: Session, code: str, restaurant_id: uuid.UUID, customer: User, now: datetime) -> Coupon:
    coupon = db.execute(select(Coupon).where(Coupon.code == normalise(code))).scalar_one_or_none()
    if coupon is None or not coupon.is_active:
        raise CouponRejected(f"{normalise(code)} isn't a valid coupon")
    if coupon.valid_from > now:
        raise CouponRejected(f"{coupon.code} isn't active yet")
    if coupon.valid_until is not None and coupon.valid_until <= now:
        raise CouponRejected(f"{coupon.code} has expired")
    if coupon.restaurant_id is not None and coupon.restaurant_id != restaurant_id:
        raise CouponRejected(f"{coupon.code} only works at a different restaurant")
    if coupon.max_uses_total is not None and coupon.times_used >= coupon.max_uses_total:
        raise CouponRejected(f"{coupon.code} has been fully used")
    if coupon.first_order_only and _has_previous_order(db, customer.id):
        raise CouponRejected(f"{coupon.code} is only for your first order")
    if _uses_by(db, coupon.id, customer.id) >= coupon.max_uses_per_user:
        raise CouponRejected(f"You've already used {coupon.code}")
    return coupon


def redeem(db: Session, coupon: Coupon, customer: User, order: Order) -> None:
    """Inside the order's transaction, after the order row exists (flushed)."""
    claimed = db.execute(
        update(Coupon)
        .where(
            Coupon.id == coupon.id,
            or_(Coupon.max_uses_total.is_(None), Coupon.times_used < Coupon.max_uses_total),
        )
        .values(times_used=Coupon.times_used + 1)
        .returning(Coupon.id)
    ).scalar_one_or_none()
    if claimed is None:
        raise CouponRejected(f"{coupon.code} has just been fully used")
    # From here this transaction holds the coupon row's lock until it commits.
    # Any other order using this coupon waits at the UPDATE above, so these
    # counts include every other use that has committed: no race.
    if _uses_by(db, coupon.id, customer.id) >= coupon.max_uses_per_user:
        raise CouponRejected(f"You've already used {coupon.code}")
    if coupon.first_order_only and _has_previous_order(db, customer.id, exclude=order.id):
        raise CouponRejected(f"{coupon.code} is only for your first order")
    db.add(CouponRedemption(coupon_id=coupon.id, user_id=customer.id, order_id=order.id, discount=order.discount))


def release_for_order(db: Session, order_id: uuid.UUID) -> bool:
    """The order failed (cancelled, rejected, never paid): give the use back.
    Runs inside the status change's transaction. Safe to call twice."""
    coupon_id = db.execute(
        update(CouponRedemption)
        .where(CouponRedemption.order_id == order_id, CouponRedemption.status == RedemptionStatus.APPLIED)
        .values(status=RedemptionStatus.RELEASED, released_at=func.now())
        .returning(CouponRedemption.coupon_id)
    ).scalar_one_or_none()
    if coupon_id is None:
        return False
    db.execute(update(Coupon).where(Coupon.id == coupon_id).values(times_used=Coupon.times_used - 1))
    return True


def create_coupon(db: Session, data: CouponCreate, user: User) -> Coupon:
    """Admins create platform-funded coupons (for all restaurants, or one).
    Owners create coupons for their own restaurant, which they pay for."""
    if user.role is Role.ADMIN:
        funded_by = CouponFunder.PLATFORM
        if data.restaurant_id is not None:
            ensure_can_manage(db, data.restaurant_id, user)  # 404 if it doesn't exist
    elif user.role is Role.RESTAURANT_OWNER:
        if data.restaurant_id is None:
            raise Forbidden("Restaurant owners can only create coupons for their own restaurant")
        ensure_can_manage(db, data.restaurant_id, user)
        funded_by = CouponFunder.RESTAURANT
    else:
        raise Forbidden("Only admins and restaurant owners can create coupons")
    try:
        with transaction(db):
            coupon = Coupon(**data.model_dump(exclude={"code"}), code=normalise(data.code), funded_by=funded_by)
            db.add(coupon)
    except IntegrityError as exc:
        raise Conflict(f"A coupon called {normalise(data.code)} already exists") from exc
    return coupon


def list_available(db: Session, restaurant_id: uuid.UUID | None, now: datetime) -> list[Coupon]:
    """What a customer can see on the checkout page (before the per-customer rules)."""
    stmt = select(Coupon).where(
        Coupon.is_active.is_(True),
        Coupon.valid_from <= now,
        or_(Coupon.valid_until.is_(None), Coupon.valid_until > now),
        or_(Coupon.max_uses_total.is_(None), Coupon.times_used < Coupon.max_uses_total),
    )
    if restaurant_id is None:
        stmt = stmt.where(Coupon.restaurant_id.is_(None))
    else:
        stmt = stmt.where(or_(Coupon.restaurant_id.is_(None), Coupon.restaurant_id == restaurant_id))
    return list(db.execute(stmt.order_by(Coupon.code)).scalars())
