"""Wait until the database schema is at the newest migration, then exit 0.

Kubernetes runs this as an init container in front of the API and the worker:

    python -m scripts.wait_for_migrations --timeout 300

Why wait instead of migrating? With 3 API pods starting together, 3 copies of
`alembic upgrade head` would race to change the same tables. Instead ONE
migration Job upgrades the schema, and every pod only waits for it. A pod
started with new code never serves requests against an old schema.

Exit codes: 0 = schema is current, 1 = timed out (Kubernetes retries the pod).
"""

import argparse
import logging
import time
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.core.logging import configure_logging, log_event

log = logging.getLogger("quickserve.wait_for_migrations")
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def expected_heads() -> set[str]:
    """The newest revision(s) in the migrations folder shipped with this image."""
    return set(ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads())


def current_heads(engine: Engine) -> set[str]:
    """The revision(s) the database says it is at (empty before the first migration)."""
    with engine.connect() as conn:
        return set(MigrationContext.configure(conn).get_current_heads())


def schema_is_current(engine: Engine, heads: set[str] | None = None) -> bool:
    return current_heads(engine) == (heads if heads is not None else expected_heads())


def wait(engine: Engine, timeout_s: float, interval_s: float = 2.0, heads: set[str] | None = None) -> bool:
    heads = heads if heads is not None else expected_heads()
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            current = current_heads(engine)
            if current == heads:
                log_event(log, logging.INFO, "schema is current", revision=",".join(sorted(heads)))
                return True
            log_event(log, logging.INFO, "waiting for migrations", current=",".join(sorted(current)) or "none")
        except OperationalError as exc:  # database not reachable yet
            log_event(log, logging.INFO, "waiting for database", error=type(exc).__name__)
        if time.monotonic() >= deadline:
            log_event(log, logging.ERROR, "gave up waiting for migrations", timeout_s=timeout_s)
            return False
        time.sleep(interval_s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait (default 300)")
    args = parser.parse_args()

    configure_logging()
    logging.getLogger("alembic").setLevel(logging.WARNING)  # skip "Context impl ..." on every check
    from app.database.session import engine  # imported late so logging is set up first

    return 0 if wait(engine, args.timeout) else 1


if __name__ == "__main__":
    raise SystemExit(main())
