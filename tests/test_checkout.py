"""Checkout with real money rules (Phase 11): quotes, coupons, surge, delivery areas.

Real PostgreSQL, real transactions, and real threads for the races: two
customers grabbing the last use of a coupon must not both get it.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.exceptions import CouponRejected, Forbidden, NotServiceable, PriceChanged, Unprocessable
from app.database.session import SessionLocal
from app.modules.coupons import service as coupons
from app.modules.coupons.model import Coupon, CouponFunder, CouponRedemption, RedemptionStatus
from app.modules.coupons.schema import CouponCreate
from app.modules.menu.repository import db_now
from app.modules.orders.model import Order
from app.modules.orders.model import OrderStatus as S
from app.modules.orders.schema import GeoPoint
from app.modules.orders.service import cancel, change_status, place_order, quote
from app.modules.pricing import service as pricing
from app.modules.pricing.calculator import CouponKind
from app.modules.restaurants.model import Restaurant
from tests.helpers import order_payload

FAR = GeoPoint(lat=30.70, lng=76.70)  # about 11 km by road from Sector 17: outside every slab


@pytest.fixture
def make_coupon(db, admin):
    def _make(code="WELCOME50", **overrides):
        fields = dict(
            code=code,
            description="50% off up to Rs 100",
            kind=CouponKind.PERCENT,
            value=D("50"),
            max_discount=D("100"),
            min_order_value=D("149"),
        )
        fields.update(overrides)
        return coupons.create_coupon(db, CouponCreate(**fields), admin)

    return _make


def _refresh(db, obj):
    db.expire_all()
    return db.get(type(obj), obj.id)


# ----- coupons on real orders -----


def test_order_with_a_coupon_stores_the_discount_and_one_use(db, restaurant, customer, make_item, make_coupon):
    coupon = make_coupon()
    item = make_item(price="150.00", stock=10)
    order = place_order(db, order_payload(restaurant, (item, 2), coupon="welcome50"), customer)  # any case

    assert order.coupon_code == "WELCOME50"
    assert order.discount == D("100.00")  # 50% of 300 = 150, capped at 100
    assert order.gst_food == D("11.00")  # 5% of (300 - 100 + 20 packaging)
    assert _refresh(db, coupon).times_used == 1
    redemption = db.execute(select(CouponRedemption)).scalar_one()
    assert redemption.order_id == order.id and redemption.status is RedemptionStatus.APPLIED


def test_a_rejected_coupon_rolls_back_the_whole_order(db, restaurant, customer, make_item, make_coupon):
    make_coupon(min_order_value=D("500"))
    item = make_item(price="150.00", stock=10)
    with pytest.raises(CouponRejected, match="add Rs 200.00 more"):
        place_order(db, order_payload(restaurant, (item, 2), coupon="WELCOME50"), customer)
    db.rollback()
    assert db.execute(select(func.count()).select_from(Order)).scalar_one() == 0
    assert _refresh(db, item).available == 10  # the reserved stock went back


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"valid_until": "past"}, "has expired"),
        ({"restaurant_id": "other"}, "different restaurant"),
        ({"max_uses_total": 1, "used": 1}, "fully used"),
    ],
)
def test_coupon_rules(db, restaurant, customer, owner, make_item, make_coupon, overrides, message):
    if overrides.get("valid_until") == "past":
        overrides["valid_until"] = db_now(db) - timedelta(minutes=1)
    if overrides.get("restaurant_id") == "other":
        other = Restaurant(owner_id=owner.id, name="Other", address="Sector 9", latitude=D("30.7"), longitude=D("76.8"))
        db.add(other)
        db.commit()
        overrides["restaurant_id"] = other.id
    used = overrides.pop("used", 0)
    coupon = make_coupon(**overrides)
    if used:
        coupon.times_used = used
        db.commit()
    item = make_item(price="200.00", stock=10)
    with pytest.raises(CouponRejected, match=message):
        place_order(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)


def test_unknown_coupon(db, restaurant, customer, make_item):
    item = make_item(price="200.00", stock=10)
    with pytest.raises(CouponRejected, match="isn't a valid coupon"):
        place_order(db, order_payload(restaurant, (item, 1), coupon="NOPE"), customer)


def test_one_use_per_customer_and_a_failed_order_gives_it_back(db, restaurant, customer, make_item, make_coupon):
    coupon = make_coupon(first_order_only=False)
    item = make_item(price="200.00", stock=10)
    first = place_order(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)
    with pytest.raises(CouponRejected, match="already used"):
        place_order(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)
    db.rollback()

    cancel(db, first.id, customer, "changed my mind")  # the order fails...
    assert _refresh(db, coupon).times_used == 0  # ...and the use comes back
    again = place_order(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)
    assert again.discount == D("100.00")


def test_first_order_only(db, restaurant, customer, make_item, make_coupon):
    make_coupon(first_order_only=True)
    item = make_item(price="200.00", stock=10)
    place_order(db, order_payload(restaurant, (item, 1)), customer)  # an ordinary first order
    with pytest.raises(CouponRejected, match="only for your first order"):
        place_order(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)


def test_a_cancelled_order_doesnt_count_as_a_first_order(db, restaurant, customer, make_item, make_coupon):
    make_coupon(first_order_only=True)
    item = make_item(price="200.00", stock=10)
    earlier = place_order(db, order_payload(restaurant, (item, 1)), customer)
    cancel(db, earlier.id, customer, "wrong address")
    order = place_order(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)
    assert order.discount == D("100.00")


def test_rejected_by_the_restaurant_releases_the_coupon(db, restaurant, customer, owner, make_item, make_coupon):
    from app.modules.payments.schema import SimulatedOutcome
    from app.modules.payments.service import pay

    coupon = make_coupon()
    item = make_item(price="200.00", stock=10)
    order = place_order(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)
    pay(db, order.id, f"key-{order.id}", SimulatedOutcome.success, customer)
    change_status(db, order.id, S.REJECTED, owner, "kitchen closed")
    assert _refresh(db, coupon).times_used == 0
    assert db.execute(select(CouponRedemption.status)).scalar_one() is RedemptionStatus.RELEASED


# ----- races -----


def _run_concurrently(n, fn):
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def test_twenty_customers_race_for_five_coupon_uses(db, restaurant, make_user, make_item, make_coupon):
    coupon = make_coupon(max_uses_total=5)
    item = make_item(price="200.00", stock=100)
    customers = [make_user() for _ in range(20)]

    def try_order(i):
        session = SessionLocal()
        try:
            place_order(session, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customers[i])
            return "ok"
        except CouponRejected:
            return "rejected"
        finally:
            session.close()

    results = _run_concurrently(20, try_order)
    assert results.count("ok") == 5
    assert results.count("rejected") == 15
    assert _refresh(db, coupon).times_used == 5
    assert db.execute(select(func.count()).select_from(CouponRedemption)).scalar_one() == 5


def test_one_customer_double_tapping_gets_the_coupon_once(db, restaurant, customer, make_item, make_coupon):
    coupon = make_coupon(max_uses_per_user=1)
    item = make_item(price="200.00", stock=100)

    def try_order(_):
        session = SessionLocal()
        try:
            place_order(session, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)
            return "ok"
        except CouponRejected:
            return "rejected"
        finally:
            session.close()

    results = _run_concurrently(8, try_order)
    assert results.count("ok") == 1
    assert _refresh(db, coupon).times_used == 1


# ----- quotes and price changes -----


def test_the_quote_matches_the_order_and_reserves_nothing(db, restaurant, customer, make_item, make_coupon):
    coupon = make_coupon()
    item = make_item(price="150.00", stock=10)
    payload = order_payload(restaurant, (item, 2), coupon="WELCOME50")
    bill, coupon_error = quote(db, payload, customer)
    assert coupon_error is None
    assert _refresh(db, item).available == 10 and _refresh(db, coupon).times_used == 0

    order = place_order(db, payload.model_copy(update={"expected_total": bill.grand_total}), customer)
    assert order.grand_total == bill.grand_total


def test_a_bad_coupon_doesnt_fail_the_quote(db, restaurant, customer, make_item, make_coupon):
    make_coupon(min_order_value=D("1000"))
    item = make_item(price="150.00", stock=10)
    bill, coupon_error = quote(db, order_payload(restaurant, (item, 1), coupon="WELCOME50"), customer)
    assert "add Rs 850.00 more" in coupon_error
    assert bill.discount == D("0.00") and bill.coupon_code is None


def test_order_refused_when_the_price_changed_since_the_quote(db, restaurant, customer, make_item, admin):
    item = make_item(price="200.00", stock=10)
    payload = order_payload(restaurant, (item, 1))
    seen, _ = quote(db, payload, customer)

    pricing.set_rain(db, 60, admin)  # it starts raining before the customer taps "Pay"

    with pytest.raises(PriceChanged) as exc:
        place_order(db, payload.model_copy(update={"expected_total": seen.grand_total}), customer)
    assert D(exc.value.extra["new_grand_total"]) == seen.grand_total + D("25.00") + D("4.50")  # rain fee + its 18% GST
    db.rollback()
    assert _refresh(db, item).available == 10


# ----- surge and delivery areas -----


def test_rain_switch_adds_the_rain_fee_until_switched_off(db, restaurant, customer, make_item, admin):
    item = make_item(price="200.00", stock=10)
    pricing.set_rain(db, 30, admin)
    rainy = place_order(db, order_payload(restaurant, (item, 1)), customer)
    assert (rainy.surge_fee, rainy.surge_reasons) == (D("25.00"), "rain")

    pricing.stop_rain(db, admin)
    dry = place_order(db, order_payload(restaurant, (item, 1)), customer)
    assert (dry.surge_fee, dry.surge_reasons) == (D("0.00"), None)


def test_peak_hours_from_settings(db, restaurant, customer, make_item):
    always_peak = Settings(peak_hours=["00:00-12:00", "12:00-00:00"], late_night_hours=[])
    item = make_item(price="200.00", stock=10)
    order = place_order(db, order_payload(restaurant, (item, 1)), customer, always_peak)
    assert (order.surge_fee, order.surge_reasons) == (D("10.00"), "peak")


def test_too_far_away(db, restaurant, customer, make_item):
    item = make_item(price="200.00", stock=10)
    with pytest.raises(NotServiceable, match="delivers up to 7.0 km"):
        place_order(db, order_payload(restaurant, (item, 1), location=FAR), customer)
    db.rollback()
    assert _refresh(db, item).available == 10


def test_restaurant_without_a_location_cant_take_orders(db, restaurant, customer, make_item):
    item = make_item(price="200.00", stock=10)
    restaurant.latitude = restaurant.longitude = None
    db.commit()
    with pytest.raises(Unprocessable, match="hasn't set its location"):
        place_order(db, order_payload(restaurant, (item, 1)), customer)


# ----- who may create coupons -----


def test_owners_fund_their_own_coupons_only(db, restaurant, owner, make_user, customer):
    from app.modules.users.model import Role

    data = dict(code="PALDHABA20", description="Rs 20 off", kind=CouponKind.FLAT, value=D("20"))
    mine = coupons.create_coupon(db, CouponCreate(**data, restaurant_id=restaurant.id), owner)
    assert mine.funded_by is CouponFunder.RESTAURANT

    other_owner = make_user(Role.RESTAURANT_OWNER)
    with pytest.raises(Forbidden):
        coupons.create_coupon(db, CouponCreate(**{**data, "code": "X1X"}, restaurant_id=restaurant.id), other_owner)
    with pytest.raises(Forbidden):
        coupons.create_coupon(db, CouponCreate(**{**data, "code": "X2X"}), owner)  # platform-wide: not theirs
    with pytest.raises(Forbidden):
        coupons.create_coupon(db, CouponCreate(**{**data, "code": "X3X"}), customer)


# ----- the HTTP side -----


def _login(client, email):
    from tests.conftest import TEST_PASSWORD

    r = client.post("/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_quote_and_order_over_http(client, db, restaurant, customer, admin, make_item):
    item = make_item(price="120.00", stock=10)
    cust = _login(client, customer.email)
    body = {
        "restaurant_id": str(restaurant.id),
        "delivery_address": "House 12, Sector 22",
        "delivery_location": {"lat": 30.7333, "lng": 76.7794},
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "coupon_code": "GONE",
    }
    q = client.post("/api/v1/orders/quote", json=body, headers=cust)
    assert q.status_code == 200, q.text
    q = q.json()
    assert q["coupon_error"] == "GONE isn't a valid coupon"
    assert [line["key"] for line in q["lines"]] == [
        "item_total",
        "packaging_charge",
        "delivery_fee",
        "small_order_fee",
        "platform_fee",
        "gst_food",
        "gst_fees",
    ]
    assert sum(D(line["amount"]) for line in q["lines"]) == D(q["grand_total"])

    body.pop("coupon_code")
    wrong = client.post("/api/v1/orders", json={**body, "expected_total": "1.00"}, headers=cust)
    assert wrong.status_code == 409 and wrong.json()["new_grand_total"] == q["grand_total"]
    ok = client.post("/api/v1/orders", json={**body, "expected_total": q["grand_total"]}, headers=cust)
    assert ok.status_code == 201 and ok.json()["small_order_fee"] == "15.00"

    far = client.post(
        "/api/v1/orders/quote", json={**body, "delivery_location": {"lat": 30.7, "lng": 76.7}}, headers=cust
    )
    assert far.status_code == 422 and "delivers up to" in far.json()["detail"]


def test_rain_switch_is_admin_only_and_shows_in_pricing_info(client, customer, admin):
    assert (
        client.put("/api/v1/admin/surge/rain", json={"minutes": 60}, headers=_login(client, customer.email)).status_code
        == 403
    )
    r = client.put("/api/v1/admin/surge/rain", json={"minutes": 60}, headers=_login(client, admin.email))
    assert r.status_code == 200 and r.json()["raining"] is True
    info = client.get("/api/v1/pricing").json()
    assert "rain" in info["surge_now"] and info["platform_fee"] == "14.90"


def test_public_coupon_list(client, db, restaurant, make_coupon):
    make_coupon()
    make_coupon("OLD", valid_until=db_now(db) - timedelta(days=1))
    codes = [c["code"] for c in client.get(f"/api/v1/coupons?restaurant_id={restaurant.id}").json()]
    assert codes == ["WELCOME50"]


def test_duplicate_coupon_code(db, make_coupon):
    from app.core.exceptions import Conflict

    make_coupon()
    with pytest.raises(Conflict, match="already exists"):
        make_coupon("welcome50")
    assert db.execute(select(func.count()).select_from(Coupon)).scalar_one() == 1
