"""Phase 12: restaurants near me, delivery time, ranking by rating, and search."""

import math
import random
from decimal import Decimal

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.core.config import Settings, get_settings
from app.core.exceptions import NotServiceable
from app.modules.discovery import service
from app.modules.discovery.ranking import bayesian_rating, eta_minutes, eta_text
from app.modules.discovery.schema import SortBy
from app.modules.menu.model import MenuItem
from app.modules.menu.schema import MenuItemCreate
from app.modules.menu.service import create_menu_item
from app.modules.orders.schema import GeoPoint
from app.modules.orders.service import quote
from app.modules.pricing.geo import bounding_box, road_km, straight_line_km
from app.modules.restaurants.model import Restaurant
from app.modules.users.model import Role
from tests.conftest import SECTOR_22, TEST_PASSWORD
from tests.helpers import order_payload

HERE = (SECTOR_22["lat"], SECTOR_22["lng"])  # the customer, in Sector 22
KM_PER_DEG_LAT = 111.2  # one degree of latitude is about 111 km


@pytest.fixture
def place(db, owner):
    """A restaurant `km_north` km (straight line) north of the customer."""

    def _make(name, km_north, radius="7.0", cuisines="", prep=20, is_open=True, rating=(0, 0)):
        r = Restaurant(
            owner_id=owner.id,
            name=name,
            address=f"{name} address",
            latitude=Decimal(str(round(HERE[0] + km_north / KM_PER_DEG_LAT, 6))),
            longitude=Decimal(str(HERE[1])),
            delivery_radius_km=Decimal(radius),
            cuisines=cuisines,
            avg_prep_minutes=prep,
            is_open=is_open,
            rating_count=rating[0],
            rating_sum=rating[1],
        )
        db.add(r)
        db.commit()
        return r

    return _make


def dish(db, restaurant, owner, name, price="200.00", description="", stock=10):
    return create_menu_item(
        db,
        restaurant.id,
        MenuItemCreate(name=name, description=description, price=Decimal(price), stock=stock),
        owner,
    )


def names(page_or_list):
    items = page_or_list.restaurants if hasattr(page_or_list, "restaurants") else page_or_list
    return [c.name for c in items]


def explain(db, stmt) -> str:
    """EXPLAIN a SQLAlchemy query, with its parameters, on the session's connection."""
    compiled = stmt.compile(dialect=postgresql.psycopg.dialect())
    cursor = db.connection().connection.cursor()
    cursor.execute("EXPLAIN " + str(compiled), compiled.params)
    return "\n".join(row[0] for row in cursor.fetchall())


# ---------- The rectangle (pure) ----------


@pytest.mark.parametrize("lat", [0.0, 30.73, 60.0, -45.0])
def test_every_point_within_the_radius_is_inside_the_box(lat):
    rng = random.Random(42)
    box = bounding_box(lat, 76.78, 5.0)
    for _ in range(2000):
        # A random point up to 5 km away in a random direction.
        bearing, km = rng.uniform(0, 2 * math.pi), rng.uniform(0, 5.0)
        d = km / 6371.0088
        la1, lo1 = math.radians(lat), math.radians(76.78)
        la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(bearing))
        lo2 = lo1 + math.atan2(
            math.sin(bearing) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2)
        )
        p_lat, p_lng = math.degrees(la2), math.degrees(lo2)
        assert straight_line_km(lat, 76.78, p_lat, p_lng) <= 5.0 + 1e-9
        assert box.min_lat <= Decimal(str(p_lat)) <= box.max_lat
        assert box.min_lng <= Decimal(str(p_lng)) <= box.max_lng


def test_the_box_is_wider_in_degrees_away_from_the_equator():
    def width(lat):
        b = bounding_box(lat, 10.0, 5.0)
        return b.max_lng - b.min_lng

    height = bounding_box(0.0, 10.0, 5.0)
    assert height.max_lat - height.min_lat == pytest.approx(Decimal("0.09"), abs=Decimal("0.001"))
    # 1 / cos(60 degrees) = 2: twice as many degrees of longitude for the same 5 km.
    assert width(60.0) / width(0.0) == pytest.approx(Decimal("2"), rel=Decimal("0.01"))


