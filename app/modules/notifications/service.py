"""The notifications service: turns outbox events into notifications, and lets
people read theirs. It never imports the orders module: everything it needs
arrives in the event payload, so it could become a separate deployable service
(its own database, events from Kafka or SQS) without changing its logic."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.modules.notifications.model import Notification
from app.modules.notifications.templates import Message, messages_for
from app.modules.outbox.model import OutboxEvent
from app.modules.users.model import User


def handle_event(db: Session, event: OutboxEvent) -> list[Message]:
    """Create this event's notifications. Safe to run twice for the same event:
    ON CONFLICT DO NOTHING on (event_id, user_id) skips anything already created.
    Returns only the notifications that are new this time."""
    created = []
    order_id = event.payload.get("order_id")
    for msg in messages_for(event.event_type, event.payload):
        stmt = (
            insert(Notification)
            .values(
                id=uuid.uuid4(),
                event_id=event.id,
                user_id=uuid.UUID(msg.user_id),
                order_id=uuid.UUID(order_id) if order_id else None,
                kind=msg.kind,
                title=msg.title,
                body=msg.body,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_event_user")
            .returning(Notification.id)  # a row comes back only if it was really inserted
        )
        if db.execute(stmt).scalar_one_or_none() is not None:
            created.append(msg)
    return created


def list_for_user(db: Session, user: User, unread_only: bool = False, limit: int = 50) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    # created_at ties when one event notifies about several steps in one
    # transaction; event_id (a growing number) keeps the true order.
    newest_first = stmt.order_by(Notification.created_at.desc(), Notification.event_id.desc())
    return list(db.execute(newest_first.limit(limit)).scalars())


def mark_read(db: Session, notification_id: uuid.UUID, user: User) -> Notification:
    """Only your own notifications: someone else's is "not found", never "forbidden"."""
    note = db.get(Notification, notification_id)
    if note is None or note.user_id != user.id:
        raise NotFound("Notification not found")
    if note.read_at is None:
        db.execute(update(Notification).where(Notification.id == note.id).values(read_at=func.now()))
        db.commit()
        db.refresh(note)
    return note
