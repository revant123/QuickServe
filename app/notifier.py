"""The notifier: delivers outbox events as notifications (Phase 8).

    python -m app.notifier              # run until stopped (SIGTERM / Ctrl+C)
    python -m app.notifier --once       # one batch, then exit
    python -m app.notifier --healthcheck  # Kubernetes liveness probe

How one pass works, all inside ONE database transaction:

  1. Lock a batch of waiting events (FOR UPDATE SKIP LOCKED), at most the
     oldest waiting event per order, so each order's events arrive in order.
     Repeat until nothing is left (or the batch limit): once an order's event
     is published, its next one becomes claimable.
  2. For each event, in a SAVEPOINT:
       - create its notifications (idempotent: ON CONFLICT DO NOTHING)
       - success: mark it published
       - failure: undo just that event's work, count the attempt, and retry it
         later with exponential backoff; after 5 attempts mark it dead
  3. Commit. Notifications and "published" become visible together.

Delivery is AT-LEAST-ONCE: if the process dies after step 2 but before the
commit, the whole pass rolls back and the events are handled again next time.
The (event_id, user_id) unique constraint makes that repeat harmless.

Why a separate process and not part of the API? It's the first piece that
behaves like its own service: it only reads the outbox, never calls the orders
code, and is deployed, scaled and restarted on its own. Swap the outbox table
for Kafka or SQS and it becomes a microservice with the same logic.
"""

import argparse
import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event
from app.core.metrics import (
    NOTIFICATIONS_CREATED,
    NOTIFIER_LAST_RUN,
    OUTBOX_DEAD,
    OUTBOX_OLDEST_AGE,
    OUTBOX_PENDING,
    OUTBOX_PROCESSED,
    after_commit,
    start_metrics_server,
)
from app.database import models  # noqa: F401  (registers every model with SQLAlchemy)
from app.database.session import SessionLocal, transaction
from app.modules.menu.repository import db_now
from app.modules.notifications.service import handle_event
from app.modules.outbox import service as outbox
from app.worker import healthcheck

log = logging.getLogger("quickserve.notifier")
stop_requested = threading.Event()
HEARTBEAT_METRIC = "quickserve_notifier_last_run_timestamp_seconds"


@dataclass
class RelayReport:
    published: int = 0
    retried: int = 0
    dead: int = 0
    notifications: list[str] = field(default_factory=list)  # kinds created

    @property
    def handled(self) -> int:
        return self.published + self.retried + self.dead


def run_once(settings: Settings | None = None) -> RelayReport:
    """Handle one batch of outbox events. Returns what happened."""
    settings = settings or get_settings()
    report = RelayReport()
    with SessionLocal() as db, transaction(db):
        now = db_now(db)
        # Claim again after each round: an order's next event becomes claimable
        # once the one before it is published (within this same transaction).
        while report.handled < settings.notifier_batch_size:
            claimed = outbox.claim_batch(db, now, settings.notifier_batch_size - report.handled)
            if not claimed:
                break
            _handle_round(db, claimed, now, settings, report)
            db.flush()  # write "published" now, so the next claim can see it
        after_commit(db, lambda: _count(report))
    return report


def _handle_round(db, claimed: list, now, settings: Settings, report: RelayReport) -> None:
    for event in claimed:
        try:
            with db.begin_nested():  # SAVEPOINT: a failure undoes only this event
                created = handle_event(db, event)
            event.published_at = now
            report.published += 1
            report.notifications += [m.kind for m in created]
            for m in created:
                # Stand-in for a real push/SMS/email provider. Runs after the
                # commit, so nobody is told about something that rolled back.
                after_commit(db, _send_push(m, event.id))
        except Exception as exc:  # noqa: BLE001  (any failure: retry, never crash the loop)
            event.attempts += 1
            event.last_error = f"{type(exc).__name__}: {exc}"[:500]
            if event.attempts >= settings.notifier_max_attempts:
                event.dead_at = now
                report.dead += 1
                log_event(log, logging.ERROR, "event dead-lettered", event_id=event.id, error=event.last_error)
            else:
                event.available_at = now + outbox.retry_delay(event.attempts)
                report.retried += 1
                log_event(log, logging.WARNING, "event failed, will retry", event_id=event.id, attempt=event.attempts)


def _send_push(msg, event_id: int):
    def send() -> None:
        NOTIFICATIONS_CREATED.labels(msg.kind).inc()
        log_event(log, logging.INFO, "notification sent", event_id=event_id, user_id=msg.user_id, kind=msg.kind)

    return send


def _count(report: RelayReport) -> None:
    OUTBOX_PROCESSED.labels("published").inc(report.published)
    OUTBOX_PROCESSED.labels("retry").inc(report.retried)
    OUTBOX_PROCESSED.labels("dead").inc(report.dead)


def housekeeping(settings: Settings | None = None) -> int:
    """Update the backlog gauges and delete delivered events past retention."""
    settings = settings or get_settings()
    with SessionLocal() as db, transaction(db):
        now = db_now(db)
        deleted = outbox.delete_published_before(db, now - timedelta(days=settings.outbox_retention_days))
        pending, oldest_age, dead = outbox.backlog(db, now)
    OUTBOX_PENDING.set(pending)
    OUTBOX_OLDEST_AGE.set(oldest_age)
    OUTBOX_DEAD.set(dead)
    return deleted


def run_forever(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if start_metrics_server(settings.notifier_metrics_port, "notifier"):
        log_event(log, logging.INFO, "metrics server started", port=settings.notifier_metrics_port)
    NOTIFIER_LAST_RUN.set(time.time())
    log_event(log, logging.INFO, "notifier started", interval_seconds=settings.notifier_interval_seconds)
    next_housekeeping = 0.0
    while not stop_requested.is_set():
        busy = False
        try:
            report = run_once(settings)
            # A full batch means more may be waiting: go again without sleeping.
            busy = report.handled >= settings.notifier_batch_size
            if report.handled:
                log_event(
                    log,
                    logging.INFO,
                    "outbox batch done",
                    published=report.published,
                    retried=report.retried,
                    dead=report.dead,
                    notifications=len(report.notifications),
                )
            if time.monotonic() >= next_housekeeping:
                housekeeping(settings)
                next_housekeeping = time.monotonic() + 15
        except Exception:
            log.exception("notifier pass failed, will retry")
        NOTIFIER_LAST_RUN.set(time.time())
        if not busy:
            stop_requested.wait(settings.notifier_interval_seconds)
    log_event(log, logging.INFO, "notifier stopped cleanly")


def _handle_signal(signum, _frame) -> None:
    log_event(log, logging.INFO, "shutdown signal received", signal=signal.Signals(signum).name)
    stop_requested.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="QuickServe notifier: delivers outbox events")
    parser.add_argument("--once", action="store_true", help="handle one batch and exit")
    parser.add_argument("--healthcheck", action="store_true", help="exit 0 if the running notifier beat recently")
    args = parser.parse_args()
    settings = get_settings()

    if args.healthcheck:
        max_age = 10 * settings.notifier_interval_seconds + 60
        sys.exit(0 if healthcheck(settings.notifier_metrics_port, max_age, HEARTBEAT_METRIC) else 1)

    configure_logging()
    if args.once:
        report = run_once(settings)
        housekeeping(settings)
        print(report)
        return
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    run_forever(settings)


if __name__ == "__main__":
    main()
