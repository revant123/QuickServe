"""Business rules for menus and stock cycles."""

import math
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.database.session import transaction
from app.modules.menu import repository as repo
from app.modules.menu.model import InventoryCycle, MenuItem
from app.modules.menu.schema import AvailabilityUpdate, MenuItemCreate, MenuItemPublic, RestockSuggestion
from app.modules.restaurants.model import Restaurant

LOW_STOCK_THRESHOLD = 5  # show "Only N left" at or below this
SELLING_FAST_MINUTES = 60  # show "Selling fast" if it will sell out within this
MIN_SALES_FOR_VELOCITY = 3  # don't call something "fast" after one sale
MAX_DEMAND_EXTRAPOLATION = 2.0  # cap for the sold-out correction in restock suggestions


def create_menu_item(db: Session, restaurant_id: uuid.UUID, data: MenuItemCreate) -> MenuItem:
    with transaction(db):
        if db.get(Restaurant, restaurant_id) is None:
            raise NotFound("Restaurant not found")
        now = repo.db_now(db)
        item = MenuItem(restaurant_id=restaurant_id, cycle_started_at=now, consumed=0, cycle_no=1, **data.model_dump())
        db.add(item)
        db.flush()  # sends the INSERT now, so the cycle below can reference item.id
        db.add(InventoryCycle(menu_item_id=item.id, cycle_no=1, started_at=now, units_stocked=item.stock, carried_in=0))
    return item


def restock(
    db: Session, menu_item_id: uuid.UUID, quantity: int, carry_over_leftover: bool
) -> tuple[InventoryCycle, MenuItem]:
    """Close the current cycle, archive its numbers, start a new one with consumed = 0.

    Everything happens inside one transaction holding a row lock on the item:
    an order that arrives mid-restock waits, then lands in the new cycle.
    """
    with transaction(db):
        item = repo.lock_item(db, menu_item_id)
        if item is None:
            raise NotFound("Menu item not found")
        cycle = repo.get_open_cycle(db, menu_item_id)
        now = repo.db_now(db)

        leftover = item.available  # None for untracked items
        carried = leftover if (carry_over_leftover and leftover) else 0

        # 1. Archive the closing cycle.
        cycle.closed_at = now
        cycle.units_consumed = item.consumed
        cycle.sold_out_at = item.sold_out_at
        cycle.leftover = leftover
        cycle.leftover_carried = carry_over_leftover if item.track_stock else None
        # The partial unique index allows only one open cycle per item, so the
        # UPDATE that closes this cycle must reach the database before the
        # INSERT that opens the next one. An explicit flush guarantees the order.
        db.flush()

        # 2. Reset the live counters for the new cycle.
        item.cycle_no += 1
        item.stock = (quantity + carried) if item.track_stock else None
        item.consumed = 0
        item.sold_out_at = None
        item.cycle_started_at = now

        # 3. Open the new cycle.
        db.add(
            InventoryCycle(
                menu_item_id=item.id,
                cycle_no=item.cycle_no,
                started_at=now,
                units_stocked=item.stock,
                carried_in=carried,
            )
        )
    return cycle, item


def set_availability(db: Session, menu_item_id: uuid.UUID, data: AvailabilityUpdate) -> MenuItem:
    with transaction(db):
        item = db.get(MenuItem, menu_item_id)
        if item is None:
            raise NotFound("Menu item not found")
        item.is_available = data.is_available
        # Switching on clears any timer. Switching off with a time means "back at that time".
        item.unavailable_until = None if data.is_available else data.unavailable_until
    return item


def _is_orderable(item: MenuItem, now: datetime) -> bool:
    # Same hybrid method the order UPDATE uses, here running as plain Python.
    return item.switched_on_at(now) and (not item.track_stock or (item.available or 0) > 0)


def _badge(item: MenuItem, now: datetime) -> tuple[str | None, int | None]:
    """The customer-facing hint. Mirrors the "Only 3 left" / "Selling fast" tags
    shown on delivery and quick-commerce apps, computed from the live cycle."""
    if not item.track_stock or item.available is None:
        return None, None
    if item.available == 0:
        return "SOLD_OUT", None
    if item.available <= LOW_STOCK_THRESHOLD:
        return "ONLY_N_LEFT", item.available
    hours = max((now - item.cycle_started_at).total_seconds() / 3600, 0.25)
    if item.consumed >= MIN_SALES_FOR_VELOCITY:
        per_minute = item.consumed / (hours * 60)
        if item.available / per_minute <= SELLING_FAST_MINUTES:
            return "SELLING_FAST", None
    return None, None


def customer_menu(db: Session, restaurant_id: uuid.UUID) -> list[MenuItemPublic]:
    if db.get(Restaurant, restaurant_id) is None:
        raise NotFound("Restaurant not found")
    now = repo.db_now(db)
    out = []
    for item in repo.list_menu(db, restaurant_id):
        orderable = _is_orderable(item, now)
        badge, units_left = _badge(item, now) if orderable or item.available == 0 else (None, None)
        out.append(
            MenuItemPublic(
                id=item.id,
                name=item.name,
                description=item.description,
                price=item.price,
                is_veg=item.is_veg,
                orderable=orderable,
                badge=badge,
                units_left=units_left,
            )
        )
    return out


def restock_suggestion(db: Session, menu_item_id: uuid.UUID, lookback: int = 3) -> RestockSuggestion:
    """Suggest how many units to prepare next, from the last few closed cycles.

    The key idea is censored demand. If an item sold out, sales only tell us
    demand was AT LEAST that much: customers who came after the sell-out are
    invisible. So for sold-out cycles we estimate demand from the selling rate
    while the item was available, stretched over the whole cycle (capped, so one
    very early sell-out doesn't produce an absurd number).
    This is a teaching heuristic, not a production forecaster.
    """
    item = db.get(MenuItem, menu_item_id)
    if item is None:
        raise NotFound("Menu item not found")
    cycles = repo.recent_closed_cycles(db, menu_item_id, lookback)
    if not item.track_stock or not cycles:
        return RestockSuggestion(
            menu_item_id=menu_item_id,
            suggested_quantity=None,
            based_on_cycles=len(cycles),
            explanation=["Not enough closed cycles yet" if item.track_stock else "Item does not track stock"],
        )

    estimates, notes = [], []
    for c in cycles:
        net = (c.units_consumed or 0) - c.units_returned - c.units_wasted
        if c.sold_out_at is not None and c.closed_at is not None:
            total = (c.closed_at - c.started_at).total_seconds()
            selling = max((c.sold_out_at - c.started_at).total_seconds(), 1)
            factor = min(total / selling, MAX_DEMAND_EXTRAPOLATION)
            estimates.append(net * factor)
            notes.append(
                f"Cycle {c.cycle_no}: sold {net}, sold out early, so demand estimated at about {net * factor:.0f}"
            )
        else:
            estimates.append(net)
            notes.append(f"Cycle {c.cycle_no}: sold {net} of {c.units_stocked}, did not sell out")
    suggested = math.ceil(sum(estimates) / len(estimates))
    notes.append(f"Average of {len(estimates)} cycle estimates, rounded up: {suggested}")
    return RestockSuggestion(
        menu_item_id=menu_item_id, suggested_quantity=suggested, based_on_cycles=len(cycles), explanation=notes
    )
