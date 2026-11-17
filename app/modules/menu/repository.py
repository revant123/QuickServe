"""Database access for menu items and stock cycles.

Each function shows the SQL it generates in its docstring, so you can compare
what you write in Python with what PostgreSQL receives. Set SQL_ECHO=true in
.env to see the real statements in your terminal.
"""

import uuid

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.modules.menu.model import InventoryCycle, MenuItem


def consume_atomically(db: Session, menu_item_id: uuid.UUID, restaurant_id: uuid.UUID, qty: int) -> Row | None:
    """Reserve `qty` units in ONE statement. Returns None if the item can't cover it."""
    return db.execute(build_consume_stmt(menu_item_id, restaurant_id, qty)).one_or_none()


def build_consume_stmt(menu_item_id: uuid.UUID, restaurant_id: uuid.UUID, qty: int):
    """Build (don't run) the reservation UPDATE. Kept separate so scripts/show_sql.py can print it.

    Generated SQL (simplified):

        UPDATE menu_items
           SET consumed    = consumed + :qty,
               sold_out_at = CASE WHEN track_stock AND sold_out_at IS NULL
                                   AND consumed + :qty = stock
                                  THEN now() ELSE sold_out_at END
         WHERE id = :id AND restaurant_id = :rid
           AND ((is_available AND unavailable_until IS NULL) OR unavailable_until <= now())
           AND (NOT track_stock OR consumed + :qty <= stock)
        RETURNING id, name, price, cycle_no, stock, consumed

    Why one conditional UPDATE instead of "SELECT, check in Python, then UPDATE"?
    Between your SELECT and your UPDATE another request can sell the same last
    unit (a race condition). Here the check and the write happen together, under
    the row lock PostgreSQL takes for the UPDATE. If two requests race for the
    last unit, the second one waits, re-checks the WHERE clause against the new
    value, matches zero rows, and gets None.
    """
    now = func.now()
    return (
        update(MenuItem)
        .where(
            MenuItem.id == menu_item_id,
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.switched_on_at(now),  # hybrid method -> SQL expression
            or_(MenuItem.track_stock.is_(False), MenuItem.consumed + qty <= MenuItem.stock),
        )
        .values(
            consumed=MenuItem.consumed + qty,
            sold_out_at=case(
                (
                    and_(
                        MenuItem.track_stock.is_(True),
                        MenuItem.sold_out_at.is_(None),
                        MenuItem.consumed + qty == MenuItem.stock,
                    ),
                    now,
                ),
                else_=MenuItem.sold_out_at,
            ),
        )
        .returning(MenuItem.id, MenuItem.name, MenuItem.price, MenuItem.cycle_no, MenuItem.stock, MenuItem.consumed)
        # "fetch" keeps any MenuItem object already loaded in this session in sync
        # with the new values that RETURNING sent back.
        .execution_options(synchronize_session="fetch")
    )


def release_from_current_cycle(db: Session, menu_item_id: uuid.UUID, cycle_no: int, qty: int) -> bool:
    """Give units back, but only if the item is still in the same cycle.

        UPDATE menu_items SET consumed = consumed - :qty
         WHERE id = :id AND cycle_no = :cycle_no AND consumed >= :qty
        RETURNING id

    The cycle_no condition matters: if the restaurant restocked after this order
    was placed, consumed was reset to 0 for the new cycle, and subtracting from it
    would corrupt the new cycle's numbers.
    """
    stmt = (
        update(MenuItem)
        .where(MenuItem.id == menu_item_id, MenuItem.cycle_no == cycle_no, MenuItem.consumed >= qty)
        .values(consumed=MenuItem.consumed - qty)
        .returning(MenuItem.id)
        .execution_options(synchronize_session="fetch")
    )
    return db.execute(stmt).one_or_none() is not None


def add_to_cycle_counter(
    db: Session, menu_item_id: uuid.UUID, cycle_no: int, *, returned: int = 0, wasted: int = 0
) -> None:
    """UPDATE inventory_cycles SET units_returned = units_returned + :r, units_wasted = units_wasted + :w
    WHERE menu_item_id = :id AND cycle_no = :cycle_no"""
    db.execute(
        update(InventoryCycle)
        .where(InventoryCycle.menu_item_id == menu_item_id, InventoryCycle.cycle_no == cycle_no)
        .values(
            units_returned=InventoryCycle.units_returned + returned,
            units_wasted=InventoryCycle.units_wasted + wasted,
        )
        .execution_options(synchronize_session="fetch")
    )


def lock_item(db: Session, menu_item_id: uuid.UUID) -> MenuItem | None:
    """SELECT ... FROM menu_items WHERE id = :id FOR UPDATE

    Used by restock, which must read `consumed`, archive it and reset it without
    any order slipping in between. FOR UPDATE makes concurrent orders for this
    item wait until the restock commits.

    populate_existing=True: if this MenuItem is already in the session's identity
    map, a normal SELECT would lock the row but hand back the OLD Python object
    with its old attribute values. populate_existing overwrites them with what
    the locked row really contains. Locking without it is a subtle bug.
    """
    return db.execute(
        select(MenuItem).where(MenuItem.id == menu_item_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()


def get_open_cycle(db: Session, menu_item_id: uuid.UUID) -> InventoryCycle:
    return db.execute(
        select(InventoryCycle)
        .where(InventoryCycle.menu_item_id == menu_item_id, InventoryCycle.closed_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def recent_closed_cycles(db: Session, menu_item_id: uuid.UUID, limit: int) -> list[InventoryCycle]:
    return list(
        db.execute(
            select(InventoryCycle)
            .where(InventoryCycle.menu_item_id == menu_item_id, InventoryCycle.closed_at.is_not(None))
            .order_by(InventoryCycle.cycle_no.desc())
            .limit(limit)
        ).scalars()
    )


def list_cycles(db: Session, menu_item_id: uuid.UUID) -> list[InventoryCycle]:
    return list(
        db.execute(
            select(InventoryCycle).where(InventoryCycle.menu_item_id == menu_item_id).order_by(InventoryCycle.cycle_no)
        ).scalars()
    )


def list_menu(db: Session, restaurant_id: uuid.UUID) -> list[MenuItem]:
    return list(
        db.execute(select(MenuItem).where(MenuItem.restaurant_id == restaurant_id).order_by(MenuItem.name)).scalars()
    )


def db_now(db: Session):
    """The database's clock, not the app server's. With several app servers,
    each machine's clock drifts a little; the database is the single source of time."""
    return db.execute(select(func.now())).scalar_one()
