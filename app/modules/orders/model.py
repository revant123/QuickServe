import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, Timestamps, UUIDPrimaryKey


class OrderStatus(str, enum.Enum):
    PLACED = "PLACED"  # created, stock reserved, waiting for payment
    PAID = "PAID"  # paid, waiting for the restaurant to accept
    ACCEPTED = "ACCEPTED"  # restaurant accepted
    PREPARING = "PREPARING"  # cooking started: food now exists
    READY = "READY"  # packed, waiting for the rider
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"  # by customer or support
    REJECTED = "REJECTED"  # by restaurant, or auto-rejected after the timeout
    PAYMENT_FAILED = "PAYMENT_FAILED"  # never paid within the payment window


order_status_enum = Enum(OrderStatus, name="order_status")


class Order(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "orders"

    # Indexed together with created_at (see __table_args__): "my orders, newest first".
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id"))
    status: Mapped[OrderStatus] = mapped_column(order_status_enum, default=OrderStatus.PLACED)
    delivery_address: Mapped[str] = mapped_column(String(500))

    # The full bill is stored, not recomputed later. If the platform fee changes
    # tomorrow, yesterday's receipts must not change.
    item_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    packaging_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    platform_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    gst_food: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    gst_fees: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Phase 11. server_default 0 so orders placed before these columns existed
    # read as "no such fee", which is what they were.
    small_order_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text("0"), default=Decimal("0"))
    surge_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text("0"), default=Decimal("0"))
    surge_reasons: Mapped[str | None] = mapped_column(String(100))  # "peak,rain"
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text("0"), default=Decimal("0"))
    coupon_code: Mapped[str | None] = mapped_column(String(30))
    delivery_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    delivery_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))

    pay_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accept_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))

    # Phase 14: who delivers it. A rider claims an order from the pool once the
    # restaurant has accepted it, so they ride over while the food is cooked.
    rider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    rider_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What the rider earns for this order, fixed when they claim it (they see it
    # before they accept, like the real apps), so a settings change later can't
    # alter a job someone already took.
    rider_pay: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # The 4-digit code the customer reads out at the door. Only the customer
    # sees it; the rider must type it to mark the order DELIVERED.
    delivery_code: Mapped[str | None] = mapped_column(String(4))
    delivery_code_attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list["OrderStatusEvent"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="OrderStatusEvent.created_at",
    )

    __table_args__ = (
        # Serves the restaurant dashboard: "my PAID orders, oldest first".
        Index("ix_orders_restaurant_status", "restaurant_id", "status"),
        # Serves the timeout job: "PAID orders whose accept_by has passed".
        Index("ix_orders_status_accept_by", "status", "accept_by"),
        # Serves the customer app's "My orders" (Phase 13): one customer's orders,
        # newest first. The index is already in that order, so there's no sort
        # step, and it replaces the old index on customer_id alone.
        Index("ix_orders_customer_newest", "customer_id", text("created_at DESC")),
        # Phase 14. One active delivery per rider, enforced by the database: a
        # partial UNIQUE index only covers rows matching its WHERE clause, so a
        # rider can have any number of delivered orders but only one in flight.
        # Two simultaneous claims by the same rider can't both commit.
        Index(
            "uq_orders_one_active_delivery_per_rider",
            "rider_id",
            unique=True,
            postgresql_where=text(
                "rider_id IS NOT NULL AND status IN ('ACCEPTED', 'PREPARING', 'READY', 'OUT_FOR_DELIVERY')"
            ),
        ),
        # The riders' pool: accepted orders nobody has claimed yet. A partial
        # index stays tiny (only the few orders waiting right now), however many
        # millions of finished orders the table holds.
        Index(
            "ix_orders_rider_pool",
            "created_at",
            postgresql_where=text("rider_id IS NULL AND status IN ('ACCEPTED', 'PREPARING', 'READY')"),
        ),
        # A rider's own history ("delivered today").
        Index("ix_orders_rider_newest", "rider_id", text("created_at DESC")),
    )


class OrderItem(UUIDPrimaryKey, Base):
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id"), index=True)
    # Snapshots: the order keeps the name and price it was bought at.
    item_name: Mapped[str] = mapped_column(String(150))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Which stock cycle these units came from. Needed when a cancellation
    # arrives after a restock: we must credit the old cycle, not the new one.
    cycle_no: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class OrderStatusEvent(UUIDPrimaryKey, Base):
    """Append-only history. Powers order tracking, support tooling and, later, events
    that other services (notifications) can react to."""

    __tablename__ = "order_status_events"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    from_status: Mapped[OrderStatus | None] = mapped_column(order_status_enum)
    to_status: Mapped[OrderStatus] = mapped_column(order_status_enum)
    actor: Mapped[str] = mapped_column(String(50))  # customer / restaurant / system / support
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="events")