def test_near_a_pole_or_the_date_line_every_longitude_is_searched():
    polar = bounding_box(89.99, 0.0, 5.0)
    assert (polar.min_lng, polar.max_lng, polar.max_lat) == (Decimal("-180"), Decimal("180"), Decimal("90"))
    fiji = bounding_box(-17.7, 179.99, 5.0)
    assert (fiji.min_lng, fiji.max_lng) == (Decimal("-180"), Decimal("180"))


# ---------- Delivery time and rating score (pure) ----------


def test_eta_is_the_slower_of_cooking_and_fetching_the_rider_plus_the_ride():
    s = Settings()  # first mile 8 min, 20 km/h, handoff 4 min
    # The kitchen is slower: 20 min prep, then 3 km = 9 min ride, then 4 min.
    assert eta_minutes(20, Decimal("3.0"), s) == 20 + 9 + 4
    # A 5-minute kitchen still waits 8 minutes for a rider to arrive.
    assert eta_minutes(5, Decimal("3.0"), s) == 8 + 9 + 4
    assert eta_text(33) == "30-35 min" and eta_text(30) == "30-35 min"


def test_one_five_star_review_does_not_beat_four_hundred_good_ones():
    m, c = Decimal("4.0"), 10
    newcomer = bayesian_rating(5, 1, m, c)  # plain average 5.0
    favourite = bayesian_rating(1840, 400, m, c)  # plain average 4.6
    assert newcomer == pytest.approx(Decimal("4.09"), abs=Decimal("0.01"))
    assert favourite > newcomer
    # With no reviews at all, a restaurant sits exactly at the platform average.
    assert bayesian_rating(0, 0, m, c) == m


# ---------- Near me ----------


def test_lists_only_open_restaurants_that_deliver_here_nearest_first(db, place, owner):
    place("Two Km", 2.0)
    place("Near", 1.2)
    place("Closed", 0.5, is_open=False)
    place("Small Radius", 3.0, radius="3.0")  # 3.75 km by road: beyond its own 3 km
    place("Beyond Platform", 6.8, radius="10.0")  # 8.5 km by road: past the last fee slab (8 km)
    place("Far Away", 30.0)  # outside the rectangle: never even read
    db.add(Restaurant(owner_id=owner.id, name="Nowhere", address="Before Phase 11: no location"))
    db.commit()

    page = service.list_nearby(db, *HERE)
    assert names(page) == ["Near", "Two Km"]
    assert page.total == 2
    first = page.restaurants[0]
    assert first.distance_km == Decimal("1.5")  # 1.2 km straight line x 1.25
    assert first.delivery_fee == Decimal("20.00") and first.free_delivery_above == Decimal("299.00")
    # 20 min cooking + 1.5 km at 20 km/h (4.5, so 5 min) + 4 min handing over
    assert first.eta_minutes == 29 and first.eta_text == "25-30 min"
    assert first.rating is None and first.rating_count == 0  # "New"


def test_the_list_and_checkout_never_disagree(db, place, owner, customer):
    """Every restaurant the list shows can be quoted, at the same distance. And the
    one just past the edge is refused by both."""
    # 6.39 km straight is 7.99 by road, right at the 8 km edge.
    for i, km in enumerate([0.5, 1.7, 3.3, 4.9, 6.39]):
        r = place(f"R{i}", km, radius="10.0")
        dish(db, r, owner, f"Thali {i}")
    listed = {c.id: c.distance_km for c in service.list_nearby(db, *HERE).restaurants}
    assert len(listed) == 5
    for r in db.execute(select(Restaurant)).scalars():
        item = db.execute(select(MenuItem).where(MenuItem.restaurant_id == r.id)).scalar_one()
        bill, _ = quote(db, order_payload(r, (item, 1), location=GeoPoint(lat=HERE[0], lng=HERE[1])), customer)
        assert bill.distance_km == listed[r.id]
    edge = place("Just Too Far", 6.45, radius="10.0")  # 8.06 km by road
    item = dish(db, edge, owner, "Thali edge")
    assert edge.id not in {c.id for c in service.list_nearby(db, *HERE).restaurants}
    with pytest.raises(NotServiceable):
        quote(db, order_payload(edge, (item, 1), location=GeoPoint(lat=HERE[0], lng=HERE[1])), customer)


