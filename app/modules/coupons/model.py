import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, Timestamps, UUIDPrimaryKey
from app.modules.pricing.calculator import CouponKind


class CouponFunder(str, enum.Enum):
    """Who pays for the discount. It matters for the restaurant's payout: a
    platform coupon is the platform's marketing cost, a restaurant coupon comes
    out of the restaurant's share."""

    PLATFORM = "PLATFORM"
    RESTAURANT = "RESTAURANT"


class RedemptionStatus(str, enum.Enum):
    APPLIED = "APPLIED"  # on a live order: counts towards the limits
    RELEASED = "RELEASED"  # the order failed (cancelled, rejected, unpaid): the use is given back


class Coupon(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(String(30), unique=True)  # always stored in capitals
    description: Mapped[str] = mapped_column(String(200))
    kind: Mapped[CouponKind] = mapped_column(Enum(CouponKind, name="coupon_kind"))
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # percent, or rupees
    max_discount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # cap for percent coupons
    min_order_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), server_default=text("0"))
    # NULL: any restaurant. Set: only that restaurant's orders.
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("restaurants.id"), index=True)
    funded_by: Mapped[CouponFunder] = mapped_column(Enum(CouponFunder, name="coupon_funder"))
    first_order_only: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    max_uses_total: Mapped[int | None] = mapped_column(Integer)  # NULL: unlimited
    max_uses_per_user: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    times_used: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint("kind <> 'PERCENT' OR value <= 100", name="percent_at_most_100"),
        CheckConstraint("max_uses_per_user >= 1", name="per_user_at_least_1"),
        # The last line of defence for a limited coupon: even a bug in the code
        # can't make the database record more uses than allowed.
        CheckConstraint(
            "times_used >= 0 AND (max_uses_total IS NULL OR times_used <= max_uses_total)", name="uses_within_limit"
        ),
    )


class CouponRedemption(UUIDPrimaryKey, Base):
    """One use of a coupon, by one customer, on one order."""

    __tablename__ = "coupon_redemptions"

    coupon_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coupons.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # unique: one coupon per order, and a retried request can't apply it twice.
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[RedemptionStatus] = mapped_column(
        Enum(RedemptionStatus, name="redemption_status"), default=RedemptionStatus.APPLIED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Serves "how many times has this customer used this coupon?"
        Index("ix_coupon_redemptions_coupon_user", "coupon_id", "user_id"),
    )
