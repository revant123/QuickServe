"""Print the SQL that SQLAlchemy generates for QuickServe's key queries.

Run:  python -m scripts.show_sql      (no database needed: it only compiles)

"ORM does not eliminate SQL." This script is how you check that claim yourself.
For the live version, set SQL_ECHO=true in .env and watch the server log.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import selectinload

import app.database.models  # noqa: F401
from app.modules.menu.analytics import build_best_sellers_stmt
from app.modules.menu.model import MenuItem
from app.modules.menu.repository import build_consume_stmt
from app.modules.restaurants.model import Restaurant

DIALECT = postgresql.dialect()
some_id = uuid.UUID(int=1)


def show(title: str, stmt) -> None:
    print(f"\n-- {title}\n" + "-" * 72)
    print(stmt.compile(dialect=DIALECT))


if __name__ == "__main__":
    show("1. Reserve 2 units atomically (consume_atomically)", build_consume_stmt(some_id, some_id, 2))
    show(
        "2. Lock an item before restocking (lock_item)",
        select(MenuItem).where(MenuItem.id == some_id).with_for_update(),
    )
    show(
        "3. Restaurants with menus, query 1 of 2 (selectinload sends a second SELECT ... WHERE restaurant_id IN (...))",
        select(Restaurant).options(selectinload(Restaurant.menu_items)),
    )
    show(
        "4. Best-seller report (CTE + GROUP BY + window function)",
        build_best_sellers_stmt(some_id, datetime(2026, 11, 1, tzinfo=UTC)),
    )
