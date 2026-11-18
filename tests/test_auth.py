"""Login, tokens, and who may do what. All through HTTP, the way a real client calls it."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import create_access_token
from tests.conftest import TEST_PASSWORD


def login(client, email, password=TEST_PASSWORD):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def auth(client, user) -> dict:
    token = login(client, user.email).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- logging in


def test_login_returns_a_token_that_identifies_you(client, customer):
    r = login(client, customer.email)
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["id"] == str(customer.id) and "password_hash" not in me.json()


def test_login_email_is_case_insensitive(client, customer):
    assert login(client, customer.email.upper()).status_code == 200


def test_wrong_password_and_unknown_email_look_identical(client, customer):
    wrong_password = login(client, customer.email, "not-the-password")
    no_such_user = login(client, "nobody@example.com", "whatever-123")
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json() == {"detail": "Incorrect email or password"}
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


def test_cannot_sign_up_as_admin(client):
    r = client.post(
        "/api/v1/users", json={"name": "Sneaky", "email": "sneaky@x.in", "password": "secret-pass", "role": "ADMIN"}
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- bad tokens


def test_no_token_is_401(client):
    assert client.get("/api/v1/users/me").status_code == 401


def test_expired_token_is_401(client, customer):
    s = get_settings()
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {
            "sub": str(customer.id),
            "type": "access",
            "jti": "test-token-id",
            "iat": past,
            "exp": past + timedelta(minutes=30),
        },
        s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
    )
    r = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_token_signed_with_another_key_is_401(client, customer):
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": str(customer.id),
            "type": "access",
            "jti": "test-token-id",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        "an-attacker-guessed-secret-that-is-long-enough",
        algorithm="HS256",
    )
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_unsigned_alg_none_token_is_401(client, customer):
    """The classic JWT attack: a token that says "no signature needed"."""
    now = datetime.now(UTC)
    unsigned = jwt.encode(
        {
            "sub": str(customer.id),
            "type": "access",
            "jti": "test-token-id",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        None,
        algorithm="none",
    )
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_editing_the_role_inside_a_token_breaks_it(client, customer):
    """Anyone can READ a token (it's only base64), so let's promote ourselves to ADMIN.
    The signature no longer matches the edited contents, so the server rejects it."""
    header, payload, signature = create_access_token(customer.id, "CUSTOMER").split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["role"] == "CUSTOMER" and claims["sub"] == str(customer.id)  # readable without any key
    claims["role"] = "ADMIN"
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    forged = f"{header}.{forged_payload}.{signature}"
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_token_of_a_deleted_user_is_401(client, db, customer):
    headers = auth(client, customer)
    db.delete(customer)
    db.commit()
    r = client.get("/api/v1/users/me", headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "Account no longer exists"


def test_token_for_random_user_id_is_401(client):
    token = create_access_token(uuid.uuid4(), "ADMIN")
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_dev_secret_is_refused_outside_local(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None)


# ---------------------------------------------------------------- permissions


def test_customer_cannot_create_a_restaurant(client, customer):
    r = client.post(
        "/api/v1/restaurants",
        json={"name": "X", "address": "Y", "latitude": "30.7", "longitude": "76.7"},
        headers=auth(client, customer),
    )
    assert r.status_code == 403


def test_owner_creates_restaurant_owned_by_themselves(client, owner):
    r = client.post(
        "/api/v1/restaurants",
        json={"name": "Mine", "address": "Sector 9", "latitude": "30.7", "longitude": "76.7"},
        headers=auth(client, owner),
    )
    assert r.status_code == 201 and r.json()["owner_id"] == str(owner.id)


def test_owner_cannot_touch_another_owners_menu(client, make_user, make_item, restaurant):
    from app.modules.users.model import Role

    item = make_item(stock=10)
    intruder = make_user(Role.RESTAURANT_OWNER)
    h = auth(client, intruder)
    assert client.post(f"/api/v1/menu/{item.id}/restock", json={"quantity": 1}, headers=h).status_code == 403
    assert client.get(f"/api/v1/restaurants/{restaurant.id}/best-sellers", headers=h).status_code == 403
    assert (
        client.post(
            f"/api/v1/restaurants/{restaurant.id}/menu", json={"name": "Fake", "price": "1", "stock": 1}, headers=h
        ).status_code
        == 403
    )


def test_admin_can_manage_any_restaurant(client, admin, make_item):
    item = make_item(stock=10)
    r = client.post(f"/api/v1/menu/{item.id}/restock", json={"quantity": 5}, headers=auth(client, admin))
    assert r.status_code == 200


def test_only_customers_place_orders(client, owner, make_item, restaurant):
    item = make_item(stock=10)
    body = {
        "restaurant_id": str(restaurant.id),
        "delivery_address": "House 1, Sector 1",
        "delivery_location": {"lat": 30.7333, "lng": 76.7794},
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
    }
    assert client.post("/api/v1/orders", json=body, headers=auth(client, owner)).status_code == 403


def test_only_admins_run_the_timeout_job(client, customer, owner, admin):
    for user in (customer, owner):
        assert client.post("/api/v1/admin/jobs/order-timeouts", headers=auth(client, user)).status_code == 403
    assert client.post("/api/v1/admin/jobs/order-timeouts", headers=auth(client, admin)).status_code == 200


def test_browsing_needs_no_login(client, restaurant, make_item):
    make_item(stock=3)
    assert client.get("/api/v1/restaurants").status_code == 200
    assert client.get(f"/api/v1/restaurants/{restaurant.id}/menu").status_code == 200
