"""The transactional outbox: events written in the SAME transaction as the change.

The problem it solves ("dual write"): when an order is paid we must (1) save the
new status in PostgreSQL and (2) tell another service so it can notify people.
Two separate writes can't be atomic. Save first and crash before telling: the
customer never hears about it. Tell first and the save rolls back: the customer
is told about a payment that didn't happen.

The fix: write the event as a row in this table, inside the same transaction as
the status change. Both are committed or neither is. A separate process (the
notifier, `python -m app.notifier`) reads new rows and delivers them. If it is
down, events wait here and nothing is lost.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    # A growing number, not a UUID: it gives events a natural order.
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))  # "order.placed", "order.status_changed"
    aggregate_type: Mapped[str] = mapped_column(String(32))  # "order"
    aggregate_id: Mapped[uuid.UUID]  # which order: events of one order are delivered in order
    # Everything a consumer needs, so it never has to read the orders tables
    # ("event-carried state transfer"). A real separate service couldn't.
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Phase 15: the W3C traceparent of the request that wrote the event, so the
    # notifier's work continues the SAME trace, seconds or hours later. A message
    # queue would carry it as a message header; a table carries it as a column.
    trace_parent: Mapped[str | None] = mapped_column(String(55))

    # Delivery bookkeeping, written only by the notifier.
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # gave up: needs a human

    __table_args__ = (
        # The notifier's question, "what's waiting, per order, oldest first?",
        # reads only this small partial index, however many old events exist.
        Index(
            "ix_outbox_events_pending",
            "aggregate_id",
            "id",
            postgresql_where=text("published_at IS NULL AND dead_at IS NULL"),
        ),
        # For deleting old delivered events (retention).
        Index("ix_outbox_events_published_at", "published_at", postgresql_where=text("published_at IS NOT NULL")),
    )
