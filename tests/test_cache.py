"""The Redis menu cache: hits, invalidation, the staleness we accept, and life without Redis."""

import time

import pytest

from app.core.config import get_settings
from app.core.exceptions import OutOfStock
from app.core.redis import get_redis, make_redis
from app.modules.menu.schema import AvailabilityUpdate
from app.modules.menu.service import restock, set_availability
from app.modules.orders.service import place_order
from tests.helpers import order_payload


@pytest.fixture
def dead_redis():
    """Our production client settings, pointed at a port where nothing listens."""
    return make_redis("redis://localhost:1/15")


def menu(client, restaurant):
    r = client.get(f"/api/v1/restaurants/{restaurant.id}/menu")
    assert r.status_code == 200
    return r


def test_first_read_misses_second_read_hits(client, restaurant, make_item):
    make_item(stock=10)
    first, second = menu(client, restaurant), menu(client, restaurant)
    assert first.headers["X-Cache"] == "MISS" and second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()
    ttl = get_redis().ttl(f"menu:v1:{restaurant.id}")
    assert 0 < ttl <= get_settings().menu_cache_ttl_seconds


def test_owner_changes_clear_the_cache(client, db, restaurant, make_item, owner):
    item = make_item(stock=10)
    menu(client, restaurant)
    assert menu(client, restaurant).headers["X-Cache"] == "HIT"

    restock(db, item.id, 20, False, owner)
    assert menu(client, restaurant).headers["X-Cache"] == "MISS"

    set_availability(db, item.id, AvailabilityUpdate(is_available=False), owner)
    after = menu(client, restaurant)
    assert after.headers["X-Cache"] == "MISS" and after.json()[0]["orderable"] is False


def test_a_stale_menu_can_never_cause_an_oversell(client, db, restaurant, customer, make_item):
    """Orders don't clear the cache, so the menu may still say '2 left' for a few
    seconds after they're gone. The order path checks PostgreSQL, so nobody can buy them."""
    item = make_item(stock=2)
    assert menu(client, restaurant).json()[0]["units_left"] == 2
    place_order(db, order_payload(restaurant, (item, 2)), customer)

    stale = menu(client, restaurant)
    assert stale.headers["X-Cache"] == "HIT" and stale.json()[0]["units_left"] == 2  # accepted staleness
    with pytest.raises(OutOfStock):
        place_order(db, order_payload(restaurant, (item, 1)), customer)  # ...but no oversell


def test_menu_still_works_when_redis_is_down_and_stays_fast(client, restaurant, make_item, monkeypatch, dead_redis):
    make_item(stock=10)
    monkeypatch.setattr("app.modules.menu.cache.get_redis", lambda: dead_redis)
    started = time.perf_counter()
    r = menu(client, restaurant)
    elapsed = time.perf_counter() - started
    assert r.headers["X-Cache"] == "BYPASS" and len(r.json()) == 1
    assert elapsed < 1.0  # degraded means "no cache", not "every request hangs"


def test_readiness_reports_redis_down_but_stays_ready(client, monkeypatch, dead_redis):
    monkeypatch.setattr("app.core.redis.get_redis", lambda: dead_redis)
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok" and r.json()["redis"].startswith("down")
