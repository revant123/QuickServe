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
"""

import argparse
import logging
import signal
import threading

from app.core.config import get_settings
from app.core.logging import configure_logging, log_event
from app.database import models  # noqa: F401  (registers every model with SQLAlchemy)
from app.database.session import SessionLocal
from app.modules.orders.schema import TimeoutReport
from app.modules.orders.service import run_timeouts

log = logging.getLogger("quickserve.worker")
stop_requested = threading.Event()


def run_once() -> TimeoutReport:
    with SessionLocal() as db:
        report = run_timeouts(db)
    level = logging.INFO if (report.payment_expired or report.auto_rejected) else logging.DEBUG
    log_event(
        log, level, "timeout job finished", payment_expired=report.payment_expired, auto_rejected=report.auto_rejected
    )
    return report


def run_forever(interval_seconds: int) -> None:
    log_event(log, logging.INFO, "worker started", interval_seconds=interval_seconds)
    while not stop_requested.is_set():
        try:
            run_once()
        except Exception:
            # One bad pass (database restarting, say) must not kill the worker.
            log.exception("timeout job failed, will retry next interval")
        # wait() returns early the moment a stop is requested: no waiting out the full interval.
        stop_requested.wait(interval_seconds)
    log_event(log, logging.INFO, "worker stopped cleanly")


def _handle_signal(signum, _frame) -> None:
    log_event(log, logging.INFO, "shutdown signal received", signal=signal.Signals(signum).name)
    stop_requested.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="QuickServe background worker")
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    args = parser.parse_args()

    configure_logging()
    if args.once:
        run_once()
        return
    signal.signal(signal.SIGTERM, _handle_signal)  # docker stop / kubectl delete pod
    signal.signal(signal.SIGINT, _handle_signal)  # Ctrl+C
    run_forever(get_settings().worker_interval_seconds)


if __name__ == "__main__":
    main()
