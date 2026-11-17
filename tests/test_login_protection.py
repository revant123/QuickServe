"""Login rate limiting and logout (token revocation), with real Redis."""

import pytest

from app.core.config import get_settings
from app.core.redis import get_redis, make_redis
from tests.conftest import TEST_PASSWORD


def login(client, email, password=TEST_PASSWORD):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


@pytest.fixture
def dead_redis():
    """Our production client settings, pointed at a port where nothing listens."""
    return make_redis("redis://localhost:1/15")


# ---------------------------------------------------------------- rate limiting


def test_sixth_wrong_password_is_blocked_even_with_the_right_password(client, customer):
    for _ in range(5):
        assert login(client, customer.email, "wrong-guess-1").status_code == 401
    blocked = login(client, customer.email, TEST_PASSWORD)  # correct, but too late
    assert blocked.status_code == 429
    retry_after = int(blocked.headers["Retry-After"])
    assert 0 < retry_after <= get_settings().login_failure_window_seconds


def test_success_resets_the_counter(client, customer):
    for _ in range(4):
        login(client, customer.email, "wrong-guess-1")
    assert login(client, customer.email).status_code == 200
    for _ in range(4):
        assert login(client, customer.email, "wrong-guess-1").status_code == 401  # not 429: counter was reset


def test_locking_one_account_does_not_lock_others(client, customer, owner):
    for _ in range(5):
        login(client, customer.email, "wrong-guess-1")
    assert login(client, customer.email).status_code == 429
    assert login(client, owner.email).status_code == 200


def test_one_ip_guessing_across_many_accounts_is_blocked(client, monkeypatch):
    """Password spraying: one common password tried against many accounts."""
    monkeypatch.setattr(get_settings(), "login_max_failures_per_ip", 3)
    for i in range(3):
        assert login(client, f"victim{i}@example.com", "Password123").status_code == 401
    assert login(client, "victim99@example.com", "Password123").status_code == 429


def test_counter_lives_in_redis_with_an_expiry(client, customer):
    login(client, customer.email, "wrong-guess-1")
    key = f"login:fail:email:{customer.email}"
    assert get_redis().get(key) == "1"
    assert 0 < get_redis().ttl(key) <= get_settings().login_failure_window_seconds


def test_login_still_works_when_redis_is_down(client, customer, monkeypatch, dead_redis):
    """Fail open: a Redis outage pauses the protection, it doesn't lock everyone out."""
    monkeypatch.setattr("app.modules.auth.rate_limit.get_redis", lambda: dead_redis)
    assert login(client, customer.email).status_code == 200


# ---------------------------------------------------------------- logout


def test_logout_kills_this_token_only(client, customer):
    token_a = login(client, customer.email).json()["access_token"]
    token_b = login(client, customer.email).json()["access_token"]  # e.g. a second phone
    a = {"Authorization": f"Bearer {token_a}"}
    b = {"Authorization": f"Bearer {token_b}"}

    assert client.post("/api/v1/auth/logout", headers=a).status_code == 204
    after = client.get("/api/v1/users/me", headers=a)
    assert after.status_code == 401 and "logged out" in after.json()["detail"]
    assert client.get("/api/v1/users/me", headers=b).status_code == 200


def test_revocation_entry_expires_with_the_token(client, customer):
    token = login(client, customer.email).json()["access_token"]
    client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    keys = list(get_redis().scan_iter("auth:revoked:*"))
    assert len(keys) == 1
    assert 0 < get_redis().ttl(keys[0]) <= get_settings().access_token_expire_minutes * 60


def test_logout_refuses_to_pretend_when_redis_is_down(client, customer, monkeypatch, dead_redis):
    token = login(client, customer.email).json()["access_token"]
    monkeypatch.setattr("app.modules.auth.revocation.get_redis", lambda: dead_redis)
    r = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503
