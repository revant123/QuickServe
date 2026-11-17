"""Write events to the outbox (producers) and claim them for delivery (the notifier)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.modules.outbox.model import OutboxEvent


def record(db: Session, event_type: str, aggregate_type: str, aggregate_id: uuid.UUID, payload: dict) -> OutboxEvent:
    """Add an event to the CURRENT transaction. It becomes visible only if the
    caller's transaction commits, together with the change it describes."""
    event = OutboxEvent(
        event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id, payload=payload
    )
    db.add(event)
    return event


def claim_batch(db: Session, now: datetime, batch: int) -> list[OutboxEvent]:
    """Lock up to `batch` events that are ready to deliver.

    Two rules:
      - Per order, only the OLDEST waiting event is claimable. If "PAID" failed
        and is waiting to be retried, "ACCEPTED" for the same order waits behind
        it, so a customer never hears "accepted" before "payment received".
        This holds even with several notifiers running.
      - FOR UPDATE SKIP LOCKED: several notifiers can run at once; each takes
        events nobody else holds, so no event is delivered twice at the same time.
    """
    earlier = aliased(OutboxEvent)
    earlier_pending = exists().where(
        and_(
            earlier.aggregate_id == OutboxEvent.aggregate_id,
            earlier.id < OutboxEvent.id,
            earlier.published_at.is_(None),
            earlier.dead_at.is_(None),
        )
    )
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.dead_at.is_(None),
            OutboxEvent.available_at <= now,
            ~earlier_pending,
        )
        .order_by(OutboxEvent.id)
        .limit(batch)
        .with_for_update(skip_locked=True, of=OutboxEvent)
        .execution_options(populate_existing=True)
    )
    return list(db.execute(stmt).scalars())


def retry_delay(attempts: int) -> timedelta:
    """Exponential backoff: 2, 4, 8, 16 ... seconds, at most 5 minutes.
    A struggling dependency gets breathing room instead of a retry storm."""
    return timedelta(seconds=min(2**attempts, 300))


def backlog(db: Session, now: datetime) -> tuple[int, float, int]:
    """(events waiting, age in seconds of the oldest one, events given up on)."""
    pending, oldest = db.execute(
        select(func.count(), func.min(OutboxEvent.created_at)).where(
            OutboxEvent.published_at.is_(None), OutboxEvent.dead_at.is_(None)
        )
    ).one()
    dead = db.execute(select(func.count()).where(OutboxEvent.dead_at.is_not(None))).scalar_one()
    age = (now - oldest).total_seconds() if oldest else 0.0
    return pending, max(age, 0.0), dead


def delete_published_before(db: Session, cutoff: datetime, batch: int = 1000) -> int:
    """Retention: delivered events are only kept for a while (FinOps: the table
    would otherwise grow forever). Small batches keep each delete short."""
    ids = select(OutboxEvent.id).where(OutboxEvent.published_at < cutoff).limit(batch).scalar_subquery()
    return db.execute(delete(OutboxEvent).where(OutboxEvent.id.in_(ids))).rowcount
