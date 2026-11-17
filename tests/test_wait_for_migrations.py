"""The init container that makes Kubernetes pods wait for the migration Job."""

import time

from sqlalchemy import create_engine

from app.database.session import engine
from scripts.wait_for_migrations import expected_heads, schema_is_current, wait


def test_schema_is_current_after_migrations():
    # The test session ran `alembic upgrade head`, so the database is at head.
    assert expected_heads()
    assert schema_is_current(engine)


def test_detects_a_schema_that_is_behind():
    # Pretend the image contains a newer migration than the database has seen.
    assert not schema_is_current(engine, heads={"a-newer-revision"})


def test_wait_returns_immediately_when_current():
    started = time.monotonic()
    assert wait(engine, timeout_s=5)
    assert time.monotonic() - started < 2


def test_wait_gives_up_after_the_timeout():
    assert wait(engine, timeout_s=0.3, interval_s=0.1, heads={"a-newer-revision"}) is False


def test_wait_survives_an_unreachable_database():
    # Port 1: nothing listens there, like a database that hasn't started yet.
    down = create_engine("postgresql+psycopg://x:y@localhost:1/none", connect_args={"connect_timeout": 1})
    assert wait(down, timeout_s=0.2, interval_s=0.1) is False
