import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class SortBy(StrEnum):
    distance = "distance"
    rating = "rating"
    eta = "eta"


class RestaurantCard(BaseModel):
    """One restaurant in the "near me" list: what a listing card shows."""

    id: uuid.UUID
    name: str
    address: str
    cuisines: list[str]
    distance_km: Decimal  # road estimate, the same number checkout will use
    eta_minutes: int
    eta_text: str  # "25-30 min"
    rating: Decimal | None  # None means "New": too few reviews to show an average
    rating_count: int
    delivery_fee: Decimal  # for an ordinary order; it may be free above free_delivery_above
    free_delivery_above: Decimal | None  # None: too far for free delivery
    packaging_charge: Decimal


class NearbyPage(BaseModel):
    total: int  # how many restaurants deliver here (after filters), for "Showing 1-20 of 57"
    restaurants: list[RestaurantCard]


class DishHit(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    price: Decimal
    is_veg: bool
    restaurant: RestaurantCard


class SearchResult(BaseModel):
    query: str
    # exact: the words matched. fuzzy: nothing matched exactly, so these are the
    # closest spellings ("Showing results for paneer"). none: nothing at all.
    matched: Literal["exact", "fuzzy", "none"]
    restaurants: list[RestaurantCard]
    dishes: list[DishHit]
