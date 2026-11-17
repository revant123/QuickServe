"""Best-seller report, written twice: once with SQLAlchemy, once as raw SQL.

Both functions return identical rows (a test checks this). Read them side by
side: this is the clearest way to see what the ORM gives you and what it doesn't.

How "best seller" is decided
----------------------------
Counting units sold is misleading. A restaurant that prepares 200 samosas and
20 biryanis will always "sell more" samosas, even if biryani sold out by 1 pm
and samosas were left over at night.

So the report ranks by units sold per hour *while the item was on sale*.
For a cycle that sold out, the clock stops at sold_out_at, because after that
the item could not be bought; counting those hours would punish the item for
being popular. Each cycle counts for at least 15 minutes so one very early
sell-out cannot produce an absurd rate. Sell-through (sold / stocked) is
reported next to it, because it says whether we prepared too much or too little.
"""

import uuid
from datetime import datetime

from sqlalchemy import Float, Integer, case, cast, func, select, text
from sqlalchemy.orm import Session

from app.modules.menu.model import InventoryCycle, MenuItem

MIN_HOURS_PER_CYCLE = 0.25


def best_sellers_orm(db: Session, restaurant_id: uuid.UUID, since: datetime) -> list[dict]:
    return [dict(row._mapping) for row in db.execute(build_best_sellers_stmt(restaurant_id, since))]


def build_best_sellers_stmt(restaurant_id: uuid.UUID, since: datetime):
    c, m = InventoryCycle, MenuItem
    is_open = c.closed_at.is_(None)

    # Step 1: one row per cycle (a CTE). For the open cycle the live numbers
    # still sit on menu_items, so we pick them from there.
    sold_out = case((is_open, m.sold_out_at), else_=c.sold_out_at)
    consumed = case((is_open, m.consumed), else_=c.units_consumed)
    end_time = func.coalesce(sold_out, c.closed_at, func.now())
    hours = func.greatest(func.extract("epoch", end_time - c.started_at) / 3600.0, MIN_HOURS_PER_CYCLE)

    per_cycle = (
        select(
            m.id.label("menu_item_id"),
            m.name.label("name"),
            (consumed - c.units_returned - c.units_wasted).label("net_units"),
            c.units_stocked.label("units_stocked"),
            hours.label("hours"),
            sold_out.label("sold_out_at"),
        )
        .join(c, c.menu_item_id == m.id)
        .where(m.restaurant_id == restaurant_id, c.started_at >= since)
        .cte("per_cycle")
    )

    # Step 2: one row per item.
    pc = per_cycle.c
    units_sold = func.sum(pc.net_units)
    total_hours = func.sum(pc.hours)
    per_item = (
        select(
            pc.menu_item_id,
            pc.name,
            cast(units_sold, Integer).label("units_sold"),
            cast(func.sum(pc.units_stocked), Integer).label("units_stocked"),
            cast(total_hours, Float).label("hours_on_sale"),
            cast(units_sold / func.nullif(total_hours, 0), Float).label("units_per_hour"),
            cast(units_sold / func.nullif(func.sum(pc.units_stocked), 0).cast(Float), Float).label("sell_through"),
            func.count(pc.sold_out_at).label("sold_out_cycles"),
            func.count().label("cycles"),
        )
        .group_by(pc.menu_item_id, pc.name)
        .subquery("per_item")
    )

    # Step 3: rank with a window function.
    pi = per_item.c
    return select(
        pi,
        func.rank().over(order_by=(pi.units_per_hour.desc().nulls_last(), pi.units_sold.desc())).label("rank"),
    ).order_by(text("rank"), pi.name)


BEST_SELLERS_SQL = text(
    """
    WITH per_cycle AS (
        SELECT m.id   AS menu_item_id,
               m.name AS name,
               CASE WHEN c.closed_at IS NULL THEN m.consumed ELSE c.units_consumed END
                   - c.units_returned - c.units_wasted                         AS net_units,
               c.units_stocked                                                 AS units_stocked,
               GREATEST(
                   EXTRACT(EPOCH FROM COALESCE(
                       CASE WHEN c.closed_at IS NULL THEN m.sold_out_at ELSE c.sold_out_at END,
                       c.closed_at, now()) - c.started_at) / 3600.0,
                   :min_hours)                                                 AS hours,
               CASE WHEN c.closed_at IS NULL THEN m.sold_out_at ELSE c.sold_out_at END AS sold_out_at
          FROM menu_items m
          JOIN inventory_cycles c ON c.menu_item_id = m.id
         WHERE m.restaurant_id = :restaurant_id
           AND c.started_at >= :since
    ),
    per_item AS (
        SELECT menu_item_id,
               name,
               SUM(net_units)::int                                             AS units_sold,
               SUM(units_stocked)::int                                         AS units_stocked,
               SUM(hours)::float                                               AS hours_on_sale,
               (SUM(net_units) / NULLIF(SUM(hours), 0))::float                 AS units_per_hour,
               (SUM(net_units) / NULLIF(SUM(units_stocked), 0)::float)::float  AS sell_through,
               COUNT(sold_out_at)                                              AS sold_out_cycles,
               COUNT(*)                                                        AS cycles
          FROM per_cycle
         GROUP BY menu_item_id, name
    )
    SELECT *,
           RANK() OVER (ORDER BY units_per_hour DESC NULLS LAST, units_sold DESC) AS rank
      FROM per_item
     ORDER BY rank, name
    """
)


def best_sellers_sql(db: Session, restaurant_id: uuid.UUID, since: datetime) -> list[dict]:
    rows = db.execute(
        BEST_SELLERS_SQL, {"restaurant_id": restaurant_id, "since": since, "min_hours": MIN_HOURS_PER_CYCLE}
    )
    return [dict(row._mapping) for row in rows]
