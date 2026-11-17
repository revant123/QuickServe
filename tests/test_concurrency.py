"""Race conditions, tested with real threads and separate database connections.

These are the tests that a plain "stock -= 1 in Python" design fails.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.core.exceptions import OutOfStock
from app.database.session import SessionLocal
from app.modules.menu import repository as menu_repo
from app.modules.menu.service import restock
from app.modules.orders.model import OrderItem
from app.modules.orders.service import place_order
from tests.helpers import order_payload


def _run_concurrently(n: int, fn):
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()  # release all threads at the same instant
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def test_forty_customers_ten_biryanis(db, restaurant, customer, make_item):
    item = make_item("Hyderabadi Biryani", "280.00", stock=10)
    payload = order_payload(customer, restaurant, (item, 1))

    def try_order(_):
        session = SessionLocal()
        try:
            place_order(session, payload)
            return "ok"
        except OutOfStock:
            return "sold out"
        finally:
            session.close()

    results = _run_concurrently(40, try_order)

    assert results.count("ok") == 10
    assert results.count("sold out") == 30
    db.refresh(item)
    assert item.consumed == 10 and item.available == 0


def test_restock_in_the_middle_of_a_rush_loses_nothing(db, restaurant, customer, make_item):
    """Orders and a restock race. Every sold unit must be counted in exactly one cycle."""
    item = make_item("Masala Chai", "30.00", stock=500)
    payload = order_payload(customer, restaurant, (item, 1))

    def act(i):
        session = SessionLocal()
        try:
            if i == 15:
                restock(session, item.id, quantity=500, carry_over_leftover=False)
                return "restock"
            place_order(session, payload)
            return "ok"
        finally:
            session.close()

    results = _run_concurrently(30, act)
    sold = results.count("ok")

    cycles = menu_repo.list_cycles(db, item.id)
    db.refresh(item)
    assert len(cycles) == 2
    assert cycles[0].units_consumed + item.consumed == sold

    # Each order line remembers its cycle, and the per-cycle counts agree with it.
    per_cycle = dict(
        db.execute(
            select(OrderItem.cycle_no, func.sum(OrderItem.quantity))
            .where(OrderItem.menu_item_id == item.id)
            .group_by(OrderItem.cycle_no)
        ).all()
    )
    assert per_cycle.get(1, 0) == cycles[0].units_consumed
    assert per_cycle.get(2, 0) == item.consumed
