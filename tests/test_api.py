"""End to end through HTTP: four different people, each logged in, doing their part."""

from tests.conftest import TEST_PASSWORD


def _login(client, email, password=TEST_PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_order_journey(client, rider, admin):
    # Sign-ups
    client.post(
        "/api/v1/users",
        json={"name": "Owner", "email": "owner@dhaba.in", "password": "secret-pass", "role": "RESTAURANT_OWNER"},
    )
    cust = client.post(
        "/api/v1/users", json={"name": "Arjun", "email": "Arjun@Example.com", "password": "secret-pass"}
    ).json()
    assert "password_hash" not in cust and cust["email"] == "arjun@example.com"
    dup = client.post("/api/v1/users", json={"name": "X", "email": "arjun@example.com", "password": "secret-pass"})
    assert dup.status_code == 409

    owner_h = _login(client, "owner@dhaba.in", "secret-pass")
    cust_h = _login(client, "arjun@example.com", "secret-pass")
    rider_h = _login(client, rider.email)

    # Owner sets up the restaurant and a dish
    rest = client.post(
        "/api/v1/restaurants",
        json={
            "name": "Pal Dhaba",
            "address": "Sector 28",
            "packaging_charge": "15.00",
            "latitude": "30.719300",
            "longitude": "76.803000",
        },
        headers=owner_h,
    ).json()
    item = client.post(
        f"/api/v1/restaurants/{rest['id']}/menu",
        json={"name": "Dal Makhani", "price": "240.00", "stock": 3},
        headers=owner_h,
    ).json()
    assert item["available"] == 3

    # Customer orders (no customer_id anywhere: it comes from the token)
    body = {
        "restaurant_id": rest["id"],
        "delivery_address": "House 5, Sector 15",
        "delivery_location": {"lat": 30.7333, "lng": 76.7794},
        "items": [{"menu_item_id": item["id"], "quantity": 2}],
    }
    assert client.post("/api/v1/orders", json=body).status_code == 401  # not logged in
    order = client.post("/api/v1/orders", json=body, headers=cust_h)
    assert order.status_code == 201
    order = order.json()
    assert order["customer_id"] == cust["id"]

    too_many = client.post("/api/v1/orders", json=body, headers=cust_h)
    assert too_many.status_code == 409 and "Only 1 left" in too_many.json()["detail"]

    # Customer pays; a retry doesn't charge twice
    pay_h = {**cust_h, "Idempotency-Key": "pay-attempt-0001"}
    first = client.post(f"/api/v1/orders/{order['id']}/payments", headers=pay_h)
    retry = client.post(f"/api/v1/orders/{order['id']}/payments", headers=pay_h)
    assert first.status_code == 201 and retry.status_code == 200
    assert retry.headers["Idempotent-Replayed"] == "true" and first.json()["id"] == retry.json()["id"]

    # Only the owner can accept; the customer can't
    status_url = f"/api/v1/orders/{order['id']}/status"
    assert client.patch(status_url, json={"status": "ACCEPTED"}, headers=cust_h).status_code == 403
    assert client.patch(status_url, json={"status": "ACCEPTED"}, headers=owner_h).json()["status"] == "ACCEPTED"
    assert client.patch(status_url, json={"status": "DELIVERED"}, headers=owner_h).status_code == 403

    # Phase 14: the rider sees the order in the pool, without the address, and
    # sees the order itself only after claiming it
    assert client.get(f"/api/v1/orders/{order['id']}", headers=rider_h).status_code == 404
    pool = client.get("/api/v1/rider/pool", headers=rider_h).json()
    assert [p["id"] for p in pool] == [order["id"]] and "delivery_address" not in pool[0]
    for s in ("PREPARING", "READY"):
        client.patch(status_url, json={"status": s}, headers=owner_h)
    assert client.post(f"/api/v1/orders/{order['id']}/claim", headers=rider_h).status_code == 200
    seen_by_rider = client.get(f"/api/v1/orders/{order['id']}", headers=rider_h).json()
    assert seen_by_rider["delivery_code"] is None and seen_by_rider["rider_name"] == rider.name
    code = client.get(f"/api/v1/orders/{order['id']}", headers=cust_h).json()["delivery_code"]
    assert client.patch(status_url, json={"status": "OUT_FOR_DELIVERY"}, headers=rider_h).status_code == 200
    assert client.patch(status_url, json={"status": "DELIVERED"}, headers=rider_h).status_code == 422  # no code
    delivered = client.patch(status_url, json={"status": "DELIVERED", "delivery_code": code}, headers=rider_h)
    assert delivered.status_code == 200

    timeline = client.get(f"/api/v1/orders/{order['id']}/timeline", headers=cust_h).json()
    assert [(e["to_status"], e["actor"]) for e in timeline] == [
        ("PLACED", "customer"),
        ("PAID", "system"),
        ("ACCEPTED", "restaurant"),
        ("PREPARING", "restaurant"),
        ("READY", "restaurant"),
        ("OUT_FOR_DELIVERY", "rider"),
        ("DELIVERED", "rider"),
    ]

    # Public menu, owner-only analytics
    menu = client.get(f"/api/v1/restaurants/{rest['id']}/menu").json()
    assert menu[0]["badge"] == "ONLY_N_LEFT" and menu[0]["units_left"] == 1

    restocked = client.post(f"/api/v1/menu/{item['id']}/restock", json={"quantity": 10}, headers=owner_h).json()
    assert restocked["closed_cycle"]["units_consumed"] == 2 and restocked["item"]["consumed"] == 0

    assert client.get(f"/api/v1/restaurants/{rest['id']}/best-sellers", headers=cust_h).status_code == 403
    best = client.get(f"/api/v1/restaurants/{rest['id']}/best-sellers?days=7", headers=owner_h)
    assert best.status_code == 200 and best.json()[0]["units_sold"] == 2

    # Admin sees everything
    admin_h = _login(client, admin.email)
    assert client.get(f"/api/v1/orders/{order['id']}", headers=admin_h).status_code == 200


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "alive"}
    assert client.get("/health/ready").json()["database"] == "ok"


def test_validation_errors_are_422(client, owner, restaurant):
    h = _login(client, owner.email)
    r = client.post(f"/api/v1/restaurants/{restaurant.id}/menu", json={"name": "X", "price": "-5"}, headers=h)
    assert r.status_code == 422
