"""Phase 13: the two endpoints the customer app needed, and the API contract."""

import uuid

from sqlalchemy import text, update

from app.modules.orders.model import Order
from app.modules.orders.service import list_my_orders, place_order
from app.modules.users.model import Role
from tests.conftest import TEST_PASSWORD
from tests.helpers import order_payload
from tests.test_orm_behaviour import count_queries


def login(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_my_orders_newest_first_with_restaurant_name_and_item_count(db, restaurant, make_item, customer, make_user):
    naan, dal = make_item("Butter Naan", "50.00", stock=50), make_item("Dal Makhani", "240.00", stock=50)
    first = place_order(db, order_payload(restaurant, (naan, 2)), customer)
    second = place_order(db, order_payload(restaurant, (naan, 1), (dal, 3)), customer)
    other = make_user(Role.CUSTOMER)
    place_order(db, order_payload(restaurant, (dal, 1)), other)
    # Same transaction start, so make the order unambiguous.
    db.execute(
        update(Order).where(Order.id == first.id).values(created_at=Order.created_at - text("interval '1 minute'"))
    )
    db.commit()

    rows = list_my_orders(db, customer, limit=20, offset=0)
    assert [r.id for r in rows] == [second.id, first.id]  # only mine, newest first
    assert rows[0].restaurant_name == restaurant.name
    assert rows[0].item_count == 4 and rows[1].item_count == 2
    assert rows[0].grand_total == second.grand_total


def test_my_orders_is_one_query_however_many_orders(db, restaurant, make_item, customer):
    item = make_item("Butter Naan", "50.00", stock=100)
    for _ in range(8):
        place_order(db, order_payload(restaurant, (item, 1)), customer)
    db.expire_all()
    db.refresh(customer)  # reload the user now, so the count below is only the list itself
    with count_queries() as queries:
        rows = list_my_orders(db, customer, limit=20, offset=0)
    assert len(rows) == 8
    # Loading orders, then each one's restaurant and items, would be 1 + 2 x 8 = 17.
    assert len(queries) == 1, queries


def test_my_orders_http(client, restaurant, make_item, customer, owner):
    item = make_item("Butter Naan", "50.00", stock=10)
    h = login(client, customer.email)
    client.post("/api/v1/orders", json=order_payload(restaurant, (item, 1)).model_dump(mode="json"), headers=h)
    r = client.get("/api/v1/orders", headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1 and r.json()[0]["restaurant_name"] == restaurant.name
    assert client.get("/api/v1/orders").status_code == 401
    assert client.get("/api/v1/orders", headers=login(client, owner.email)).status_code == 403  # customers only
    assert client.get("/api/v1/orders?limit=51", headers=h).status_code == 422  # every list is bounded


def test_restaurant_detail_is_public(client, restaurant):
    r = client.get(f"/api/v1/restaurants/{restaurant.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == restaurant.name and "cuisines" in body and "rating" in body
    assert client.get(f"/api/v1/restaurants/{uuid.uuid4()}").status_code == 404
