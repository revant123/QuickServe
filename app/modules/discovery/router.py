from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.discovery import service
from app.modules.discovery.schema import NearbyPage, SearchResult, SortBy

router = APIRouter(tags=["discovery"])

LAT = Query(ge=-90, le=90, description="Where to deliver", examples=[30.7333])
LNG = Query(ge=-180, le=180, examples=[76.7794])


@router.get("/restaurants/near", response_model=NearbyPage)
def restaurants_near(
    lat: float = LAT,
    lng: float = LNG,
    sort: SortBy = SortBy.distance,
    cuisine: str | None = Query(None, max_length=40, examples=["North Indian"]),
    min_rating: Decimal | None = Query(None, ge=1, le=5, examples=["4.0"]),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Public. Open restaurants that deliver to this point, with distance, delivery time,
    delivery fee and rating. Sort by distance (default), rating or eta."""
    return service.list_nearby(db, lat, lng, sort, cuisine, min_rating, limit, offset)


@router.get("/search", response_model=SearchResult)
def search(
    q: str = Query(min_length=2, max_length=60, examples=["paneer"]),
    lat: float = LAT,
    lng: float = LNG,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Public. Dishes and restaurants matching q, from restaurants that deliver to you.
    Tolerates typos ("paner", "biriyani") when nothing matches exactly."""
    return service.search(db, q, lat, lng, limit)
