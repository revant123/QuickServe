"""Pydantic schemas: what the API accepts and returns.

Schemas are kept separate from SQLAlchemy models on purpose. The model is the
shape of the table; the schema is the shape of the API contract. They change
for different reasons, e.g. password_hash is a column but must never be in a response.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MenuItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=500)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_veg: bool = True
    track_stock: bool = True
    stock: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def stock_matches_tracking(self):
        if self.track_stock and self.stock is None:
            raise ValueError("stock is required when track_stock is true")
        if not self.track_stock and self.stock is not None:
            raise ValueError("stock must be empty when track_stock is false")
        return self


class RestockRequest(BaseModel):
    quantity: int = Field(ge=0, description="Units prepared for the new cycle")
    carry_over_leftover: bool = Field(
        default=False,
        description="Add unsold units from the closing cycle to the new stock. "
        "False for most cooked food (leftovers are discarded); true for packaged items.",
    )


class AvailabilityUpdate(BaseModel):
    is_available: bool
    unavailable_until: datetime | None = None


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    name: str
    description: str
    price: Decimal
    is_veg: bool
    is_available: bool
    unavailable_until: datetime | None
    track_stock: bool
    stock: int | None
    consumed: int
    available: int | None
    cycle_no: int
    cycle_started_at: datetime
    sold_out_at: datetime | None


class MenuItemPublic(BaseModel):
    """What a customer sees: no raw counters, just what helps them decide."""

    id: uuid.UUID
    name: str
    description: str
    price: Decimal
    is_veg: bool
    orderable: bool
    badge: str | None = Field(description="SOLD_OUT, ONLY_N_LEFT, SELLING_FAST or null")
    units_left: int | None = Field(description="Shown only when stock is low")


class CycleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cycle_no: int
    started_at: datetime
    closed_at: datetime | None
    units_stocked: int | None
    carried_in: int
    units_consumed: int | None
    units_returned: int
    units_wasted: int
    leftover: int | None
    leftover_carried: bool | None
    sold_out_at: datetime | None


class RestockResult(BaseModel):
    closed_cycle: CycleOut
    item: MenuItemOut


class RestockSuggestion(BaseModel):
    menu_item_id: uuid.UUID
    suggested_quantity: int | None
    based_on_cycles: int
    explanation: list[str]


class BestSellerRow(BaseModel):
    menu_item_id: uuid.UUID
    name: str
    units_sold: int
    units_stocked: int | None
    sell_through: float | None = Field(description="units_sold / units_stocked, tracked items only")
    hours_on_sale: float
    units_per_hour: float = Field(description="Sales rate while the item was actually available")
    sold_out_cycles: int
    cycles: int
    rank: int
