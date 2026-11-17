import enum
import uuid
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, Timestamps, UUIDPrimaryKey


class PaymentStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class Payment(UUIDPrimaryKey, Timestamps, Base):
    """One row per payment attempt. An order may have many failed attempts but at
    most one successful payment."""

    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status"))
    # The client sends the same key when it retries after a timeout. A UNIQUE
    # constraint turns "charged twice" into "returned the first result".
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    provider_reference: Mapped[str] = mapped_column(String(100))
    failure_reason: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        # Business rule enforced by PostgreSQL itself: one SUCCESS per order.
        Index(
            "uq_payments_one_success_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'SUCCESS'"),
        ),
    )
