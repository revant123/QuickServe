import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RestaurantCreate(BaseModel):
    # No owner_id field: the owner is whoever is logged in. Accepting an owner_id
    # from the request would let anyone create restaurants in someone else's name.
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
