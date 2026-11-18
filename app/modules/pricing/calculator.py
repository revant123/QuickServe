"""The bill: how much one order costs, line by line, like Zomato and Swiggy show it.

    item total            sum of (unit price x quantity)
  - coupon discount       percent (capped) or flat, on the food only
  + packaging charge      set by the restaurant
  + delivery fee          by road distance, in slabs; free for big orders nearby
  + small order fee       when the food is worth less than a threshold
  + surge fee             peak hours, late night, rain (they add up)
  + platform fee          flat, every order
  + GST on food           5% on food after discount + packaging
  + GST on fees           18% on delivery + small order + surge + platform
  = grand total

This module is PURE: numbers in, a bill out. No database, no clock, no HTTP.
The caller looks up the distance, the time and whether it's raining, and
passes them in. That makes every rule testable with plain values ("what does
an order of Rs 140, 5.2 km away, at 23:30 in the rain cost?"), and the same
function serves both the quote the customer sees and the order they place.

Illustrative only, not tax advice: real GST treatment of platform-funded
discounts, for example, is more involved than "reduce the food's value".
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from enum import StrEnum

from app.core.config import Settings
from app.core.exceptions import CouponRejected, NotServiceable
from app.core.money import rupees

ZERO = Decimal("0.00")


class CouponKind(StrEnum):
    PERCENT = "PERCENT"  # "50% off up to Rs 100"
    FLAT = "FLAT"  # "Rs 75 off"


@dataclass(frozen=True)
class CouponTerms:
    """Only what the arithmetic needs. Who may use it, and how often, is checked
    elsewhere (app/modules/coupons/service.py) because that needs the database."""

    code: str
    kind: CouponKind
    value: Decimal
    max_discount: Decimal | None = None
    min_order_value: Decimal = ZERO


@dataclass(frozen=True)
class Conditions:
    """Everything outside the cart that changes the price."""

    distance_km: Decimal  # road distance, restaurant -> customer
    local_time: time  # in settings.pricing_timezone
    raining: bool = False


@dataclass(frozen=True)
class BillLine:
    key: str
    label: str
    amount: Decimal
    note: str | None = None


@dataclass(frozen=True)
class Bill:
    item_total: Decimal
    discount: Decimal
    packaging_charge: Decimal
    delivery_fee: Decimal
    small_order_fee: Decimal
    surge_fee: Decimal
    platform_fee: Decimal
    gst_food: Decimal
    gst_fees: Decimal
    grand_total: Decimal
    distance_km: Decimal
    surge_reasons: tuple[str, ...] = ()
    coupon_code: str | None = None
    lines: tuple[BillLine, ...] = field(default=(), compare=False)


# ----- the rules, one function each -----


def parse_window(window: str) -> tuple[time, time]:
    """'19:00-22:00' -> (19:00, 22:00)."""
    start, end = window.split("-")
    return time.fromisoformat(start.strip()), time.fromisoformat(end.strip())


def in_window(t: time, window: str) -> bool:
    """Start included, end excluded. A window may cross midnight: '23:00-05:00'."""
    start, end = parse_window(window)
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def delivery_fee(item_total: Decimal, distance_km: Decimal, settings: Settings) -> tuple[Decimal, str]:
    slabs = sorted(settings.delivery_fee_slabs)
    slab = next(((up_to, fee) for up_to, fee in slabs if distance_km <= up_to), None)
    if slab is None:
        raise NotServiceable(f"We don't deliver beyond {slabs[-1][0]} km; this address is {distance_km} km away")
    up_to, fee = slab
    if item_total >= settings.free_delivery_above and distance_km <= settings.free_delivery_max_km:
        return (
            ZERO,
            f"{distance_km} km; free above Rs {settings.free_delivery_above} within {settings.free_delivery_max_km} km",
        )
    return rupees(fee), f"{distance_km} km (up to {up_to} km slab)"


def small_order_fee(item_total: Decimal, settings: Settings) -> Decimal:
    return rupees(settings.small_order_fee) if item_total < settings.small_order_below else ZERO


def surge(conditions: Conditions, settings: Settings) -> tuple[Decimal, tuple[str, ...]]:
    """Each reason adds its own fee: a rainy late night costs both."""
    reasons, fee = [], ZERO
    if any(in_window(conditions.local_time, w) for w in settings.peak_hours):
        reasons.append("peak")
        fee += settings.peak_fee
    if any(in_window(conditions.local_time, w) for w in settings.late_night_hours):
        reasons.append("late_night")
        fee += settings.late_night_fee
    if conditions.raining:
        reasons.append("rain")
        fee += settings.rain_fee
    return rupees(fee), tuple(reasons)


def coupon_discount(coupon: CouponTerms, item_total: Decimal) -> Decimal:
    """The discount on the food. Never more than the food itself costs."""
    if item_total < coupon.min_order_value:
        short = rupees(coupon.min_order_value - item_total)
        raise CouponRejected(f"{coupon.code} needs an order of Rs {coupon.min_order_value}; add Rs {short} more")
    if coupon.kind is CouponKind.PERCENT:
        amount = item_total * coupon.value / 100
        if coupon.max_discount is not None:
            amount = min(amount, coupon.max_discount)
    else:
        amount = coupon.value
    return rupees(min(amount, item_total))


# ----- the whole bill -----


def price(
    item_total: Decimal,
    packaging_charge: Decimal,
    conditions: Conditions,
    settings: Settings,
    coupon: CouponTerms | None = None,
) -> Bill:
    item_total = rupees(item_total)
    packaging = rupees(packaging_charge)
    # Fees are decided on the cart value BEFORE the discount: a coupon shouldn't
    # turn a free-delivery order into a paid one.
    delivery, delivery_note = delivery_fee(item_total, conditions.distance_km, settings)
    small = small_order_fee(item_total, settings)
    surge_fee, reasons = surge(conditions, settings)
    platform = rupees(settings.platform_fee)
    discount = coupon_discount(coupon, item_total) if coupon else ZERO

    # GST. A discount given at the time of sale and shown on the bill is not
    # part of the taxable value (CGST Act, Section 15(3)(a)), so the 5% is on
    # the food AFTER the discount.
    gst_food = rupees((item_total - discount + packaging) * settings.gst_rate_food)
    gst_fees = rupees((delivery + small + surge_fee + platform) * settings.gst_rate_fees)
    grand = item_total - discount + packaging + delivery + small + surge_fee + platform + gst_food + gst_fees

    lines: list[BillLine] = [BillLine("item_total", "Item total", item_total)]
    if discount:
        lines.append(BillLine("discount", f"Coupon {coupon.code}", -discount))
    optional: Sequence[tuple[str, str, Decimal, str | None]] = [
        ("packaging_charge", "Packaging (restaurant)", packaging, None),
        ("delivery_fee", "Delivery fee", delivery, delivery_note),
        ("small_order_fee", "Small order fee", small, f"orders below Rs {settings.small_order_below}"),
        ("surge_fee", "Surge fee", surge_fee, ", ".join(reasons) or None),
    ]
    for key, label, amount, note in optional:
        if amount or key == "delivery_fee":  # always show delivery, even when it's free
            lines.append(BillLine(key, label, amount, note))
    lines += [
        BillLine("platform_fee", "Platform fee", platform),
        BillLine("gst_food", f"GST on food ({settings.gst_rate_food:.0%})", gst_food),
        BillLine("gst_fees", f"GST on fees ({settings.gst_rate_fees:.0%})", gst_fees),
    ]
    return Bill(
        item_total=item_total,
        discount=discount,
        packaging_charge=packaging,
        delivery_fee=delivery,
        small_order_fee=small,
        surge_fee=surge_fee,
        platform_fee=platform,
        gst_food=gst_food,
        gst_fees=gst_fees,
        grand_total=rupees(grand),
        distance_km=conditions.distance_km,
        surge_reasons=reasons,
        coupon_code=coupon.code if coupon else None,
        lines=tuple(lines),
    )
