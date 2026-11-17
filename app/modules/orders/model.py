import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, func
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

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
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

    pay_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accept_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))

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
