"""The background worker: runs the order timeout job on a schedule.

Run it in its own terminal, next to the API:

    python -m app.worker            # every WORKER_INTERVAL_SECONDS (default 30)
    python -m app.worker --once     # one pass, then exit (handy for testing or cron)

Why a separate process instead of a timer inside the API?
  - The API may run as 4 processes on 3 machines; a timer inside each would run
    the job 12 times. A worker is deployed and scaled on its own.
  - A slow job never steals CPU from customer requests.

Can I run two workers at once? Yes. The job claims orders with
SELECT ... FOR UPDATE SKIP LOCKED, so each worker takes different rows and no
order is processed twice. Extra workers are for resilience (one machine dies,
another keeps going), not speed.

Graceful shutdown: Docker and Kubernetes stop containers by sending SIGTERM and,
after a grace period, SIGKILL. The worker catches SIGTERM, finishes the pass it
is in the middle of (so no transaction is cut in half), then exits.

Heartbeat (Phase 7b): every pass, successful or not, updates a "last run"
timestamp served on the metrics port (9101). `python -m app.worker --healthcheck`
reads it, and Kubernetes uses that as the worker's liveness probe: if the loop
is stuck, the pod is restarted. A FAILING job (database down) still beats, so it
is not restarted; that case raises an alert instead (no success for 5 minutes).
"""

import argparse
import logging
import signal
import sys
import threading
import time
import urllib.request

from prometheus_client.parser import text_string_to_metric_families

from app.core.config import get_settings
from app.core.logging import configure_logging, log_event
from app.core.metrics import WORKER_RUNS, WORKER_TIMEOUTS, start_metrics_server, worker_heartbeat
from app.database import models  # noqa: F401  (registers every model with SQLAlchemy)
from app.database.session import SessionLocal
from app.modules.orders.schema import TimeoutReport
from app.modules.orders.service import run_timeouts

log = logging.getLogger("quickserve.worker")
stop_requested = threading.Event()


def run_once() -> TimeoutReport:
    with SessionLocal() as db:
        report = run_timeouts(db)
    WORKER_TIMEOUTS.labels("payment_expired").inc(report.payment_expired)
    WORKER_TIMEOUTS.labels("auto_rejected").inc(report.auto_rejected)
    level = logging.INFO if (report.payment_expired or report.auto_rejected) else logging.DEBUG
    log_event(
        log, level, "timeout job finished", payment_expired=report.payment_expired, auto_rejected=report.auto_rejected
    )
    return report


def run_forever(interval_seconds: int, metrics_port: int = 0) -> None:
    if start_metrics_server(metrics_port, "worker"):
        log_event(log, logging.INFO, "metrics server started", port=metrics_port)
    worker_heartbeat(success=False)  # alive from the start, before the first pass
    log_event(log, logging.INFO, "worker started", interval_seconds=interval_seconds)
    while not stop_requested.is_set():
        try:
            run_once()
            WORKER_RUNS.labels("ok").inc()
            worker_heartbeat(success=True)
        except Exception:
            # One bad pass (database restarting, say) must not kill the worker.
            log.exception("timeout job failed, will retry next interval")
            WORKER_RUNS.labels("error").inc()
            worker_heartbeat(success=False)
        # wait() returns early the moment a stop is requested: no waiting out the full interval.
        stop_requested.wait(interval_seconds)
    log_event(log, logging.INFO, "worker stopped cleanly")


def _handle_signal(signum, _frame) -> None:
    log_event(log, logging.INFO, "shutdown signal received", signal=signal.Signals(signum).name)
    stop_requested.set()


def heartbeat_age_seconds(port: int) -> float | None:
    """Seconds since the running worker's last pass, read from its metrics port."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=3) as resp:
        text = resp.read().decode()
    for family in text_string_to_metric_families(text):
        if family.name == "quickserve_worker_last_run_timestamp_seconds" and family.samples:
            return time.time() - family.samples[0].value
    return None


def healthcheck(port: int, max_age_seconds: float) -> bool:
    """True if the worker on this machine finished a pass recently enough."""
    try:
        age = heartbeat_age_seconds(port)
    except OSError:  # nothing listening: the worker isn't running
        return False
    return age is not None and age <= max_age_seconds


def main() -> None:
    parser = argparse.ArgumentParser(description="QuickServe background worker")
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument("--healthcheck", action="store_true", help="exit 0 if the running worker beat recently, else 1")
    args = parser.parse_args()
    settings = get_settings()

    if args.healthcheck:
        # Three missed passes plus a margin: one slow pass isn't a stuck worker.
        sys.exit(0 if healthcheck(settings.worker_metrics_port, 3 * settings.worker_interval_seconds + 30) else 1)

    configure_logging()
    if args.once:
        run_once()
        return
    signal.signal(signal.SIGTERM, _handle_signal)  # docker stop / kubectl delete pod
    signal.signal(signal.SIGINT, _handle_signal)  # Ctrl+C
    run_forever(settings.worker_interval_seconds, settings.worker_metrics_port)


if __name__ == "__main__":
    main()
