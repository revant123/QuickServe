"""Check tracing end to end (Phase 15): one order's trace, from the API through the outbox to the notifier.

    python3 scripts/trace_check.py                                   # Docker Compose
    python3 scripts/trace_check.py --api URL --jaeger URL [--insecure] [--expect-service NAME]

It logs in as the seed's demo customer, places and pays for an order, takes the
X-Trace-Id of the payment request, then asks Jaeger's API for that trace until it
contains the API's spans AND the notifier's "process order.status_changed" span,
seconds later, in the same trace. Prints a little tree of what it found.

Standard library only, so it runs anywhere Python does (CI runners included).
"""

import argparse
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
import uuid

CUSTOMER = ("customer@quickserve.dev", "customer-pass-123")


class Client:
    def __init__(self, base: str, insecure: bool):
        self.base = base.rstrip("/")
        self.ctx = ssl._create_unverified_context() if insecure else None  # noqa: S323 (local self-signed CA)

    def call(self, method, path, body=None, token=None, headers=None, form=None):
        data, hdrs = None, dict(headers or {})
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        with urllib.request.urlopen(req, timeout=10, context=self.ctx) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), resp.headers


def place_paid_order(api: Client) -> str:
    _, login, _ = api.call("POST", "/api/v1/auth/login", form={"username": CUSTOMER[0], "password": CUSTOMER[1]})
    token = login["access_token"]
    _, restaurants, _ = api.call("GET", "/api/v1/restaurants")
    restaurants = restaurants["items"] if isinstance(restaurants, dict) else restaurants
    for r in restaurants:
        _, menu, _ = api.call("GET", f"/api/v1/restaurants/{r['id']}/menu")
        dish = next((m for m in menu if m.get("available") is None or m["available"] > 0), None)
        if r.get("is_open", True) and dish:
            break
    else:
        raise SystemExit("no open restaurant with a dish in stock: run the seed first")
    body = {
        "restaurant_id": r["id"],
        "delivery_address": "Trace check",
        "delivery_location": {"lat": float(r["latitude"]) + 0.002, "lng": float(r["longitude"])},
        "items": [{"menu_item_id": dish["id"], "quantity": 1}],
    }
    _, order, _ = api.call("POST", "/api/v1/orders", body, token)
    status, _, headers = api.call(
        "POST", f"/api/v1/orders/{order['id']}/payments", token=token, headers={"Idempotency-Key": uuid.uuid4().hex}
    )
    trace_id = headers.get("X-Trace-Id")
    if status not in (200, 201) or not trace_id:
        raise SystemExit(f"payment returned {status} with no X-Trace-Id: is TRACING_ENABLED on?")
    print(f"order {order['id'][:8]} paid; trace {trace_id}")
    return trace_id


def wait_for_trace(jaeger: Client, trace_id: str, expect: set[str], timeout: float) -> dict:
    """Poll Jaeger. Traces appear after the tail sampler's decision_wait (10 s) plus batching."""
    deadline = time.monotonic() + timeout
    last = "not found yet"
    while time.monotonic() < deadline:
        try:
            _, found, _ = jaeger.call("GET", f"/api/traces/{trace_id}")
            data = (found or {}).get("data") or []
            if data:
                t = data[0]
                services = {p["serviceName"] for p in t["processes"].values()}
                consumer = any(s["operationName"] == "process order.status_changed" for s in t["spans"])
                if expect <= services and consumer:
                    return t
                last = f"services {sorted(services)}, notifier span: {consumer}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        time.sleep(2)
    raise SystemExit(f"trace {trace_id} incomplete after {timeout:.0f} s ({last})")


def show(t: dict) -> None:
    by_id = {s["spanID"]: s for s in t["spans"]}
    children: dict[str | None, list] = {}
    for s in t["spans"]:
        parent = next((r["spanID"] for r in s.get("references", []) if r["refType"] == "CHILD_OF"), None)
        children.setdefault(parent if parent in by_id else None, []).append(s)
    start = min(s["startTime"] for s in t["spans"])

    def walk(parent, depth):
        for s in sorted(children.get(parent, []), key=lambda x: x["startTime"]):
            service = t["processes"][s["processID"]]["serviceName"]
            print(
                f"  {'  ' * depth}{s['operationName'][:60]:<{62 - 2 * depth}} "
                f"+{(s['startTime'] - start) / 1000:7.1f} ms {s['duration'] / 1000:7.1f} ms  {service}"
            )
            walk(s["spanID"], depth + 1)

    walk(None, 0)
    sql = sum(1 for s in t["spans"] if any(tag["key"] == "db.system.name" for tag in s.get("tags", [])))
    print(f"{len(t['spans'])} spans, {sql} of them SQL statements")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8001")
    parser.add_argument("--jaeger", default="http://localhost:16686")
    parser.add_argument("--insecure", action="store_true", help="accept QuickServe's local CA (through the Gateway)")
    parser.add_argument("--expect-service", action="append", default=[], help="another service the trace must include")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()

    trace_id = place_paid_order(Client(args.api, args.insecure))
    expect = {"quickserve-api", "quickserve-notifier", *args.expect_service}
    t = wait_for_trace(Client(args.jaeger, args.insecure), trace_id, expect, args.timeout)
    show(t)
    print(f"Trace OK: {', '.join(sorted(expect))} in one trace.")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as exc:
        sys.exit(f"could not connect: {exc}")
