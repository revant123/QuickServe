"""End to end through HTTP, the way the app and Swagger UI use it."""


def test_full_order_journey(client):
    owner = client.post(
        "/api/v1/users",
        json={"name": "Owner", "email": "owner@dhaba.in", "password": "secret-pass", "role": "RESTAURANT_OWNER"},
    ).json()
    cust = client.post(
        "/api/v1/users", json={"name": "Arjun", "email": "Arjun@Example.com", "password": "secret-pass"}
    ).json()
    assert "password_hash" not in cust and cust["email"] == "arjun@example.com"
    assert (
        client.post(
            "/api/v1/users", json={"name": "X", "email": "arjun@example.com", "password": "secret-pass"}
        ).status_code
        == 409
    )

    rest = client.post(
        "/api/v1/restaurants",
        json={"owner_id": owner["id"], "name": "Pal Dhaba", "address": "Sector 28", "packaging_charge": "15.00"},
    ).json()
    item = client.post(
        f"/api/v1/restaurants/{rest['id']}/menu", json={"name": "Dal Makhani", "price": "240.00", "stock": 3}
    ).json()
    assert item["available"] == 3

    order = client.post(
        "/api/v1/orders",
        json={
            "customer_id": cust["id"],
            "restaurant_id": rest["id"],
            "delivery_address": "House 5, Sector 15",
            "items": [{"menu_item_id": item["id"], "quantity": 2}],
        },
    )
    assert order.status_code == 201
    order = order.json()

    too_many = client.post(
        "/api/v1/orders",
        json={
            "customer_id": cust["id"],
            "restaurant_id": rest["id"],
            "delivery_address": "House 5, Sector 15",
            "items": [{"menu_item_id": item["id"], "quantity": 2}],
        },
    )
    assert too_many.status_code == 409 and "Only 1 left" in too_many.json()["detail"]

    headers = {"Idempotency-Key": "pay-attempt-0001"}
    first = client.post(f"/api/v1/orders/{order['id']}/payments", headers=headers)
    retry = client.post(f"/api/v1/orders/{order['id']}/payments", headers=headers)
    assert first.status_code == 201 and retry.status_code == 200
    assert retry.headers["Idempotent-Replayed"] == "true" and first.json()["id"] == retry.json()["id"]

    accepted = client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "ACCEPTED", "actor": "restaurant"})
    assert accepted.json()["status"] == "ACCEPTED"
    bad = client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "DELIVERED", "actor": "rider"})
    assert bad.status_code == 409

    timeline = client.get(f"/api/v1/orders/{order['id']}/timeline").json()
    assert [e["to_status"] for e in timeline] == ["PLACED", "PAID", "ACCEPTED"]

    menu = client.get(f"/api/v1/restaurants/{rest['id']}/menu").json()
    assert menu[0]["badge"] == "ONLY_N_LEFT" and menu[0]["units_left"] == 1

    restocked = client.post(f"/api/v1/menu/{item['id']}/restock", json={"quantity": 10}).json()
    assert restocked["closed_cycle"]["units_consumed"] == 2 and restocked["item"]["consumed"] == 0

    best = client.get(f"/api/v1/restaurants/{rest['id']}/best-sellers?days=7")
    assert best.status_code == 200 and best.json()[0]["units_sold"] == 2


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "alive"}
    assert client.get("/health/ready").json()["database"] == "ok"


def test_validation_errors_are_422(client):
    r = client.post("/api/v1/restaurants/00000000-0000-0000-0000-000000000000/menu", json={"name": "X", "price": "-5"})
    assert r.status_code == 422