def test_the_rectangle_is_cut_with_the_location_index(db, place):
    place("Somewhere", 1.0)
    query = service.candidates_query(*HERE, get_settings())
    # A handful of rows is cheaper to scan than to index, so the planner would
    # rightly pick a table scan here. Forbidding it shows the index CAN serve the query.
    db.execute(text("SET LOCAL enable_seqscan = off"))
    plan = explain(db, query)
    assert "ix_restaurants_location" in plan, plan
    db.rollback()


def test_sort_by_rating_uses_the_bayesian_score(db, place):
    place("One Lucky Review", 1.0, rating=(1, 5))
    place("Crowd Favourite", 2.0, rating=(400, 1840))  # 4.6 average
    place("Mediocre", 0.5, rating=(50, 160))  # 3.2 average
    page = service.list_nearby(db, *HERE, sort=SortBy.rating)
    assert names(page) == ["Crowd Favourite", "One Lucky Review", "Mediocre"]
    # What customers SEE is still the plain average; "New" below 3 reviews.
    ratings = {c.name: c.rating for c in page.restaurants}
    assert ratings == {"Crowd Favourite": Decimal("4.6"), "One Lucky Review": None, "Mediocre": Decimal("3.2")}


def test_sort_by_eta_and_filters(db, place):
    place("Slow Kitchen Nearby", 0.5, prep=45, cuisines="North Indian, Mughlai", rating=(10, 45))
    place("Fast Kitchen Further", 3.0, prep=10, cuisines="South Indian", rating=(10, 38))
    assert names(service.list_nearby(db, *HERE, sort=SortBy.eta)) == ["Fast Kitchen Further", "Slow Kitchen Nearby"]
    assert names(service.list_nearby(db, *HERE, cuisine="south indian")) == ["Fast Kitchen Further"]
    assert names(service.list_nearby(db, *HERE, cuisine="Indian")) == []  # whole cuisine names only
    assert names(service.list_nearby(db, *HERE, min_rating=Decimal("4.0"))) == ["Slow Kitchen Nearby"]


def test_pagination(db, place):
    for i in range(5):
        place(f"P{i}", 0.5 + i * 0.5)
    page = service.list_nearby(db, *HERE, limit=2, offset=2)
    assert page.total == 5 and names(page) == ["P2", "P3"]


# ---------- Search ----------


@pytest.fixture
def menu(db, place, owner):
    dhaba = place("Punjabi Tadka", 1.0, cuisines="North Indian, Punjabi")
    dosa = place("Dosa Junction", 2.0, cuisines="South Indian")
    far = place("Far Dhaba", 20.0, cuisines="North Indian")
    dish(db, dhaba, owner, "Kadhai Paneer", "300.00", "Paneer and capsicum in a spicy masala")
    dish(db, dhaba, owner, "Paneer Tikka", "280.00")
    dish(db, dhaba, owner, "Butter Chicken", "380.00", "Creamy tomato gravy")
    dish(db, dhaba, owner, "Chicken Biryani", "320.00")
    dish(db, dosa, owner, "Masala Dosa", "150.00", "With sambar and coconut chutney")
    dish(db, dosa, owner, "Filter Coffee", "60.00")
    dish(db, dosa, owner, "Masala Chai", "40.00")
    dish(db, far, owner, "Shahi Paneer", "290.00")  # too far to deliver here
    return dhaba, dosa


def search(db, q):
    return service.search(db, q, *HERE)


def test_search_finds_dishes_by_name_and_description(db, menu):
    result = search(db, "paneer")
    assert result.matched == "exact"
    found = [d.name for d in result.dishes]
    # Name matches rank above description matches; Shahi Paneer is too far away.
    assert found[:2] in (["Kadhai Paneer", "Paneer Tikka"], ["Paneer Tikka", "Kadhai Paneer"])
    assert "Shahi Paneer" not in found
    assert result.dishes[0].restaurant.name == "Punjabi Tadka"
    assert [d.name for d in search(db, "coconut").dishes] == ["Masala Dosa"]  # in the description
    assert [d.name for d in search(db, "biryanis").dishes] == ["Chicken Biryani"]  # English stemming


