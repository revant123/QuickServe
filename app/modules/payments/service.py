"""Mock payment processing with idempotency.

Real problem this solves: the customer taps "Pay", the network times out, the
app retries. Without idempotency the second request charges them again. With
an Idempotency-Key header, the retry carries the same key, and we return the
first result instead of creating a second charge.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from app.core.config import Settings
from app.core.exceptions import Conflict, NotFound
from app.core.metrics import PAYMENTS, after_commit
from app.database.session import transaction
from app.modules.menu.repository import db_now
from app.modules.orders import service as orders
from app.modules.orders.model import Order, OrderStatus
from app.modules.payments.model import Payment, PaymentStatus
from app.modules.payments.schema import SimulatedOutcome
from app.modules.users.model import User


def _by_key(db: Session, key: str) -> Payment | None:
    return db.execute(select(Payment).where(Payment.idempotency_key == key)).scalar_one_or_none()


def pay(
    db: Session,
    order_id: uuid.UUID,
    idempotency_key: str,
    outcome: SimulatedOutcome,
    customer: User,
    settings: Settings | None = None,
) -> tuple[Payment, bool]:
    """Returns (payment, replayed). replayed=True means this key was seen before.

    Only the customer who placed the order can pay for it.
    """
    # Only the owner is checked here, so don't load the order's items: the
    # relationship is eager (selectin), and a trace showed order_items being read
    # twice per payment, here and again under the lock below (Phase 15).
    order = db.get(Order, order_id, options=[lazyload(Order.items)])
    if order is None or order.customer_id != customer.id:
        raise NotFound("Order not found")

    existing = _by_key(db, idempotency_key)
    if existing is not None:
        if existing.order_id != order_id:
            raise Conflict("This Idempotency-Key was already used for a different order")
        return existing, True

    try:
        with transaction(db):
            order = orders.lock_order(db, order_id)
            # Check the key AGAIN, now that we hold the order lock. If the same
            # request arrived twice at once, the other copy may have committed a
            # payment while we were waiting for the lock. (A concurrency test
            # caught this: without the re-check, the second tap got "Order is PAID"
            # instead of the first tap's result.)
            winner = _by_key(db, idempotency_key)
            if winner is not None:
                if winner.order_id != order_id:
                    raise Conflict("This Idempotency-Key was already used for a different order")
                return winner, True
            now = db_now(db)
            if order.status is not OrderStatus.PLACED:
                raise Conflict(f"Order is {order.status.value}; it cannot be paid")
            if now > order.pay_by:
                raise Conflict("The payment window for this order has expired")

            ok = outcome is SimulatedOutcome.success
            payment = Payment(
                order_id=order.id,
                amount=order.grand_total,
                status=PaymentStatus.SUCCESS if ok else PaymentStatus.FAILED,
                idempotency_key=idempotency_key,
                provider_reference=f"MOCK-{uuid.uuid4().hex[:12].upper()}",
                failure_reason=None if ok else "Payment declined (simulated)",
            )
            db.add(payment)
            db.flush()  # a duplicate key or a second SUCCESS fails here, before we touch the order
            after_commit(db, lambda: PAYMENTS.labels("success" if ok else "failed").inc())
            if ok:
                orders.mark_paid(db, order, now, settings)
            # A failed attempt leaves the order PLACED: the customer may retry
            # with a new key until pay_by. The timeout job cleans up after that.
    except IntegrityError:
        # Two requests with the same key raced; the other one committed first.
        winner = _by_key(db, idempotency_key)
        if winner is not None and winner.order_id == order_id:
            return winner, True
        raise Conflict("This order already has a successful payment") from None
    return payment, False


def list_for_order(db: Session, order_id: uuid.UUID, user: User) -> list[Payment]:
    orders.get_order(db, order_id, user)  # same visibility rules as the order itself
    return list(db.execute(select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at)).scalars())


def get_payment(db: Session, payment_id: uuid.UUID, user: User) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise NotFound("Payment not found")
    try:
        orders.get_order(db, payment.order_id, user)
    except NotFound:
        raise NotFound("Payment not found") from None
    return payment
