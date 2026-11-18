"""The pricing rules, as plain arithmetic: no database, no clock (Phase 11).

Every rule lives in app/modules/pricing/calculator.py as a pure function, so
each boundary ("Rs 148.99 pays the small order fee, Rs 149 doesn't") is a
one-line test.
"""

from datetime import UTC, datetime, time
from decimal import Decimal as D

import pytest

from app.core.config import Settings
from app.core.exceptions import CouponRejected, NotServiceable
from app.modules.pricing.calculator import (
    Conditions,
    CouponKind,
    CouponTerms,
    coupon_discount,
    delivery_fee,
    in_window,
    price,
    small_order_fee,
    surge,
)
from app.modules.pricing.geo import road_km, straight_line_km
from app.modules.pricing.service import local_time

# The production defaults, including the surge hours (conftest switches those
# off for the database tests; here we want them).
S = Settings(peak_hours=["19:00-22:00"], late_night_hours=["23:00-05:00"])
NOON = time(12, 0)
WELCOME50 = CouponTerms("WELCOME50", CouponKind.PERCENT, D("50"), max_discount=D("100"), min_order_value=D("149"))


def bill(item_total="400", km="1.0", at=NOON, raining=False, coupon=None, packaging="0"):
    return price(D(item_total), D(packaging), Conditions(D(km), at, raining), S, coupon)


# ----- distance -----


def test_straight_line_distance():
    # One degree of longitude on the equator is about 111.2 km.
    assert straight_line_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.1)
    # Sector 17 to Sector 22, Chandigarh.
    assert straight_line_km(30.7398, 76.7827, 30.7333, 76.7794) == pytest.approx(0.79, abs=0.01)


def test_road_distance_is_longer_than_the_straight_line():
    assert road_km(30.7398, 76.7827, 30.7333, 76.7794, D("1.25")) == D("1.0")


# ----- delivery fee slabs -----


@pytest.mark.parametrize(
    ("km", "fee"),
    [("0.3", "20.00"), ("2.0", "20.00"), ("2.1", "30.00"), ("4.0", "30.00"), ("5.9", "45.00"), ("8.0", "60.00")],
)
def test_delivery_fee_slabs(km, fee):
    assert delivery_fee(D("200"), D(km), S)[0] == D(fee)


def test_nobody_delivers_beyond_the_last_slab():
    with pytest.raises(NotServiceable, match="beyond 8 km"):
        delivery_fee(D("200"), D("8.1"), S)


@pytest.mark.parametrize(
    ("item_total", "km", "fee"),
    [
        ("299.00", "4.0", "0.00"),  # big enough, near enough: free
        ("298.99", "4.0", "30.00"),  # one paisa short
        ("299.00", "4.1", "45.00"),  # big enough, but too far for free delivery
    ],
)
def test_free_delivery_needs_a_big_order_nearby(item_total, km, fee):
    assert delivery_fee(D(item_total), D(km), S)[0] == D(fee)


# ----- small order fee -----


def test_small_order_fee_boundary():
    assert small_order_fee(D("148.99"), S) == D("15.00")
    assert small_order_fee(D("149.00"), S) == D("0.00")


# ----- surge -----


@pytest.mark.parametrize(
    ("t", "inside"),
    [(time(23, 0), True), (time(2, 30), True), (time(4, 59), True), (time(5, 0), False), (time(22, 59), False)],
)
def test_windows_can_cross_midnight(t, inside):
    assert in_window(t, "23:00-05:00") is inside


def test_peak_window_includes_start_excludes_end():
    assert in_window(time(19, 0), "19:00-22:00")
    assert not in_window(time(22, 0), "19:00-22:00")


@pytest.mark.parametrize(
    ("at", "raining", "fee", "reasons"),
    [
        (NOON, False, "0.00", ()),
        (time(20, 15), False, "10.00", ("peak",)),
        (time(23, 30), False, "15.00", ("late_night",)),
        (NOON, True, "25.00", ("rain",)),
        (time(23, 30), True, "40.00", ("late_night", "rain")),  # they add up
    ],
)
def test_surge_reasons_add_up(at, raining, fee, reasons):
    assert surge(Conditions(D("1"), at, raining), S) == (D(fee), reasons)


def test_surge_hours_are_indian_time():
    # 14:00 UTC is 19:30 in India: peak hour, although it's afternoon in UTC.
    assert local_time(datetime(2026, 11, 18, 14, 0, tzinfo=UTC), S) == time(19, 30)


# ----- coupons -----


def test_percent_coupon_is_capped():
    assert coupon_discount(WELCOME50, D("150")) == D("75.00")  # 50%
    assert coupon_discount(WELCOME50, D("600")) == D("100.00")  # capped


def test_flat_coupon_never_exceeds_the_food():
    flat = CouponTerms("FLAT75", CouponKind.FLAT, D("75"))
    assert coupon_discount(flat, D("300")) == D("75.00")
    assert coupon_discount(flat, D("60")) == D("60.00")


def test_coupon_minimum_order_says_how_much_more():
    with pytest.raises(CouponRejected, match="add Rs 9.00 more"):
        coupon_discount(WELCOME50, D("140"))


def test_discount_lowers_food_gst_but_not_the_fees():
    without = bill("400", coupon=None)
    with_coupon = bill("400", coupon=WELCOME50)
    assert with_coupon.discount == D("100.00")
    assert with_coupon.gst_food == D("15.00")  # 5% of 300, not of 400
    assert with_coupon.gst_fees == without.gst_fees


def test_a_coupon_doesnt_take_away_free_delivery():
    # 320 of food qualifies for free delivery; after 100 off it's 220, but the
    # fees are decided on the cart value before the discount.
    assert bill("320", coupon=WELCOME50).delivery_fee == D("0.00")


# ----- the whole bill -----


def test_a_rainy_late_night_order_line_by_line():
    b = bill("400", km="5.2", at=time(23, 30), raining=True, coupon=WELCOME50, packaging="20")
    assert b.discount == D("100.00")
    assert b.delivery_fee == D("45.00")  # 4-6 km slab; too far for free delivery
    assert b.small_order_fee == D("0.00")
    assert b.surge_fee == D("40.00")  # late night 15 + rain 25
    assert b.platform_fee == D("14.90")
    assert b.gst_food == D("16.00")  # 5% of (400 - 100 + 20)
    assert b.gst_fees == D("17.98")  # 18% of (45 + 40 + 14.90) = 17.982
    assert b.grand_total == D("453.88")
    # The lines add up to the total: what the customer sees is what they pay.
    assert sum(line.amount for line in b.lines) == b.grand_total
    assert [line.key for line in b.lines] == [
        "item_total",
        "discount",
        "packaging_charge",
        "delivery_fee",
        "surge_fee",
        "platform_fee",
        "gst_food",
        "gst_fees",
    ]


def test_a_small_lunch_pays_the_small_order_fee():
    b = bill("120")
    assert b.small_order_fee == D("15.00")
    assert b.grand_total == D("184.88")  # 120 + 20 + 15 + 14.90 + 6.00 + 18% of 49.90 (8.98)
    assert sum(line.amount for line in b.lines) == b.grand_total


def test_slabs_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv("DELIVERY_FEE_SLABS", "[[3, 25], [10, 50]]")
    s = Settings()
    assert delivery_fee(D("100"), D("9.5"), s)[0] == D("50.00")
