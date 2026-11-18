from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field


class RainRequest(BaseModel):
    # Long enough for a downpour, short enough that a forgotten switch turns itself off.
    minutes: int = Field(ge=5, le=720)


class RainOut(BaseModel):
    raining: bool
    until: datetime | None


class PricingInfo(BaseModel):
    """What the app shows on a "why am I paying this?" screen."""

    local_time: time
    surge_now: list[str]
    rain_until: datetime | None
    platform_fee: Decimal
    delivery_fee_slabs: list[tuple[Decimal, Decimal]]
    free_delivery_above: Decimal
    free_delivery_max_km: Decimal
    small_order_below: Decimal
    small_order_fee: Decimal
    peak_hours: list[str]
    peak_fee: Decimal
    late_night_hours: list[str]
    late_night_fee: Decimal
    rain_fee: Decimal


class BillLineOut(BaseModel):
    key: str
    label: str
    amount: Decimal
    note: str | None = Field(default=None)