@pytest.mark.parametrize(
    ("typo", "expected"),
    [("paner", "Paneer"), ("biriyani", "Chicken Biryani"), ("chiken", "Chicken"), ("dosaa", "Masala Dosa")],
)
def test_typos_fall_back_to_fuzzy_matching(db, menu, typo, expected):
    result = search(db, typo)
    assert result.matched == "fuzzy"
    assert any(expected in d.name for d in result.dishes)


def test_exact_matches_skip_the_fuzzy_step(db, menu):
    # "chai" is 0.4 similar to "Butter Chicken": only acceptable when nothing better exists.
    result = search(db, "chai")
    assert result.matched == "exact"
    assert [d.name for d in result.dishes] == ["Masala Chai"]


def test_search_finds_restaurants_by_name_or_cuisine(db, menu):
    assert [r.name for r in search(db, "south indian").restaurants] == ["Dosa Junction"]
    assert [r.name for r in search(db, "tadka").restaurants] == ["Punjabi Tadka"]
    # Far Dhaba is North Indian too, but doesn't deliver here.
    assert [r.name for r in search(db, "north indian").restaurants] == ["Punjabi Tadka"]


def test_sold_out_and_switched_off_dishes_are_hidden(db, menu, owner):
    dhaba, _ = menu
    sold_out = dish(db, dhaba, owner, "Paneer Butter Masala", stock=0)
    off = dish(db, dhaba, owner, "Paneer Bhurji")
    off.is_available = False
    db.commit()
    found = [d.name for d in search(db, "paneer").dishes]
    assert sold_out.name not in found and off.name not in found


def test_like_wildcards_in_the_query_are_just_characters(db, menu):
    result = search(db, "%%")
    assert result.matched == "none" and result.dishes == []


def test_nothing_found_is_counted(db, menu):
    before = REGISTRY.get_sample_value("quickserve_searches_total", {"outcome": "none"}) or 0
    assert search(db, "pizza").matched == "none"
    assert REGISTRY.get_sample_value("quickserve_searches_total", {"outcome": "none"}) == before + 1


def test_search_queries_can_use_the_gin_indexes(db, menu):
    db.execute(text("SET LOCAL enable_seqscan = off"))
    for fuzzy, index in [
        (False, "ix_menu_items_search_vector"),
        (False, "ix_menu_items_name_trgm"),
        (True, "ix_menu_items_name_trgm"),
    ]:
        where, _ = service.dish_match("paneer", fuzzy)
        plan = explain(db, select(MenuItem.id).where(where))
        assert index in plan, plan
    db.rollback()


# ---------- HTTP ----------


def test_discovery_endpoints(client, menu):
    r = client.get("/api/v1/restaurants/near", params={"lat": HERE[0], "lng": HERE[1], "sort": "eta"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["restaurants"][0]["cuisines"] in (["North Indian", "Punjabi"], ["South Indian"])

    r = client.get("/api/v1/search", params={"q": "paner", "lat": HERE[0], "lng": HERE[1]})
    assert r.status_code == 200 and r.json()["matched"] == "fuzzy"

    assert client.get("/api/v1/restaurants/near", params={"lat": 100, "lng": 0}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "a", "lat": 0, "lng": 0}).status_code == 422


def login(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_owners_set_cuisines_and_prep_time(client, owner, make_user, restaurant):
    url = f"/api/v1/restaurants/{restaurant.id}/profile"
    body = {"cuisines": [" North  Indian ", "Punjabi", "north indian"], "avg_prep_minutes": 25}
    r = client.put(url, json=body, headers=login(client, owner.email))
    assert r.status_code == 200, r.text
    assert r.json()["cuisines"] == ["North Indian", "Punjabi"]  # tidied, duplicates dropped
    assert r.json()["avg_prep_minutes"] == 25

    other = make_user(Role.RESTAURANT_OWNER)
    assert client.put(url, json=body, headers=login(client, other.email)).status_code == 403
    bad = {"cuisines": ["Indian, Chinese"], "avg_prep_minutes": 25}
    assert client.put(url, json=bad, headers=login(client, owner.email)).status_code == 422


def test_road_km_and_the_listing_use_the_same_rounding():
    # Guard for the "never disagree" promise: both go through geo.road_km.
    assert road_km(30.7333, 76.7794, 30.7423, 76.7794, Decimal("1.25")) == Decimal("1.3")
