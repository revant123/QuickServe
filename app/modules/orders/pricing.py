"""The bill, modelled on how Indian delivery apps itemise it.

    item total            sum of (unit price x quantity)
  + packaging charge      set by the restaurant
  + delivery fee          waived above a minimum order value
  + platform fee          flat, per order
  + GST on food           restaurant service through an e-commerce operator
  + GST on fees           the platform's own services (delivery + platform fee)
  = grand total

Rates and fees come from settings, never from constants in code: platforms
change them often, and tax rules change too. Illustrative only, not tax advice.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import Settings
from app.core.money import rupees


@dataclass(frozen=True)
class Bill:
    item_total: Decimal
    packaging_charge: Decimal
    delivery_fee: Decimal
    platform_fee: Decimal
    gst_food: Decimal
    gst_fees: Decimal
    grand_total: Decimal


def compute_bill(item_total: Decimal, packaging_charge: Decimal, settings: Settings) -> Bill:
    item_total = rupees(item_total)
    packaging = rupees(packaging_charge)
    delivery = Decimal("0.00") if item_total >= settings.free_delivery_above else rupees(settings.delivery_fee)
    platform = rupees(settings.platform_fee)
    gst_food = rupees((item_total + packaging) * settings.gst_rate_food)
    gst_fees = rupees((delivery + platform) * settings.gst_rate_fees)
    grand = item_total + packaging + delivery + platform + gst_food + gst_fees
    return Bill(item_total, packaging, delivery, platform, gst_food, gst_fees, rupees(grand))
