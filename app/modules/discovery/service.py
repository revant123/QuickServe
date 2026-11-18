"""Restaurants near me, and search.

Both start the same way: which open restaurants deliver to this point?

1. SQL, with an index: the rectangle around the customer (geo.bounding_box).
   It's sized for the furthest anyone may deliver, so it can only contain
   too many restaurants, never too few.
2. Python: the exact road distance for each restaurant inside the rectangle,
   with the SAME function checkout uses (geo.road_km). If the list said
   "delivers to you" and checkout then said "too far", customers would stop
   trusting the list. One function means they can't disagree.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.metrics import SEARCHES
from app.modules.discovery.ranking import bayesian_rating, eta_minutes, eta_text
from app.modules.discovery.schema import DishHit, NearbyPage, RestaurantCard, SearchResult, SortBy
from app.modules.menu.model import MenuItem
from app.modules.menu.repository import db_now
from app.modules.pricing.calculator import ZERO, delivery_fee
from app.modules.pricing.geo import bounding_box, road_km
from app.modules.restaurants.model import Restaurant


@dataclass(frozen=True)
class Nearby:
    restaurant: Restaurant
    distance_km: Decimal
    eta_minutes: int


def platform_max_km(settings: Settings) -> Decimal:
    """Nobody delivers beyond the last delivery fee slab (Phase 11)."""
    return max(up_to for up_to, _fee in settings.delivery_fee_slabs)


def candidates_query(lat: float, lng: float, settings: Settings) -> Select:
    """Step 1, in SQL: open restaurants inside the rectangle."""
    # Road km / detour factor = the furthest a deliverable restaurant can be in
    # a straight line, which is what the rectangle is measured in.
    box = bounding_box(lat, lng, float(platform_max_km(settings) / settings.road_detour_factor))
    return select(Restaurant).where(
        Restaurant.is_open.is_(True),
        Restaurant.latitude.between(box.min_lat, box.max_lat),
        Restaurant.longitude.between(box.min_lng, box.max_lng),
    )


def nearby(db: Session, lat: float, lng: float, settings: Settings) -> list[Nearby]:
    """Every open restaurant that delivers to (lat, lng). Step 2 runs here, in Python."""
    limit_km = platform_max_km(settings)
    found = []
    for r in db.execute(candidates_query(lat, lng, settings)).scalars():
        distance = road_km(r.latitude, r.longitude, lat, lng, settings.road_detour_factor)
        if distance <= min(r.delivery_radius_km, limit_km):
            found.append(Nearby(r, distance, eta_minutes(r.avg_prep_minutes, distance, settings)))
    return found


def card(n: Nearby, settings: Settings) -> RestaurantCard:
    r = n.restaurant
    fee, _ = delivery_fee(ZERO, n.distance_km, settings)  # the fee for an order below the free-delivery line
    return RestaurantCard(
        id=r.id,
        name=r.name,
        address=r.address,
        cuisines=r.cuisine_list,
        distance_km=n.distance_km,
        eta_minutes=n.eta_minutes,
        eta_text=eta_text(n.eta_minutes),
        rating=r.rating,
        rating_count=r.rating_count,
        delivery_fee=fee,
        free_delivery_above=settings.free_delivery_above if n.distance_km <= settings.free_delivery_max_km else None,
        packaging_charge=r.packaging_charge,
    )


def platform_mean_rating(db: Session, settings: Settings) -> Decimal:
    """The m in the Bayesian average: the average of every rating on the platform.
    IMDb uses its site-wide mean the same way. Until anyone has rated, the setting."""
    total, count = db.execute(select(func.sum(Restaurant.rating_sum), func.sum(Restaurant.rating_count))).one()
    return Decimal(total) / Decimal(count) if count else settings.rating_prior_mean


def list_nearby(
    db: Session,
    lat: float,
    lng: float,
    sort: SortBy = SortBy.distance,
    cuisine: str | None = None,
    min_rating: Decimal | None = None,
    limit: int = 20,
    offset: int = 0,
    settings: Settings | None = None,
) -> NearbyPage:
    settings = settings or get_settings()
    places = nearby(db, lat, lng, settings)
    if cuisine:
        wanted = cuisine.strip().lower()
        places = [n for n in places if wanted in (c.lower() for c in n.restaurant.cuisine_list)]
    if min_rating is not None:
        # The filter uses the rating customers SEE: "4.0+" must not show a 3.9.
        places = [n for n in places if n.restaurant.rating is not None and n.restaurant.rating >= min_rating]

    if sort is SortBy.rating:
        mean = platform_mean_rating(db, settings)

        def key(n: Nearby):
            r = n.restaurant
            return (-bayesian_rating(r.rating_sum, r.rating_count, mean, settings.rating_prior_weight), n.distance_km)
    elif sort is SortBy.eta:

        def key(n: Nearby):
            return (n.eta_minutes, n.distance_km)
    else:

        def key(n: Nearby):
            return (n.distance_km, n.restaurant.name)

    # The sort runs in Python because distance depends on where THIS customer
    # stands: there's no column to ORDER BY. That's fine while a city block has
    # tens or hundreds of restaurants inside the rectangle. See the README for
    # what changes at Swiggy's scale.
    places.sort(key=key)
    return NearbyPage(total=len(places), restaurants=[card(n, settings) for n in places[offset : offset + limit]])


# ---------------- Search ----------------


def _like_pattern(q: str) -> str:
    # % and _ are wildcards in LIKE. Escape them, or searching "100%" matches everything.
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def dish_match(q: str, fuzzy: bool):
    """The WHERE clause for dishes, and a score to rank them by.

    exact: full-text search (words, with English stemming, so "momo" finds
           "Momos"), or the text appears anywhere in the name (ILIKE).
    fuzzy: trigram similarity, for typos. q <% name is true when q is close
           enough to some run of words in the name ("paner" ~ "Kadhai Paneer").
    GIN indexes serve all three operators (@@, ILIKE, <%).
    """
    tsquery = func.websearch_to_tsquery("english", q)
    score = func.ts_rank(MenuItem.search_vector, tsquery) + func.word_similarity(q, MenuItem.name)
    if fuzzy:
        return literal(q).op("<%")(MenuItem.name), score
    return or_(MenuItem.search_vector.op("@@")(tsquery), MenuItem.name.ilike(_like_pattern(q), escape="\\")), score


def restaurant_match(q: str, fuzzy: bool):
    if fuzzy:
        return or_(literal(q).op("<%")(Restaurant.name), literal(q).op("<%")(Restaurant.cuisines))
    pattern = _like_pattern(q)
    return or_(Restaurant.name.ilike(pattern, escape="\\"), Restaurant.cuisines.ilike(pattern, escape="\\"))


def _run(db: Session, q: str, places: dict[uuid.UUID, Nearby], fuzzy: bool, limit: int, now):
    ids = list(places)
    rest_where = restaurant_match(q, fuzzy)
    restaurant_ids = db.execute(select(Restaurant.id).where(Restaurant.id.in_(ids), rest_where)).scalars().all()

    dish_where, score = dish_match(q, fuzzy)
    dishes = (
        db.execute(
            select(MenuItem)
            .where(
                MenuItem.restaurant_id.in_(ids),
                dish_where,
                MenuItem.switched_on_at(now),
                # Hide dishes that are sold out right now: a search result you
                # can't order is worse than no result.
                or_(MenuItem.track_stock.is_(False), MenuItem.consumed < MenuItem.stock),
            )
            .order_by(score.desc(), MenuItem.price)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return restaurant_ids, dishes


def search(
    db: Session, q: str, lat: float, lng: float, limit: int = 20, settings: Settings | None = None
) -> SearchResult:
    """Dishes and restaurants matching q, only from restaurants that deliver to (lat, lng)."""
    settings = settings or get_settings()
    q = " ".join(q.split())  # trim and collapse spaces
    places = {n.restaurant.id: n for n in nearby(db, lat, lng, settings)}
    matched = "none"
    restaurant_ids, dishes = [], []
    if places:
        now = db_now(db)
        restaurant_ids, dishes = _run(db, q, places, fuzzy=False, limit=limit, now=now)
        if restaurant_ids or dishes:
            matched = "exact"
        else:
            # Nothing matched as typed: try again, tolerating typos. Done as a
            # second step (not always) because fuzzy matching also finds
            # near-misses: "chai" is 0.4 similar to "Butter Chicken".
            # set_config(..., true) changes the threshold for this transaction only.
            db.execute(
                select(func.set_config("pg_trgm.word_similarity_threshold", str(settings.search_fuzzy_threshold), True))
            )
            restaurant_ids, dishes = _run(db, q, places, fuzzy=True, limit=limit, now=now)
            if restaurant_ids or dishes:
                matched = "fuzzy"
    SEARCHES.labels(matched).inc()

    restaurants = sorted((places[i] for i in restaurant_ids), key=lambda n: n.distance_km)
    return SearchResult(
        query=q,
        matched=matched,
        restaurants=[card(n, settings) for n in restaurants],
        dishes=[
            DishHit(
                id=d.id,
                name=d.name,
                description=d.description,
                price=d.price,
                is_veg=d.is_veg,
                restaurant=card(places[d.restaurant_id], settings),
            )
            for d in dishes
        ],
    )
