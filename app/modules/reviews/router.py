import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.reviews import service
from app.modules.reviews.schema import RatingsReport, RestaurantReviews, ReviewCreate, ReviewOut
from app.modules.users.model import Role, User

router = APIRouter(tags=["reviews"])


@router.post("/orders/{order_id}/review", response_model=ReviewOut, status_code=201)
def review_order(
    order_id: uuid.UUID, body: ReviewCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """The customer who placed a DELIVERED order, once, within a few days of delivery."""
    return service.create_review(db, order_id, body, user)


@router.get("/restaurants/{restaurant_id}/reviews", response_model=RestaurantReviews)
def list_reviews(
    restaurant_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Public. Rating summary with the star distribution, and the newest reviews."""
    return service.restaurant_reviews(db, restaurant_id, limit, offset)


@router.post("/admin/jobs/recompute-ratings", response_model=RatingsReport, tags=["admin"])
def recompute_ratings(db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN))):
    """Admins only. Recounts every restaurant's rating totals from the reviews and reports drift."""
    return service.recompute_ratings(db)
