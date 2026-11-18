import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5, description="1 to 5 stars")
    comment: str = Field(default="", max_length=500)


class ReviewOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    restaurant_id: uuid.UUID
    rating: int
    comment: str
    # First name only: enough to feel human, not enough to identify someone.
    reviewer: str
    created_at: datetime


class RestaurantReviews(BaseModel):
    restaurant_id: uuid.UUID
    rating: Decimal | None  # None: "New", too few reviews
    rating_count: int
    distribution: dict[int, int]  # stars -> how many reviews, for the 5-bar chart
    reviews: list[ReviewOut]


class RatingsReport(BaseModel):
    restaurants_checked: int
    restaurants_corrected: int  # should be 0; anything else means a bug somewhere
