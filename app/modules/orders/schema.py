import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.model import OrderStatus
from app.modules.pricing.schema import BillLineOut


class OrderLineIn(BaseModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(gt=0, le=50)


class GeoPoint(BaseModel):
    # A pin on the map. Real apps get it from the phone's GPS or a map picker;
    # the typed address is for the rider, the coordinates are for the maths.
    lat: float = Field(ge=-90, le=90, examples=[30.7333])
    lng: float = Field(ge=-180, le=180, examples=[76.7794])


class OrderCreate(BaseModel):
    # No customer_id: the order belongs to whoever is logged in.
    restaurant_id: uuid.UUID
    delivery_address: str = Field(min_length=5, max_length=500)
    delivery_location: GeoPoint
    items: list[OrderLineIn] = Field(min_length=1, max_length=30)
    coupon_code: str | None = Field(default=None, max_length=30)
    # The grand total the customer saw in the quote. If the price has changed
    # since (surge started, the coupon ran out), the order is refused with 409
    # and the new total, instead of charging an amount they never agreed to.
    expected_total: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class StatusUpdate(BaseModel):
    # No "actor" field any more: who you are comes from your login token, so
    # nobody can claim to be "the restaurant" just by typing it.
    status: OrderStatus
    note: str | None = Field(default=None, max_length=300)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_item_id: uuid.UUID
    item_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal
    cycle_no: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    restaurant_id: uuid.UUID
    status: OrderStatus
    delivery_address: str
    item_total: Decimal
    packaging_charge: Decimal
    delivery_fee: Decimal
    platform_fee: Decimal
    small_order_fee: Decimal
    surge_fee: Decimal
    surge_reasons: str | None
    discount: Decimal
    coupon_code: str | None
    gst_food: Decimal
    gst_fees: Decimal
    grand_total: Decimal
    distance_km: Decimal | None
    pay_by: datetime
    paid_at: datetime | None
    accept_by: datetime | None
    cancel_reason: str | None
    items: list[OrderItemOut]


class StatusEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: OrderStatus | None
    to_status: OrderStatus
    actor: str
    note: str | None
    created_at: datetime


class TimeoutReport(BaseModel):
    payment_expired: int
    auto_rejected: int


class QuoteOut(BaseModel):
    """The bill before ordering: the same numbers the order will have, if
    nothing changes in between (send grand_total back as expected_total)."""

    restaurant_id: uuid.UUID
    distance_km: Decimal
    surge_reasons: list[str]
    coupon_code: str | None
    # The coupon didn't apply, and why. The quote still comes back, without it.
    coupon_error: str | None
    lines: list[BillLineOut]
    item_total: Decimal
    discount: Decimal
    grand_total: Decimal
