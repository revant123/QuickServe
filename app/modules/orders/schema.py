import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.model import OrderStatus


class OrderLineIn(BaseModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(gt=0, le=50)


class OrderCreate(BaseModel):
    customer_id: uuid.UUID  # replaced by the logged-in user once auth exists
    restaurant_id: uuid.UUID
    delivery_address: str = Field(min_length=5, max_length=500)
    items: list[OrderLineIn] = Field(min_length=1, max_length=30)


class StatusUpdate(BaseModel):
    status: OrderStatus
    # "system" (payments, timeouts) and "customer" (use /cancel) are not accepted here.
    actor: str = Field(pattern="^(restaurant|rider|support)$")
    note: str | None = Field(default=None, max_length=300)


class CancelRequest(BaseModel):
    actor: str = Field(default="customer", pattern="^(customer|support)$")
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
    gst_food: Decimal
    gst_fees: Decimal
    grand_total: Decimal
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
