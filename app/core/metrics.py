"""Prometheus metrics: numbers that answer "how is QuickServe doing right now?"

Logs (Phase 4) tell the story of ONE request. Metrics are counters and
timers added up across ALL requests, cheap enough to keep for every second:
requests per second, error rate, slowest 5%, orders per hour, payment
success rate, cache hit rate, cost per order.

Prometheus scrapes them every 15 seconds from a small HTTP server on its own
port (9100 for the API, 9101 for the worker). Keeping them off the public
port means customers can't read business numbers like orders per hour.

Two rules keep metrics cheap and correct:

1. Labels must have a SMALL, FIXED set of values. Every distinct label
   combination is a separate time series that Prometheus stores (and a managed
   service bills for). So the HTTP label is the route TEMPLATE
   ("/api/v1/orders/{order_id}"), never the real path with an ID in it, and
   there is never a user_id or order_id label.

2. Business counters move only AFTER the database commit. If an order's
   transaction rolls back, "orders placed" must not have gone up. after_commit()
   below queues the increment and a SQLAlchemy session event runs it once the
   commit has succeeded (or drops it on rollback).
"""

import time
from collections.abc import Callable

from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server
from sqlalchemy import event
from sqlalchemy.orm import Session

# ---------- HTTP: the RED signals (Rate, Errors, Duration) ----------

HTTP_REQUESTS = Counter(
    "quickserve_http_requests_total",
    "HTTP requests handled, by route template and status code",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "quickserve_http_request_duration_seconds",
    "Time to handle a request, by route template",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ---------- Business ----------

ORDERS_PLACED = Counter("quickserve_orders_placed_total", "Orders placed (committed)")
ORDER_VALUE = Histogram(
    "quickserve_order_value_rupees",
    "Grand total of placed orders, in rupees (gives average order value)",
    buckets=(100, 200, 300, 500, 800, 1200, 2000, 5000),
)
ORDER_STATUS_CHANGES = Counter(
    "quickserve_order_status_changes_total",
    "Order status changes, by new status and who made the change",
    ["to_status", "actor"],
)
# Pricing (Phase 11). Labels are small fixed sets (who funded it; why surge),
# never the coupon code: thousands of codes would mean thousands of series.
COUPON_DISCOUNT = Counter(
    "quickserve_coupon_discount_rupees_total", "Coupon discount given on placed orders, by who pays", ["funded_by"]
)
SURGE_ORDERS = Counter("quickserve_surge_orders_total", "Orders that paid a surge fee, by reason", ["reason"])
PAYMENTS = Counter("quickserve_payments_total", "Payment attempts recorded, by outcome", ["outcome"])
MENU_CACHE = Counter("quickserve_menu_cache_requests_total", "Customer menu reads, by cache result", ["result"])
LOGINS = Counter("quickserve_logins_total", "Login attempts, by outcome", ["outcome"])

# ---------- Background worker ----------

WORKER_RUNS = Counter("quickserve_worker_runs_total", "Timeout job passes, by outcome", ["outcome"])
WORKER_TIMEOUTS = Counter(
    "quickserve_worker_orders_timed_out_total", "Orders closed by the timeout job, by reason", ["reason"]
)
WORKER_LAST_RUN = Gauge(
    "quickserve_worker_last_run_timestamp_seconds",
    "When the worker loop last finished a pass, successful or not (its heartbeat)",
)
WORKER_LAST_SUCCESS = Gauge(
    "quickserve_worker_last_success_timestamp_seconds", "When the timeout job last finished without an error"
)

# ---------- Notifier and outbox (Phase 8) ----------

OUTBOX_PENDING = Gauge("quickserve_outbox_pending_events", "Outbox events waiting to be delivered")
OUTBOX_OLDEST_AGE = Gauge(
    "quickserve_outbox_oldest_pending_age_seconds", "How long the oldest waiting event has waited (0 if none)"
)
OUTBOX_DEAD = Gauge("quickserve_outbox_dead_events", "Events the notifier gave up on (need a human)")
OUTBOX_PROCESSED = Counter(
    "quickserve_outbox_events_processed_total", "Outbox events handled, by outcome", ["outcome"]
)  # published / retry / dead
NOTIFICATIONS_CREATED = Counter("quickserve_notifications_created_total", "Notifications created, by kind", ["kind"])
NOTIFIER_LAST_RUN = Gauge(
    "quickserve_notifier_last_run_timestamp_seconds", "When the notifier loop last ran (heartbeat)"
)

# ---------- Infrastructure ----------

DB_POOL_IN_USE = Gauge("quickserve_db_pool_connections_in_use", "Database connections currently checked out")
BUILD = Info("quickserve_build", "Version of the running code")


# ---------- Route label ----------


def route_label(scope: dict) -> str:
    """The route template for a request, e.g. "/api/v1/orders/{order_id}".

    FastAPI records the matched route in scope["route"]. Its path is relative to
    the router it was declared in ("/orders/{order_id}"), so the static prefix
    ("/api/v1") is taken from the real path. Requests that matched no route all
    share one label, so random URLs from scanners can't create new time series.
    """
    template = getattr(scope.get("route"), "path", None)
    if template is None:
        return "unmatched"
    path = scope.get("path", "")
    extra = path.count("/") - template.count("/")
    if extra > 0:
        template = "/".join(path.split("/")[: extra + 1]) + template
    return template


# ---------- Counting only what was committed ----------

_PENDING = "quickserve_metrics_after_commit"


def after_commit(db: Session, increment: Callable[[], None]) -> None:
    """Run `increment` once the current transaction commits; forget it on rollback."""
    db.info.setdefault(_PENDING, []).append(increment)


@event.listens_for(Session, "after_commit")
def _run_pending(session: Session) -> None:
    for increment in session.info.pop(_PENDING, []):
        increment()


@event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING, None)


# ---------- Starting the metrics server ----------


def start_metrics_server(port: int, version: str) -> bool:
    """Serve /metrics on `port` in a background thread. Port 0 means off."""
    BUILD.info({"version": version})
    if not port:
        return False
    start_http_server(port)
    return True


def track_db_pool(engine) -> None:
    DB_POOL_IN_USE.set_function(lambda: engine.pool.checkedout())


def worker_heartbeat(success: bool) -> None:
    now = time.time()
    WORKER_LAST_RUN.set(now)
    if success:
        WORKER_LAST_SUCCESS.set(now)
