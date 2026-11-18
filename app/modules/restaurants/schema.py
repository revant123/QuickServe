import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RestaurantCreate(BaseModel):
    # No owner_id field: the owner is whoever is logged in. Accepting an owner_id
    # from the request would let anyone create restaurants in someone else's name.
    name: str = Field(min_length=1, max_length=150)
    address: str = Field(min_length=1, max_length=500)
    packaging_charge: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    # Phase 11: where the kitchen is, and how far it delivers (road km).
    latitude: Decimal = Field(ge=-90, le=90, max_digits=9, decimal_places=6, examples=["30.739800"])
    longitude: Decimal = Field(ge=-180, le=180, max_digits=9, decimal_places=6, examples=["76.782700"])
    delivery_radius_km: Decimal = Field(default=Decimal("7.0"), gt=0, le=15, max_digits=4, decimal_places=1)


class LocationUpdate(BaseModel):
    """For restaurants created before Phase 11, which have no location yet."""

    latitude: Decimal = Field(ge=-90, le=90, max_digits=9, decimal_places=6)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=9, decimal_places=6)
    delivery_radius_km: Decimal = Field(default=Decimal("7.0"), gt=0, le=15, max_digits=4, decimal_places=1)


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    address: str
    is_open: bool
    packaging_charge: Decimal
    latitude: Decimal | None
    longitude: Decimal | None
    delivery_radius_km: Decimal
