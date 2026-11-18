"""Smoke test for QuickServe running in Kubernetes. Standard library only.

It runs INSIDE the cluster, so it reaches the API through its Service name
("http://api"), exactly like another service would. infra/k8s/smoke.sh starts
it in a pod of its own (label app.kubernetes.io/name=smoke-test), which the
network policies (Phase 10) allow to reach exactly what the checks need:

    infra/k8s/smoke.sh check
    infra/k8s/smoke.sh watch 60

check       health, login as the demo customer, call /users/me, then place and pay
            for an order and wait for the notifier to deliver "Payment received"
            (needs the seed data)
watch N     hit /health/ready 5 times a second for N seconds and count failures.
            Run it during `kubectl rollout restart deployment/api`: 0 failures
            means the rolling update caused no downtime.
monitoring  Prometheus scrapes every API and worker pod, has seen the login
            from `check`, fires no alerts; Grafana has loaded the dashboard;
            the Watchdog alert went Prometheus -> Alertmanager -> email (Mailpit).
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

BASE = "http://api"


def get(path, token=None, timeout=3):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read() or b"null")


def post(path, body, token, headers=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body is not None else b"", method="POST"
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read() or b"null")


def order_and_notification(token):
    """The outbox end to end: order -> payment -> event -> notifier -> notification."""
    _, restaurants = get("/api/v1/restaurants")
    restaurants = restaurants["items"] if isinstance(restaurants, dict) else restaurants
    for r in restaurants:
        _, menu = get(f"/api/v1/restaurants/{r['id']}/menu")
        dish = next((m for m in menu if m.get("available") is None or m["available"] > 0), None)
        if dish:
            break
    else:
        raise AssertionError("no dish available to order")
    body = {
        "restaurant_id": r["id"],
        "delivery_address": "Smoke test",
        # A point right next to the restaurant (Phase 11: delivery is priced by distance).
        "delivery_location": {"lat": float(r["latitude"]) + 0.002, "lng": float(r["longitude"])},
        "items": [{"menu_item_id": dish["id"], "quantity": 1}],
    }
    # Checkout like an app: quote, show it, then order at exactly that price.
    _, bill = post("/api/v1/orders/quote", body, token)
    assert sum(Decimal(line["amount"]) for line in bill["lines"]) == Decimal(bill["grand_total"]), bill
    _, order = post("/api/v1/orders", {**body, "expected_total": bill["grand_total"]}, token)
    assert order["grand_total"] == bill["grand_total"], (order, bill)
    status, _ = post(f"/api/v1/orders/{order['id']}/payments", None, token, {"Idempotency-Key": f"smoke-{order['id']}"})
    assert status in (200, 201), status
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        _, notes = get("/api/v1/notifications", token)
        if any(n["order_id"] == order["id"] and n["title"] == "Payment received" for n in notes):
            print("notification delivered: Payment received, for order", order["id"])
            return
        time.sleep(1)
    raise AssertionError("the notifier didn't deliver 'Payment received' within 30 s")


def check():
    status, body = get("/health/ready")
    assert status == 200 and body["database"] == "ok", body
    print("ready:", body)

    form = urllib.parse.urlencode({"username": "customer@quickserve.dev", "password": "customer-pass-123"}).encode()
    with urllib.request.urlopen(BASE + "/api/v1/auth/login", data=form, timeout=5) as resp:
        token = json.loads(resp.read())["access_token"]

    status, me = get("/api/v1/users/me", token)
    assert status == 200 and me["email"] == "customer@quickserve.dev", me
    print("logged in as:", me["email"], me["role"])

    order_and_notification(token)


def prom(query):
    url = "http://prometheus:9090/api/v1/query?" + urllib.parse.urlencode({"query": query})
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())["data"]["result"]


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def watchdog_in_alertmanager():
    alerts = get_json("http://alertmanager:9093/api/v2/alerts")
    return any(a["labels"].get("alertname") == "Watchdog" for a in alerts)


def watchdog_emailed():
    inbox = get_json("http://mailpit:8025/api/v1/messages")
    return any("Watchdog" in (m.get("Subject") or "") for m in inbox.get("messages") or [])


def monitoring(timeout=120):
    deadline = time.monotonic() + timeout
    checks = {
        "every API, worker and notifier pod is scraped": 'count(up{job="quickserve"} == 1) >= 4',
        "the notifier delivered the smoke test's events": 'sum(quickserve_outbox_events_processed_total{outcome="published"}) >= 2',
        "the login from `check` was counted": 'sum(quickserve_logins_total{outcome="success"}) >= 1',
        "the worker heartbeat is fresh": "time() - max(quickserve_worker_last_run_timestamp_seconds) < 120",
        "the recording rules run": "quickserve:infra_cost_usd:per_hour",
        "the rightsizing rules see every app's CPU and memory": "count(quickserve:app_memory_bytes) >= 3",
        "Prometheus sends alerts to Alertmanager": "prometheus_notifications_alertmanagers_discovered >= 1",
        # The end of the chain: two HTTP checks, not PromQL.
        "alertmanager: the Watchdog arrived": watchdog_in_alertmanager,
        "mailpit: the Watchdog email arrived": watchdog_emailed,
    }
    pending = dict(checks)
    while pending and time.monotonic() < deadline:
        for name, query in list(pending.items()):
            try:
                if query() if callable(query) else prom(query):
                    print(name if callable(query) else f"prometheus: {name}")
                    del pending[name]
            except (urllib.error.URLError, OSError):
                pass  # Prometheus still starting
        if pending:
            time.sleep(5)
    assert not pending, f"not seen within {timeout}s: {list(pending)}"

    # The Watchdog always fires on purpose; anything else firing is a problem.
    firing = prom('ALERTS{alertstate="firing", alertname!="Watchdog"}')
    assert not firing, f"alerts firing: {firing}"
    print("prometheus: no alerts firing (apart from the Watchdog)")

    with urllib.request.urlopen("http://grafana:3000/api/dashboards/uid/quickserve-overview", timeout=5) as resp:
        dash = json.loads(resp.read())["dashboard"]
    print("grafana: dashboard loaded:", dash["title"], f"({len(dash['panels'])} panels)")


def watch(seconds):
    ok = failed = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            status, _ = get("/health/ready", timeout=2)
            ok += status == 200
            failed += status != 200
        except (urllib.error.URLError, OSError, ValueError):
            failed += 1
        time.sleep(0.2)
    print(json.dumps({"ok": ok, "failed": failed}))
    return failed


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "check":
        check()
    elif mode == "watch":
        sys.exit(1 if watch(float(sys.argv[2])) else 0)
    elif mode == "monitoring":
        monitoring()
    else:
        sys.exit(f"unknown mode {mode!r}: use check, watch N or monitoring")
