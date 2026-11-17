import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.orders.model import Order, OrderStatus, OrderStatusEvent


def lock_order(db: Session, order_id: uuid.UUID) -> Order | None:
    """SELECT ... FROM orders WHERE id = :id FOR UPDATE

    Two actors can act on one order at the same moment: the restaurant taps
    "Accept" just as the timeout job rejects it. Locking the row makes them take
    turns; the second one sees the new status and fails the transition check.
    """
    return db.execute(
        select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()


def claim_expired(db: Session, status: OrderStatus, deadline_column, now: datetime, batch: int) -> list[Order]:
    """SELECT ... WHERE status = :s AND <deadline> < now() ORDER BY <deadline>
       LIMIT :batch FOR UPDATE SKIP LOCKED

    SKIP LOCKED lets several job workers run at once without stepping on each
    other: each one grabs rows nobody else has locked and skips the rest.
    """
    stmt = (
        select(Order)
        .where(Order.status == status, deadline_column < now)
        .order_by(deadline_column)
        .limit(batch)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return list(db.execute(stmt).scalars())


def list_events(db: Session, order_id: uuid.UUID) -> list[OrderStatusEvent]:
    stmt = select(OrderStatusEvent).where(OrderStatusEvent.order_id == order_id).order_by(OrderStatusEvent.created_at)
    return list(db.execute(stmt).scalars())
