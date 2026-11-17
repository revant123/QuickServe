"""Best sellers, restock suggestions and menu badges, all built on archived cycles."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.modules.menu import repository as menu_repo
from app.modules.menu.analytics import best_sellers_orm, best_sellers_sql
from app.modules.menu.service import customer_menu, restock, restock_suggestion
from app.modules.orders.service import place_order
from tests.helpers import order_payload


def _sell(db, customer, restaurant, item, units, per_order):
    for _ in range(units // per_order):
        place_order(db, order_payload(customer, restaurant, (item, per_order)))


def _set_cycle_times(db, item, cycle_no, *, started_h_ago, sold_out_h_ago=None, closed_h_ago=0.0):
    db.execute(
        text("""UPDATE inventory_cycles
                   SET started_at  = now() - make_interval(secs => :s * 3600),
                       sold_out_at = CASE WHEN CAST(:so AS float) IS NULL THEN NULL
                                          ELSE now() - make_interval(secs => CAST(:so AS float) * 3600) END,
                       closed_at   = now() - make_interval(secs => :c * 3600)
                 WHERE menu_item_id = :id AND cycle_no = :n"""),
        {"s": started_h_ago, "so": sold_out_h_ago, "c": closed_h_ago, "id": item.id, "n": cycle_no},
    )
    db.commit()
    # We changed rows behind the ORM's back. Objects already in this session's
    # identity map still hold the old values, and a later SELECT will NOT
    # overwrite them. expire_all() makes the session reload on next access.
    db.expire_all()


@pytest.fixture
def samosa_and_biryani(db, restaurant, customer, make_item):
    """Samosa: 200 made, 120 sold over 10 hours, never sold out.
    Biryani: 20 made, all 20 gone within the first hour."""
    samosa = make_item("Samosa", "20.00", stock=200)
    biryani = make_item("Chicken Biryani", "260.00", stock=20)
    _sell(db, customer, restaurant, samosa, 120, 10)
    _sell(db, customer, restaurant, biryani, 20, 5)
    restock(db, samosa.id, 200, False)
    restock(db, biryani.id, 20, False)
    _set_cycle_times(db, samosa, 1, started_h_ago=10)
    _set_cycle_times(db, biryani, 1, started_h_ago=10, sold_out_h_ago=9)
    return samosa, biryani


def test_best_seller_is_ranked_by_rate_not_raw_volume(db, restaurant, samosa_and_biryani):
    since = menu_repo.db_now(db) - timedelta(days=7)
    report = {row["name"]: row for row in best_sellers_orm(db, restaurant.id, since)}

    samosa, biryani = report["Samosa"], report["Chicken Biryani"]
    assert samosa["units_sold"] > biryani["units_sold"]  # volume says samosa...
    assert biryani["rank"] == 1 and samosa["rank"] == 2  # ...rate says biryani
    assert biryani["sold_out_cycles"] == 1
    assert biryani["units_per_hour"] == pytest.approx(20 / 1.25)  # 1 h on sale + 15-min floor for the new cycle
    assert samosa["units_per_hour"] == pytest.approx(120 / 10.25)
    assert samosa["sell_through"] == pytest.approx(120 / 400)


def test_orm_and_raw_sql_give_identical_reports(db, restaurant, samosa_and_biryani):
    since = menu_repo.db_now(db) - timedelta(days=7)
    assert best_sellers_orm(db, restaurant.id, since) == best_sellers_sql(db, restaurant.id, since)


def test_returns_and_waste_are_not_counted_as_sales(db, restaurant, customer, make_item):
    item = make_item("Kadhai Paneer", "240.00", stock=10)
    _sell(db, customer, restaurant, item, 6, 2)
    db.execute(
        text("UPDATE inventory_cycles SET units_returned = 1, units_wasted = 1 WHERE menu_item_id = :id"),
        {"id": item.id},
    )
    db.commit()
    row = best_sellers_orm(db, restaurant.id, menu_repo.db_now(db) - timedelta(days=1))[0]
    assert row["units_sold"] == 4


def test_restock_suggestion_corrects_for_sold_out_cycles(db, restaurant, customer, make_item):
    item = make_item("Chole Bhature", "180.00", stock=20)
    _sell(db, customer, restaurant, item, 20, 5)  # cycle 1: sold out
    restock(db, item.id, 30, False)
    _set_cycle_times(db, item, 1, started_h_ago=16, sold_out_h_ago=12, closed_h_ago=8)  # sold out halfway
    _sell(db, customer, restaurant, item, 25, 5)  # cycle 2: 25 of 30, no sell-out
    restock(db, item.id, 30, False)

    s = restock_suggestion(db, item.id)

    # cycle 1: 20 sold in 4 of 8 hours -> demand ~40 ; cycle 2: 25 ; average 32.5 -> 33
    assert s.suggested_quantity == 33
    assert s.based_on_cycles == 2


def test_menu_badges(db, restaurant, customer, make_item):
    low = make_item("Gulab Jamun", "80.00", stock=10)
    fast = make_item("Momos", "120.00", stock=100)
    gone = make_item("Rasmalai", "100.00", stock=2)
    plain = make_item("Plain Rice", "90.00", stock=None, track_stock=False)
    slow = make_item("Kheer", "90.00", stock=100)
    _sell(db, customer, restaurant, low, 6, 6)
    _sell(db, customer, restaurant, fast, 60, 10)
    _sell(db, customer, restaurant, slow, 10, 10)
    _sell(db, customer, restaurant, gone, 2, 2)
    # Momos: 60 sold in the last hour, 40 left -> gone in about 40 minutes.
    # Kheer: 10 sold in 3 hours, 90 left -> about 27 hours. Not "fast".
    db.execute(
        text("UPDATE menu_items SET cycle_started_at = now() - interval '1 hour' WHERE id = :id"), {"id": fast.id}
    )
    db.execute(
        text("UPDATE menu_items SET cycle_started_at = now() - interval '3 hours' WHERE id = :id"), {"id": slow.id}
    )
    db.commit()
    # Without expire_all(), the `fast` object we still hold keeps its OLD
    # cycle_started_at: the SELECT inside customer_menu() finds it in the
    # identity map and does not overwrite it. An earlier version of this test
    # passed by accident for exactly that reason.
    db.expire_all()

    menu = {m.name: m for m in customer_menu(db, restaurant.id)}

    assert (menu["Gulab Jamun"].badge, menu["Gulab Jamun"].units_left) == ("ONLY_N_LEFT", 4)
    assert menu["Momos"].badge == "SELLING_FAST"
    assert menu["Kheer"].badge is None
    assert menu["Rasmalai"].badge == "SOLD_OUT" and menu["Rasmalai"].orderable is False
    assert menu["Plain Rice"].badge is None and menu["Plain Rice"].orderable is True
    assert plain.id == menu["Plain Rice"].id
