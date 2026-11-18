"""Prometheus metrics: the right numbers, cheap labels, and nothing counted twice."""

import socket
import time

import pytest
from prometheus_client import REGISTRY

from app import worker
from app.core.exceptions import InvalidTransition, OutOfStock
from app.core.metrics import WORKER_LAST_RUN, after_commit, route_label, start_metrics_server, worker_heartbeat
from app.modules.orders import service as orders
from tests.conftest import TEST_PASSWORD
from tests.helpers import order_payload


def value(name: str, **labels) -> float:
    """Current value of a metric sample (0 if it hasn't been created yet)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def login(client, email, password=TEST_PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- Counting only what was committed ----------


def test_after_commit_runs_on_commit_and_is_dropped_on_rollback(db):
    from sqlalchemy import text

    calls = []
    db.execute(text("SELECT 1"))  # inside a transaction, as in real code
    after_commit(db, lambda: calls.append("committed"))
    db.rollback()
    db.commit()  # an empty commit later must NOT run the dropped increment
    assert calls == []

    after_commit(db, lambda: calls.append("committed"))
    db.commit()
    assert calls == ["committed"]


def test_order_counters_move_only_for_committed_orders(db, restaurant, customer, make_item):
    item = make_item(stock=1)
    placed = value("quickserve_orders_placed_total")
    value_count = value("quickserve_order_value_rupees_count")

    orders.place_order(db, order_payload(restaurant, (item, 1)), customer)
    assert value("quickserve_orders_placed_total") == placed + 1
    assert value("quickserve_order_value_rupees_count") == value_count + 1

    # Out of stock: the transaction rolls back, so nothing is counted.
    with pytest.raises(OutOfStock):
        orders.place_order(db, order_payload(restaurant, (item, 1)), customer)
    assert value("quickserve_orders_placed_total") == placed + 1


def test_status_changes_are_labelled_by_status_and_actor(db, restaurant, customer, make_item):
    item = make_item(stock=5)
    order = orders.place_order(db, order_payload(restaurant, (item, 1)), customer)
    before = value("quickserve_order_status_changes_total", to_status="CANCELLED", actor="customer")
    orders.cancel(db, order.id, customer, "changed my mind")
    assert value("quickserve_order_status_changes_total", to_status="CANCELLED", actor="customer") == before + 1

    # A refused change (already cancelled) rolls back and is not counted.
    with pytest.raises(InvalidTransition):
        orders.cancel(db, order.id, customer, "again")
    assert value("quickserve_order_status_changes_total", to_status="CANCELLED", actor="customer") == before + 1


# ---------- Through HTTP ----------


def test_payments_counted_once_even_when_retried(client, restaurant, customer, make_item):
    item = make_item(stock=5)
    h = login(client, customer.email)
    body = {
        "restaurant_id": str(restaurant.id),
        "delivery_address": "House 1",
        "delivery_location": {"lat": 30.7333, "lng": 76.7794},
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
    }
    order = client.post("/api/v1/orders", json=body, headers=h).json()
    before = value("quickserve_payments_total", outcome="success")

    pay = {**h, "Idempotency-Key": "metrics-pay-0001"}
    assert client.post(f"/api/v1/orders/{order['id']}/payments", headers=pay).status_code in (200, 201)
    client.post(f"/api/v1/orders/{order['id']}/payments", headers=pay)  # the app retries
    assert value("quickserve_payments_total", outcome="success") == before + 1


def test_http_metrics_use_the_route_template_not_the_real_path(client, restaurant, make_item):
    make_item()
    route = "/api/v1/restaurants/{restaurant_id}/menu"
    before = value("quickserve_http_requests_total", method="GET", route=route, status="200")
    client.get(f"/api/v1/restaurants/{restaurant.id}/menu")
    assert value("quickserve_http_requests_total", method="GET", route=route, status="200") == before + 1
    assert value("quickserve_http_request_duration_seconds_count", method="GET", route=route) >= 1

    # No series may contain a real ID: that would create one time series per restaurant.
    names = {s.labels.get("route", "") for m in REGISTRY.collect() for s in m.samples}
    assert not any(str(restaurant.id) in n for n in names)


def test_route_label_rebuilds_the_full_template():
    class Route:
        path = "/orders/{order_id}"

    assert route_label({"route": Route(), "path": "/api/v1/orders/9b2c"}) == "/api/v1/orders/{order_id}"
    assert route_label({"path": "/wp-admin/login.php"}) == "unmatched"


def test_unknown_paths_share_one_label(client):
    before = value("quickserve_http_requests_total", method="GET", route="unmatched", status="404")
    client.get("/no/such/page/12345")
    client.get("/another/random/path")
    assert value("quickserve_http_requests_total", method="GET", route="unmatched", status="404") == before + 2


def test_metrics_are_not_served_on_the_public_api_port(client):
    assert client.get("/metrics").status_code == 404


def test_menu_cache_results_are_counted(client, restaurant, make_item):
    make_item()
    miss, hit = (
        value("quickserve_menu_cache_requests_total", result="miss"),
        value("quickserve_menu_cache_requests_total", result="hit"),
    )
    client.get(f"/api/v1/restaurants/{restaurant.id}/menu")
    client.get(f"/api/v1/restaurants/{restaurant.id}/menu")
    assert value("quickserve_menu_cache_requests_total", result="miss") == miss + 1
    assert value("quickserve_menu_cache_requests_total", result="hit") == hit + 1


def test_logins_counted_by_outcome(client, customer):
    ok, bad, blocked = (value("quickserve_logins_total", outcome=o) for o in ("success", "failed", "blocked"))
    login(client, customer.email)
    for _ in range(5):
        client.post("/api/v1/auth/login", data={"username": customer.email, "password": "wrong"})
    r = client.post("/api/v1/auth/login", data={"username": customer.email, "password": "wrong"})
    assert r.status_code == 429
    assert value("quickserve_logins_total", outcome="success") == ok + 1
    assert value("quickserve_logins_total", outcome="failed") == bad + 5
    assert value("quickserve_logins_total", outcome="blocked") == blocked + 1


# ---------- Worker heartbeat (its Kubernetes liveness probe) ----------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def metrics_port():
    port = _free_port()
    assert start_metrics_server(port, "test")
    return port


def test_healthcheck_passes_right_after_a_pass(metrics_port):
    worker_heartbeat(success=True)
    assert worker.healthcheck(metrics_port, max_age_seconds=60)


def test_healthcheck_fails_when_the_loop_is_stuck(metrics_port):
    WORKER_LAST_RUN.set(time.time() - 600)  # last pass 10 minutes ago
    assert not worker.healthcheck(metrics_port, max_age_seconds=120)


def test_a_failing_job_still_counts_as_alive(metrics_port):
    # Database down: the pass fails but the loop is running. Restarting the pod
    # wouldn't fix the database, so liveness must still pass.
    worker_heartbeat(success=False)
    assert worker.healthcheck(metrics_port, max_age_seconds=60)


def test_healthcheck_fails_when_no_worker_is_running():
    assert not worker.healthcheck(_free_port(), max_age_seconds=60)


def test_worker_counts_timed_out_orders(db, restaurant, customer, make_item):
    from sqlalchemy import text

    item = make_item(stock=5)
    order = orders.place_order(db, order_payload(restaurant, (item, 1)), customer)
    db.execute(text("UPDATE orders SET pay_by = now() - interval '1 minute' WHERE id = :id"), {"id": order.id})
    db.commit()
    before = value("quickserve_worker_orders_timed_out_total", reason="payment_expired")
    worker.run_once()
    assert value("quickserve_worker_orders_timed_out_total", reason="payment_expired") == before + 1
