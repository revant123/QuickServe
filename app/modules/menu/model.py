"""Menu items and inventory cycles: the stock/consumed design.

QuickKart used one counter: stock -= 1 on every sale, stop at 0.
QuickServe keeps two numbers per item instead:

    stock     how many units were prepared for the current cycle (fixed during the cycle)
    consumed  how many of those units have been ordered so far
    available = stock - consumed

A "cycle" runs from one restock to the next. Restocking closes the current
cycle (its numbers are archived in inventory_cycles), starts a new one, sets
the new stock and resets consumed to 0.

The archive is the important part. If we reset consumed without saving it, the
data needed for best sellers, sell-through and demand forecasting would be lost
at every restock. See README: "The inventory design".
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    and_,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.modules.restaurants.model import Restaurant


class MenuItem(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "menu_items"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(String(500), default="")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    is_veg: Mapped[bool] = mapped_column(default=True)

    # Manual switch, like the "Out of Stock" toggle in restaurant partner apps.
    is_available: Mapped[bool] = mapped_column(default=True)
    # "Out of stock until 6 pm": the item comes back on its own after this time.
    unavailable_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Made-to-order items (a plain dosa, say) may not be counted. Their stock is
    # NULL, but we still count consumed so they appear in best-seller reports.
    track_stock: Mapped[bool] = mapped_column(default=True)
    stock: Mapped[int | None] = mapped_column(Integer)
    consumed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    cycle_no: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    cycle_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    # First moment in this cycle when available reached 0. Marks "censored" demand:
    # we know customers wanted more than we sold.
    sold_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Full-text search (Phase 12). A GENERATED column: PostgreSQL computes it from
    # name and description on every INSERT/UPDATE, so it can never be stale and
    # no application code has to remember to fill it. Words in the name weigh
    # more ('A') than words in the description ('B') when ranking.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', name), 'A') || setweight(to_tsvector('english', description), 'B')",
            persisted=True,
        ),
        deferred=True,  # never loaded unless asked for: nobody needs to read it
    )

    restaurant: Mapped["Restaurant"] = relationship(back_populates="menu_items", lazy="raise")
    cycles: Mapped[list["InventoryCycle"]] = relationship(
        back_populates="menu_item", lazy="raise", order_by="InventoryCycle.cycle_no"
    )

    __table_args__ = (
        # The database itself refuses to oversell, even if application code has a bug.
        # This is defence in depth: the service checks first, the database guarantees.
        CheckConstraint("consumed >= 0", name="consumed_non_negative"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint(
            "(track_stock AND stock IS NOT NULL AND stock >= 0 AND consumed <= stock)"
            " OR (NOT track_stock AND stock IS NULL)",
            name="stock_consistent",
        ),
        # GIN indexes for search. One for full-text (search_vector @@ query), one
        # of trigrams for ILIKE '%naan%' and typo-tolerant matching ("paner").
        Index("ix_menu_items_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_menu_items_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    @property
    def available(self) -> int | None:
        if not self.track_stock or self.stock is None:
            return None
        return self.stock - self.consumed

    # A hybrid method is one rule written for two worlds: called on an object it
    # runs as Python, called on the class it builds a SQL expression. The menu
    # page (Python) and the order UPDATE (SQL) can never disagree about whether
    # an item is switched on.
    #   on:              is_available AND unavailable_until IS NULL
    #   off until time:  unavailable_until is set; back on once that time passes
    #   off:             NOT is_available AND unavailable_until IS NULL
    @hybrid_method
    def switched_on_at(self, now: datetime) -> bool:
        if self.unavailable_until is not None:
            return self.unavailable_until <= now
        return self.is_available

    @switched_on_at.inplace.expression
    @classmethod
    def _switched_on_at_sql(cls, now):
        return or_(
            and_(cls.is_available.is_(True), cls.unavailable_until.is_(None)),
            cls.unavailable_until <= now,
        )


class InventoryCycle(UUIDPrimaryKey, Base):
    """One row per stock cycle. The open cycle's live counter is menu_items.consumed;
    when the cycle closes, the final numbers are copied here and never change again
    (except returns that arrive after the close)."""

    __tablename__ = "inventory_cycles"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id"), index=True)
    cycle_no: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    units_stocked: Mapped[int | None] = mapped_column(Integer)  # NULL for untracked items
    carried_in: Mapped[int] = mapped_column(Integer, default=0)  # leftover brought from the previous cycle
    units_consumed: Mapped[int | None] = mapped_column(Integer)  # filled when the cycle closes
    units_returned: Mapped[int] = mapped_column(Integer, default=0)  # cancellations that arrived after close
    units_wasted: Mapped[int] = mapped_column(Integer, default=0)  # cancelled after cooking started
    leftover: Mapped[int | None] = mapped_column(Integer)  # stock - consumed at close
    leftover_carried: Mapped[bool | None] = mapped_column()
    sold_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    menu_item: Mapped[MenuItem] = relationship(back_populates="cycles", lazy="raise")

    __table_args__ = (
        UniqueConstraint("menu_item_id", "cycle_no", name="uq_inventory_cycles_item_cycle"),
        # A partial unique index: at most ONE open cycle per item. A plain UNIQUE
        # on menu_item_id would allow only one cycle ever; the WHERE clause limits
        # the rule to rows that are still open.
        Index(
            "uq_inventory_cycles_one_open",
            "menu_item_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
    )
