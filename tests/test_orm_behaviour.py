"""Small experiments that show what the ORM does on the wire.

Each test counts the SQL statements SQLAlchemy actually sends, so the ORM's
behaviour is something you can check rather than take on trust.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import selectinload

from app.database.session import engine
from app.modules.restaurants.model import Restaurant


@contextmanager
def count_queries():
    statements: list[str] = []

    def before(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)


@pytest.fixture
def three_restaurants(db, make_user, make_item, restaurant):
    from decimal import Decimal

    from app.modules.menu.schema import MenuItemCreate
    from app.modules.menu.service import create_menu_item

    owner = make_user()
    others = [
        Restaurant(owner_id=owner.id, name=f"R{i}", address="Chandigarh", packaging_charge=Decimal("0"))
        for i in range(2)
    ]
    db.add_all(others)
    db.commit()
    for r in [restaurant, *others]:
        for n in range(3):
            create_menu_item(db, r.id, MenuItemCreate(name=f"Dish {n}", price=Decimal("100"), stock=5))
    db.expunge_all()


def test_lazy_loading_is_switched_off_to_prevent_n_plus_1(db, three_restaurants):
    """With default lazy loading, `for r in restaurants: r.menu_items` silently
    runs 1 query for the list + 1 per restaurant (the N+1 problem). We set
    lazy="raise", so that mistake fails loudly in development instead."""
    restaurants = db.execute(select(Restaurant)).scalars().all()
    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = restaurants[0].menu_items


def test_selectinload_fetches_everything_in_two_queries(db, three_restaurants):
    with count_queries() as sql:
        restaurants = db.execute(select(Restaurant).options(selectinload(Restaurant.menu_items))).scalars().all()
        total_items = sum(len(r.menu_items) for r in restaurants)
    assert total_items == 9
    assert len(sql) == 2  # SELECT restaurants; SELECT menu_items WHERE restaurant_id IN (...)
    assert "IN (" in sql[1]


def test_a_plain_select_does_not_refresh_an_object_you_already_hold(db, restaurant):
    """The identity map's catch. If you hold an object and the row changes
    underneath (another request, a raw SQL script), selecting it again gives you
    the same object WITH THE OLD VALUES. populate_existing (or refresh/expire)
    is how you ask for the database's current truth. Our row-locking queries
    always use populate_existing for this reason."""
    from sqlalchemy import text

    held = db.get(Restaurant, restaurant.id)
    db.execute(text("UPDATE restaurants SET name = 'Renamed' WHERE id = :id"), {"id": restaurant.id})
    db.commit()

    again = db.execute(select(Restaurant).where(Restaurant.id == restaurant.id)).scalar_one()
    assert again is held and again.name == "Sharma Dhaba"  # stale

    fresh = db.execute(
        select(Restaurant).where(Restaurant.id == restaurant.id).execution_options(populate_existing=True)
    ).scalar_one()
    assert fresh.name == "Renamed"


def test_identity_map_returns_the_same_object(db, restaurant):
    """Within one session, the same row is always the same Python object, and a
    repeated primary-key lookup is answered from memory without SQL."""
    db.expunge_all()
    with count_queries() as sql:
        a = db.get(Restaurant, restaurant.id)
        b = db.get(Restaurant, restaurant.id)
    assert a is b
    assert len(sql) == 1
