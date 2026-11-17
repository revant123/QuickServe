"""The background worker: one pass, two workers at once, and a graceful stop."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select, text

from app import worker
from app.modules.orders.model import OrderStatus, OrderStatusEvent
from app.modules.orders.service import place_order
from app.modules.payments.schema import SimulatedOutcome
from app.modules.payments.service import pay
from tests.helpers import order_payload


def _expired_paid_orders(db, restaurant, customer, item, n):
    ids = []
    for _ in range(n):
        order = place_order(db, order_payload(restaurant, (item, 1)), customer)
        pay(db, order.id, f"key-{order.id}", SimulatedOutcome.success, customer)
        ids.append(order.id)
    db.execute(text("UPDATE orders SET accept_by = now() - interval '1 second'"))
    db.commit()
    return ids


def test_one_pass_rejects_orders_the_restaurant_ignored(db, restaurant, customer, make_item):
    item = make_item(stock=10)
    _expired_paid_orders(db, restaurant, customer, item, 3)
    assert worker.run_once().auto_rejected == 3
    assert worker.run_once().auto_rejected == 0  # nothing left to do


def test_two_workers_never_process_the_same_order(db, restaurant, customer, make_item):
    item = make_item(stock=50)
    ids = _expired_paid_orders(db, restaurant, customer, item, 20)

    with ThreadPoolExecutor(2) as pool:
        reports = list(pool.map(lambda _: worker.run_once(), range(2)))

    assert sum(r.auto_rejected for r in reports) == 20
    rejected_events = db.execute(
        select(func.count())
        .select_from(OrderStatusEvent)
        .where(OrderStatusEvent.order_id.in_(ids), OrderStatusEvent.to_status == OrderStatus.REJECTED)
    ).scalar_one()
    assert rejected_events == 20  # exactly one REJECTED per order, never two


def test_stop_signal_ends_the_loop_without_waiting_out_the_interval():
    worker.stop_requested.clear()
    t = threading.Thread(target=worker.run_forever, args=(60,))
    started = time.monotonic()
    t.start()
    time.sleep(0.3)
    worker.stop_requested.set()  # what the SIGTERM handler does
    t.join(timeout=5)
    try:
        assert not t.is_alive()
        assert time.monotonic() - started < 5  # not 60
    finally:
        worker.stop_requested.clear()
