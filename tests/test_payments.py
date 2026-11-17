import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import Conflict
from app.database.session import SessionLocal
from app.modules.orders.model import OrderStatus
from app.modules.orders.service import place_order
from app.modules.payments.model import Payment
from app.modules.payments.schema import SimulatedOutcome
from app.modules.payments.service import pay
from tests.helpers import order_payload


@pytest.fixture
def order(db, restaurant, customer, make_item):
    return place_order(db, order_payload(customer, restaurant, (make_item(stock=10), 1)))


def test_retry_with_same_key_does_not_charge_twice(db, order):
    first, replayed1 = pay(db, order.id, "retry-key-001", SimulatedOutcome.success)
    second, replayed2 = pay(db, order.id, "retry-key-001", SimulatedOutcome.success)
    assert first.id == second.id
    assert (replayed1, replayed2) == (False, True)
    assert db.query(Payment).filter_by(order_id=order.id).count() == 1


def test_failed_attempt_then_successful_retry(db, order):
    failed, _ = pay(db, order.id, "attempt-0001", SimulatedOutcome.failure)
    db.refresh(order)
    assert order.status is OrderStatus.PLACED and failed.failure_reason
    pay(db, order.id, "attempt-0002", SimulatedOutcome.success)
    db.refresh(order)
    assert order.status is OrderStatus.PAID and order.accept_by is not None


def test_paid_order_cannot_be_paid_again(db, order):
    pay(db, order.id, "first-key-01", SimulatedOutcome.success)
    with pytest.raises(Conflict, match="PAID"):
        pay(db, order.id, "second-key-1", SimulatedOutcome.success)


def test_database_allows_only_one_success_per_order(db, order):
    pay(db, order.id, "first-key-01", SimulatedOutcome.success)
    with pytest.raises(IntegrityError, match="uq_payments_one_success_per_order"):
        db.execute(
            text(
                "INSERT INTO payments (id, order_id, amount, status, idempotency_key, provider_reference)"
                " VALUES (gen_random_uuid(), :oid, 1, 'SUCCESS', 'sneaky-key', 'X')"
            ),
            {"oid": order.id},
        )
        db.commit()
    db.rollback()


def test_double_tap_from_two_devices_creates_one_payment(db, order):
    barrier = threading.Barrier(2)

    def tap(_):
        session = SessionLocal()
        try:
            barrier.wait()
            payment, _ = pay(session, order.id, "double-tap-key", SimulatedOutcome.success)
            return payment.id
        finally:
            session.close()

    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(tap, range(2)))
    assert ids[0] == ids[1]
    assert db.query(Payment).filter_by(order_id=order.id).count() == 1
