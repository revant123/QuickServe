"""In-app notifications ("Your food is being prepared"), one row per person per event."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKey


class Notification(UUIDPrimaryKey, Base):
    __tablename__ = "notifications"

    # The outbox event this came from. Not a foreign key on purpose: the
    # notifications service must not depend on the orders service's tables, and
    # old outbox rows are deleted after a week while notifications stay.
    event_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    order_id: Mapped[uuid.UUID | None]
    kind: Mapped[str] = mapped_column(String(40))  # "order.paid", "order.new_for_restaurant", ...
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # The idempotency guard. Delivery is at-least-once: the same event may be
        # handled twice (a crash after handling, before marking it done). This
        # constraint makes the second time a no-op instead of a duplicate message.
        UniqueConstraint("event_id", "user_id", name="uq_notifications_event_user"),
        # "My notifications, newest first", the only list query.
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )
