"""Smoke test for QuickServe running in Kubernetes. Standard library only.

It runs INSIDE the cluster, so it reaches the API through its Service name
("http://api"), exactly like another service would:

    kubectl -n quickserve exec -i deploy/worker -- python - check    < infra/k8s/smoke_test.py
    kubectl -n quickserve exec -i deploy/worker -- python - watch 60 < infra/k8s/smoke_test.py

check       health, login as the demo customer, call /users/me (needs the seed data)
watch N     hit /health/ready 5 times a second for N seconds and count failures.
            Run it during `kubectl rollout restart deployment/api`: 0 failures
            means the rolling update caused no downtime.
monitoring  Prometheus scrapes every API and worker pod, has seen the login
            from `check`, fires no alerts; Grafana has loaded the dashboard.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://api"


def get(path, token=None, timeout=3):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read() or b"null")


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


def prom(query):
    url = "http://prometheus:9090/api/v1/query?" + urllib.parse.urlencode({"query": query})
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())["data"]["result"]


def monitoring(timeout=120):
    deadline = time.monotonic() + timeout
    checks = {
        "every API and worker pod is scraped": 'count(up{job="quickserve"} == 1) >= 3',
        "the login from `check` was counted": 'sum(quickserve_logins_total{outcome="success"}) >= 1',
        "the worker heartbeat is fresh": "time() - max(quickserve_worker_last_run_timestamp_seconds) < 120",
        "the recording rules run": "quickserve:infra_cost_usd:per_hour",
    }
    pending = dict(checks)
    while pending and time.monotonic() < deadline:
        for name, query in list(pending.items()):
            try:
                if prom(query):
                    print("prometheus:", name)
                    del pending[name]
            except (urllib.error.URLError, OSError):
                pass  # Prometheus still starting
        if pending:
            time.sleep(5)
    assert not pending, f"not seen within {timeout}s: {list(pending)}"

    firing = prom('ALERTS{alertstate="firing"}')
    assert not firing, f"alerts firing: {firing}"
    print("prometheus: no alerts firing")

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
