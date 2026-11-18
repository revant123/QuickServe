"""Ratings and reviews (Phase 12).

A review belongs to an ORDER, not just to a restaurant: only someone who
actually received food from the restaurant can rate it, and only once per
order. Zomato and Swiggy both ask for the rating on the order screen for
exactly this reason: it keeps out reviews from people who never ordered.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKey


class Review(UUIDPrimaryKey, Base):
    __tablename__ = "reviews"

    # unique=True: one review per order, guaranteed by the database. Two taps on
    # "Submit" at the same moment can't both get in, whatever the code does.
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_1_to_5"),
        # The restaurant page lists its newest reviews first: this index returns
        # them already in that order, so there's no sort step.
        Index("ix_reviews_restaurant_newest", "restaurant_id", text("created_at DESC")),
    )
