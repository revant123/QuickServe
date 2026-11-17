"""See a race condition with your own eyes.

40 customers try to buy the last 10 biryanis at the same moment, twice:

  1. NAIVE    read consumed into Python, check it, write consumed + 1 back
              (what most first versions of "stock -= 1" do)
  2. ATOMIC   QuickServe's single conditional UPDATE

Run:  python -m scripts.race_demo        (needs PostgreSQL running and migrated)

The naive version sleeps 5 ms between its read and its write. That stands in
for the real work an app does in between (validation, pricing, another query).
On a busy server the race happens without any sleep; on a quiet laptop the
sleep makes it show up every time.

Notice that our CHECK constraint (consumed <= stock) does NOT stop the naive
version. Every naive write stores a small, "valid" number, it's just the wrong
number, because concurrent writes overwrite each other (a lost update).
Constraints catch impossible values. Only atomic updates or locks prevent lost updates.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlalchemy import delete, select

import app.database.models  # noqa: F401
from app.database.session import SessionLocal
from app.modules.menu import repository as menu_repo
from app.modules.menu.model import MenuItem
from app.modules.restaurants.model import Restaurant
from app.modules.users.model import User

STOCK, CUSTOMERS = 10, 40


def setup():
    with SessionLocal() as db:
        owner = User(name="Race Owner", email=f"race-{time.time_ns()}@demo.in", password_hash="x")
        db.add(owner)
        db.flush()
        r = Restaurant(owner_id=owner.id, name="Race Demo Kitchen", address="Demo", packaging_charge=Decimal("0"))
        db.add(r)
        db.flush()
        item = MenuItem(restaurant_id=r.id, name="Biryani", price=Decimal("250"), stock=STOCK, consumed=0)
        db.add(item)
        db.commit()
        return owner.id, r.id, item.id


def teardown(owner_id, restaurant_id, item_id):
    with SessionLocal() as db:
        db.execute(delete(MenuItem).where(MenuItem.id == item_id))
        db.execute(delete(Restaurant).where(Restaurant.id == restaurant_id))
        db.execute(delete(User).where(User.id == owner_id))
        db.commit()


def naive_buy(item_id) -> bool:
    with SessionLocal() as db:
        item = db.execute(select(MenuItem).where(MenuItem.id == item_id)).scalar_one()
        if item.consumed + 1 > item.stock:
            return False
        time.sleep(0.005)  # the gap where the race lives
        item.consumed = item.consumed + 1  # computed in Python from a stale read
        db.commit()  # UPDATE menu_items SET consumed = 4 ... (a literal!)
        return True


def atomic_buy(restaurant_id, item_id) -> bool:
    with SessionLocal() as db:
        row = menu_repo.consume_atomically(db, item_id, restaurant_id, 1)
        db.commit()  # UPDATE ... SET consumed = consumed + 1 WHERE ... <= stock
        return row is not None


def race(fn) -> int:
    barrier = threading.Barrier(CUSTOMERS)

    def worker(_):
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(CUSTOMERS) as pool:
        return sum(pool.map(worker, range(CUSTOMERS)))


def main():
    for label, make_buyer in (
        ("NAIVE ", lambda rid, iid: lambda: naive_buy(iid)),
        ("ATOMIC", lambda rid, iid: lambda: atomic_buy(rid, iid)),
    ):
        owner_id, rid, iid = setup()
        try:
            accepted = race(make_buyer(rid, iid))
            with SessionLocal() as db:
                consumed = db.get(MenuItem, iid).consumed
            print(f"{label}: {accepted:>2} orders accepted for {STOCK} biryanis | consumed counter says {consumed:>2}")
            if accepted > STOCK:
                print(
                    f"        oversold by {accepted - STOCK}; the counter missed {accepted - consumed} sales (lost updates)"
                )
        finally:
            teardown(owner_id, rid, iid)


if __name__ == "__main__":
    main()
