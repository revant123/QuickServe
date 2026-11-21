import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.restaurants import service
from app.modules.restaurants.schema import LocationUpdate, ProfileUpdate, RestaurantCreate, RestaurantOut
from app.modules.users.model import User

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.post("", response_model=RestaurantOut, status_code=201)
def create_restaurant(body: RestaurantCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Restaurant owners only. You become the owner of the restaurant you create."""
    return service.create_restaurant(db, body, user)


@router.get("", response_model=list[RestaurantOut])
def list_restaurants(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Public: no login needed to browse."""
    return service.list_restaurants(db, limit, offset)


@router.get("/{restaurant_id}", response_model=RestaurantOut)
def get_restaurant(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    """Public. One restaurant, for the app's menu page (a shared link or a refresh lands here first)."""
    return service.get_restaurant(db, restaurant_id)


@router.put("/{restaurant_id}/location", response_model=RestaurantOut)
def set_location(
    restaurant_id: uuid.UUID,
    body: LocationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The restaurant's owner (or an admin). Needed before a restaurant from before Phase 11 can take orders."""
    return service.set_location(db, restaurant_id, body, user)


@router.put("/{restaurant_id}/profile", response_model=RestaurantOut)
def set_profile(
    restaurant_id: uuid.UUID,
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The restaurant's owner (or an admin). Cuisines and usual preparation time (Phase 12)."""
    return service.set_profile(db, restaurant_id, body, user)
