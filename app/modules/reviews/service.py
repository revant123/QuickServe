"""Posting reviews and keeping each restaurant's rating totals right.

The rating shown on every restaurant card is rating_sum / rating_count, two
columns on the restaurant. Reading them is free; keeping them right under
concurrency is the interesting part:

* The counters change with ONE atomic statement:
      UPDATE restaurants SET rating_count = rating_count + 1, rating_sum = rating_sum + 4
  never "read the count in Python, add one, write it back", which loses
  reviews when two arrive at once (tests/test_reviews.py proves it).
* The review row and the counter change commit together, in one transaction.
* A job recounts the totals from the reviews themselves and reports any drift.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import Conflict, NotFound, Unprocessable
from app.core.logging import log_event
from app.core.metrics import REVIEWS, after_commit
from app.database.session import transaction
from app.modules.menu.repository import db_now
from app.modules.orders.model import Order, OrderStatus, OrderStatusEvent
from app.modules.restaurants.model import Restaurant
from app.modules.reviews.model import Review
from app.modules.reviews.schema import RatingsReport, RestaurantReviews, ReviewCreate, ReviewOut
from app.modules.users.model import Role, User

logger = logging.getLogger("quickserve.reviews")


def _out(review: Review, reviewer_name: str) -> ReviewOut:
    return ReviewOut(
        id=review.id,
        order_id=review.order_id,
        restaurant_id=review.restaurant_id,
        rating=review.rating,
        comment=review.comment,
        reviewer=reviewer_name.split()[0] if reviewer_name.strip() else "Customer",
        created_at=review.created_at,
    )


def create_review(
    db: Session, order_id: uuid.UUID, data: ReviewCreate, user: User, settings: Settings | None = None
) -> ReviewOut:
    settings = settings or get_settings()
    order = db.get(Order, order_id)
    # Someone else's order: 404, not 403, so we don't confirm the order exists.
    if order is None or user.role is not Role.CUSTOMER or order.customer_id != user.id:
        raise NotFound("Order not found")
    if order.status is not OrderStatus.DELIVERED:
        raise Unprocessable("You can rate an order once it has been delivered")
    delivered_at = db.execute(
        select(OrderStatusEvent.created_at).where(
            OrderStatusEvent.order_id == order.id, OrderStatusEvent.to_status == OrderStatus.DELIVERED
        )
    ).scalar_one()
    if db_now(db) - delivered_at > timedelta(days=settings.review_window_days):
        # Memories fade and fake-review campaigns target old orders: both
        # platforms ask for the rating soon after delivery.
        raise Unprocessable(f"Reviews close {settings.review_window_days} days after delivery")

    review = Review(
        order_id=order.id,
        restaurant_id=order.restaurant_id,
        customer_id=user.id,
        rating=data.rating,
        comment=data.comment.strip(),
    )
    try:
        with transaction(db):
            db.add(review)
            db.flush()  # INSERT now: a second review for this order fails HERE, before the counters move
            db.execute(
                update(Restaurant)
                .where(Restaurant.id == order.restaurant_id)
                .values(
                    rating_count=Restaurant.rating_count + 1,
                    rating_sum=Restaurant.rating_sum + data.rating,
                )
            )
            stars = str(data.rating)
            after_commit(db, lambda: REVIEWS.labels(stars).inc())
    except IntegrityError as e:
        if getattr(e.orig.diag, "constraint_name", None) == "uq_reviews_order_id":
            raise Conflict("You've already reviewed this order") from None
        raise
    return _out(review, user.name)


def restaurant_reviews(db: Session, restaurant_id: uuid.UUID, limit: int, offset: int) -> RestaurantReviews:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFound("Restaurant not found")
    # One GROUP BY instead of five COUNTs. Served by ix_reviews_restaurant_newest.
    counts = db.execute(
        select(Review.rating, func.count()).where(Review.restaurant_id == restaurant_id).group_by(Review.rating)
    ).all()
    rows = db.execute(
        select(Review, User.name)
        .join(User, User.id == Review.customer_id)
        .where(Review.restaurant_id == restaurant_id)
        .order_by(Review.created_at.desc(), Review.id)
        .limit(limit)
        .offset(offset)
    ).all()
    distribution = {stars: 0 for stars in range(5, 0, -1)} | {stars: n for stars, n in counts}
    return RestaurantReviews(
        restaurant_id=restaurant.id,
        rating=restaurant.rating,
        rating_count=restaurant.rating_count,
        distribution=distribution,
        reviews=[_out(review, name) for review, name in rows],
    )


# Hand-written SQL: an UPDATE driven by an aggregate over another table.
# LEFT JOIN so a restaurant whose reviews were all deleted goes back to 0.
# The WHERE ... IS DISTINCT FROM clause touches only rows that are wrong, and
# RETURNING tells us which ones they were.
RECOUNT_SQL = text(
    """
    WITH truth AS (
        SELECT r.id, count(v.id) AS n, coalesce(sum(v.rating), 0) AS total
        FROM restaurants r
        LEFT JOIN reviews v ON v.restaurant_id = r.id
        GROUP BY r.id
    )
    UPDATE restaurants
    SET rating_count = truth.n, rating_sum = truth.total
    FROM truth
    WHERE restaurants.id = truth.id
      AND (restaurants.rating_count, restaurants.rating_sum) IS DISTINCT FROM (truth.n, truth.total)
    RETURNING restaurants.id, restaurants.name
    """
)


def recompute_ratings(db: Session) -> RatingsReport:
    """Recount every restaurant's totals from its reviews (a reconciliation job).

    This job has a race of its own. If a review commits between counting and
    writing, the job would overwrite the new total with its stale count. So it
    first LOCKS the restaurant rows. A review that is half done waits at its
    counter UPDATE until the job commits, then adds its +1 on top of the
    corrected total; a review that finished first is already in the count.
    (At a large scale you'd do this in batches of restaurants, not all at once.)
    """
    with transaction(db):
        checked = len(db.execute(select(Restaurant.id).order_by(Restaurant.id).with_for_update()).all())
        corrected = db.execute(RECOUNT_SQL).all()
    for restaurant_id, name in corrected:
        log_event(logger, logging.WARNING, "rating_totals_corrected", restaurant_id=str(restaurant_id), restaurant=name)
    return RatingsReport(restaurants_checked=checked, restaurants_corrected=len(corrected))
