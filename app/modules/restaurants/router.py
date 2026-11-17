from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.restaurants import service
from app.modules.restaurants.schema import RestaurantCreate, RestaurantOut
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
