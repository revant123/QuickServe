import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RestaurantCreate(BaseModel):
    owner_id: uuid.UUID
    name: str = Field(min_length=1, max_length=150)
    address: str = Field(min_length=1, max_length=500)
    packaging_charge: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    address: str
    is_open: bool
    packaging_charge: Decimal
