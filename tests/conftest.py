"""Test setup: a REAL PostgreSQL database, built by running our Alembic migrations.

Why not SQLite for tests? Because the features we rely on (row locks,
FOR UPDATE SKIP LOCKED, partial unique indexes, RETURNING, CHECK constraints
under concurrency) behave differently or don't exist there. A test that passes
on SQLite would prove nothing about production. CI runs the same PostgreSQL
version in a service container.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/quickserve_test")

from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.menu.schema import MenuItemCreate  # noqa: E402
from app.modules.menu.service import create_menu_item  # noqa: E402
from app.modules.restaurants.model import Restaurant  # noqa: E402
from app.modules.users.model import Role, User  # noqa: E402

TABLES = "payments, order_status_events, order_items, orders, inventory_cycles, menu_items, restaurants, users"

# Safety guard: these tests TRUNCATE every table. Refuse to run against anything
# that isn't clearly a test database (e.g. if DATABASE_URL in your shell points
# at your dev data).
if not engine.url.database or not engine.url.database.endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against database '{engine.url.database}': its name must end in _test")


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Run the real migrations once per test session. This also tests the migrations."""
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    yield
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
        user = User(name=f"User {counter['n']}", email=f"user{counter['n']}@example.com", password_hash="x", role=role)
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def restaurant(db, make_user) -> Restaurant:
    owner = make_user(Role.RESTAURANT_OWNER)
    r = Restaurant(
        owner_id=owner.id, name="Sharma Dhaba", address="Sector 17, Chandigarh", packaging_charge=Decimal("20.00")
    )
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def customer(make_user) -> User:
    return make_user(Role.CUSTOMER)


@pytest.fixture
def make_item(db, restaurant):
    def _make(name="Paneer Tikka", price="150.00", stock: int | None = 10, track_stock=True):
        return create_menu_item(
            db,
            restaurant.id,
            MenuItemCreate(
                name=name, price=Decimal(price), stock=stock if track_stock else None, track_stock=track_stock
            ),
        )

    return _make
