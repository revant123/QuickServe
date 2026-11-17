from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.database.session import transaction
from app.modules.restaurants.model import Restaurant
from app.modules.restaurants.schema import RestaurantCreate
from app.modules.users.model import User


def create_restaurant(db: Session, data: RestaurantCreate) -> Restaurant:
    with transaction(db):
        if db.get(User, data.owner_id) is None:
            raise NotFound("Owner not found")
        restaurant = Restaurant(**data.model_dump())
        db.add(restaurant)
    return restaurant


def list_restaurants(db: Session, limit: int, offset: int) -> list[Restaurant]:
    # LIMIT/OFFSET pagination. Every list endpoint is paginated: an unbounded
    # SELECT is a slow query today and an outage once the table is large.
    stmt = select(Restaurant).where(Restaurant.is_open.is_(True)).order_by(Restaurant.name).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())
