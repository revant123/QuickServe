"""The stock / consumed / cycle design."""

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import OutOfStock
from app.modules.menu import repository as menu_repo
from app.modules.menu.schema import AvailabilityUpdate
from app.modules.menu.service import restock, set_availability
from app.modules.orders.service import place_order
from tests.helpers import order_payload


def test_order_increases_consumed_and_leaves_stock_alone(db, restaurant, customer, make_item):
    item = make_item(stock=10)
    place_order(db, order_payload(restaurant, (item, 3)), customer)
    db.refresh(item)
    assert (item.stock, item.consumed, item.available) == (10, 3, 7)


def test_cannot_order_more_than_available(db, restaurant, customer, make_item):
    item = make_item(stock=2)
    with pytest.raises(OutOfStock, match="Only 2 left"):
        place_order(db, order_payload(restaurant, (item, 3)), customer)
    db.refresh(item)
    assert item.consumed == 0


def test_multi_item_order_is_all_or_nothing(db, restaurant, customer, make_item):
    naan = make_item("Butter Naan", "40.00", stock=5)
    dal = make_item("Dal Makhani", "220.00", stock=1)
    with pytest.raises(OutOfStock):
        place_order(db, order_payload(restaurant, (naan, 2), (dal, 2)), customer)
    db.refresh(naan)
    # naan's reservation ran first and succeeded, but the rollback undid it.
    assert naan.consumed == 0


def test_sold_out_time_is_recorded_once(db, restaurant, customer, make_item):
    item = make_item(stock=2)
    place_order(db, order_payload(restaurant, (item, 1)), customer)
    db.refresh(item)
    assert item.sold_out_at is None
    place_order(db, order_payload(restaurant, (item, 1)), customer)
    db.refresh(item)
    assert item.sold_out_at is not None and item.available == 0


def test_restock_archives_the_cycle_then_resets_consumed(db, restaurant, customer, make_item, owner):
    item = make_item(stock=10)
    place_order(db, order_payload(restaurant, (item, 7)), customer)

    closed, item = restock(db, item.id, quantity=12, carry_over_leftover=False, user=owner)

    assert (closed.cycle_no, closed.units_stocked, closed.units_consumed, closed.leftover) == (1, 10, 7, 3)
    assert closed.closed_at is not None and closed.leftover_carried is False
    assert (item.cycle_no, item.stock, item.consumed) == (2, 12, 0)
    cycles = menu_repo.list_cycles(db, item.id)
    assert [c.cycle_no for c in cycles] == [1, 2]
    assert cycles[1].closed_at is None and cycles[1].units_stocked == 12


def test_restock_can_carry_leftover_forward(db, restaurant, customer, make_item, owner):
    item = make_item("Packaged Lassi", "60.00", stock=10)
    place_order(db, order_payload(restaurant, (item, 7)), customer)
    _, item = restock(db, item.id, quantity=10, carry_over_leftover=True, user=owner)
    assert item.stock == 13
    assert menu_repo.list_cycles(db, item.id)[1].carried_in == 3


def test_untracked_item_still_counts_consumption(db, restaurant, customer, make_item):
    dosa = make_item("Plain Dosa", "90.00", stock=None, track_stock=False)
    place_order(db, order_payload(restaurant, (dosa, 4)), customer)
    place_order(db, order_payload(restaurant, (dosa, 40)), customer)
    db.refresh(dosa)
    assert dosa.stock is None and dosa.consumed == 44


def test_switched_off_item_and_timer(db, restaurant, customer, make_item, owner):
    item = make_item(stock=10)
    now = menu_repo.db_now(db)

    set_availability(
        db, item.id, AvailabilityUpdate(is_available=False, unavailable_until=now + timedelta(hours=1)), owner
    )
    with pytest.raises(OutOfStock, match="unavailable"):
        place_order(db, order_payload(restaurant, (item, 1)), customer)

    # A timer that has already passed: the item is back on by itself.
    set_availability(
        db, item.id, AvailabilityUpdate(is_available=False, unavailable_until=now - timedelta(minutes=1)), owner
    )
    place_order(db, order_payload(restaurant, (item, 1)), customer)

    set_availability(db, item.id, AvailabilityUpdate(is_available=False), owner)
    with pytest.raises(OutOfStock, match="unavailable"):
        place_order(db, order_payload(restaurant, (item, 1)), customer)


def test_database_refuses_oversell_even_if_code_is_wrong(db, make_item):
    """Defence in depth: bypass the service and write a bad value directly."""
    item = make_item(stock=5)
    with pytest.raises(IntegrityError, match="ck_menu_items_stock_consistent"):
        db.execute(text("UPDATE menu_items SET consumed = 6 WHERE id = :id"), {"id": item.id})
        db.commit()
    db.rollback()


def test_only_one_open_cycle_per_item(db, make_item):
    item = make_item(stock=5)
    with pytest.raises(IntegrityError, match="uq_inventory_cycles_one_open"):
        db.execute(
            text(
                "INSERT INTO inventory_cycles (id, menu_item_id, cycle_no, started_at, carried_in, units_returned, units_wasted)"
                " VALUES (gen_random_uuid(), :id, 99, now(), 0, 0, 0)"
            ),
            {"id": item.id},
        )
        db.commit()
    db.rollback()
