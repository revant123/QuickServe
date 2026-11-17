"""Engine, connection pool and per-request sessions."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# The engine owns a pool of real TCP connections to PostgreSQL. Opening a
# connection costs a network round trip, authentication and a server process,
# so we reuse a few of them instead of opening one per request.
engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_size=settings.db_pool_size,  # connections kept open
    max_overflow=settings.db_max_overflow,  # extra ones allowed under burst load
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_pre_ping=True,  # detect connections the DB or a firewall dropped
)

# expire_on_commit=False: after commit, objects keep their loaded values, so a
# router can still read order.total_amount without triggering another SELECT.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session (one unit of work) per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()  # returns the connection to the pool; it does not close the TCP socket


@contextmanager
def transaction(db: Session) -> Iterator[Session]:
    """All-or-nothing block: commit if the block finishes, roll back if anything raises.

    Placing an order touches several rows (stock counters, the order, its items,
    a status event). Either all of those changes happen or none of them do.
    """
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
