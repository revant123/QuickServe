"""Test setup: a REAL PostgreSQL database, built by running our Alembic migrations.

Why not SQLite for tests? Because the features we rely on (row locks,
FOR UPDATE SKIP LOCKED, partial unique indexes, RETURNING, CHECK constraints
under concurrency) behave differently or don't exist there. A test that passes
on SQLite would prove nothing about production. CI runs the same PostgreSQL
version in a service container.
"""

import os

from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import Settings  # noqa: E402

# Tests use the same server, port and credentials as your app (from .env), but a
# separate database: <your database>_test. CI sets DATABASE_URL itself.
# Redis: same server as the app, but database number 15, emptied after every test.
if "REDIS_URL" not in os.environ:
    _redis_base = Settings().redis_url.rsplit("/", 1)[0]
    os.environ["REDIS_URL"] = f"{_redis_base}/15"

# Surge hours depend on the clock: without this, a test run at 8 pm would add
# a peak fee and fail. Tests that check surge pass their own Settings.
os.environ.setdefault("PEAK_HOURS", "[]")
os.environ.setdefault("LATE_NIGHT_HOURS", "[]")

# No metrics HTTP servers in tests (tests read the metrics registry directly).
os.environ.setdefault("METRICS_PORT", "0")
os.environ.setdefault("WORKER_METRICS_PORT", "0")

if "DATABASE_URL" not in os.environ:
    _app_url = make_url(Settings().database_url)
    os.environ["DATABASE_URL"] = _app_url.set(database=f"{_app_url.database}_test").render_as_string(
        hide_password=False
    )

from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.redis import get_redis  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.menu.schema import MenuItemCreate  # noqa: E402
from app.modules.menu.service import create_menu_item  # noqa: E402
from app.modules.restaurants.model import Restaurant  # noqa: E402
from app.modules.users.model import Role, User  # noqa: E402

TEST_PASSWORD = "test-password-123"
# Two points in Chandigarh about 0.8 km apart in a straight line (1.0 km by road).
SECTOR_17 = (Decimal("30.739800"), Decimal("76.782700"))
SECTOR_22 = {"lat": 30.7333, "lng": 76.7794}
# Argon2 is slow ON PURPOSE (that is what makes stolen hashes hard to crack), so hash
# the shared test password once instead of once per test user.
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)
TABLES = "coupon_redemptions, coupons, surge_flags, notifications, outbox_events, payments, order_status_events, order_items, orders, inventory_cycles, menu_items, restaurants, users"

# Safety guard: these tests TRUNCATE every table. Refuse to run against anything
# that isn't clearly a test database (e.g. if DATABASE_URL in your shell points
# at your dev data).
if not engine.url.database or not engine.url.database.endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against database '{engine.url.database}': its name must end in _test")
if not os.environ["REDIS_URL"].endswith("/15"):
    raise RuntimeError("Refusing to run tests: REDIS_URL must use Redis database 15, which the tests empty")


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Run the real migrations once per test session. This also tests the migrations."""
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    get_redis().flushdb()
    yield
    get_redis().flushdb()
    # Tests commit for real (concurrency tests need several connections), so
    # instead of rolling back we empty the tables after each test.
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def make_user(db):
    counter = {"n": 0}

    def _make(role: Role = Role.CUSTOMER) -> User:
        counter["n"] += 1
        user = User(
            name=f"User {counter['n']}",
            email=f"user{counter['n']}@example.com",
            password_hash=TEST_PASSWORD_HASH,
            role=role,
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def owner(make_user) -> User:
    return make_user(Role.RESTAURANT_OWNER)


@pytest.fixture
def customer(make_user) -> User:
    return make_user(Role.CUSTOMER)


@pytest.fixture
def rider(make_user) -> User:
    return make_user(Role.RIDER)


@pytest.fixture
def admin(make_user) -> User:
    return make_user(Role.ADMIN)


@pytest.fixture
def restaurant(db, owner) -> Restaurant:
    r = Restaurant(
        owner_id=owner.id,
        name="Sharma Dhaba",
        address="Sector 17, Chandigarh",
        packaging_charge=Decimal("20.00"),
        latitude=SECTOR_17[0],
        longitude=SECTOR_17[1],
    )
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def make_item(db, restaurant, owner):
    def _make(name="Paneer Tikka", price="150.00", stock: int | None = 10, track_stock=True):
        return create_menu_item(
            db,
            restaurant.id,
            MenuItemCreate(
                name=name, price=Decimal(price), stock=stock if track_stock else None, track_stock=track_stock
            ),
            owner,
        )

    return _make
