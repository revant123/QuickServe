from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.restaurants import service
from app.modules.restaurants.schema import RestaurantCreate, RestaurantOut

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.post("", response_model=RestaurantOut, status_code=201)
def create_restaurant(body: RestaurantCreate, db: Session = Depends(get_db)):
    return service.create_restaurant(db, body)


@router.get("", response_model=list[RestaurantOut])
def list_restaurants(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return service.list_restaurants(db, limit, offset)
