import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import Forbidden, NotFound
from app.database.session import transaction
from app.modules.restaurants.model import Restaurant
from app.modules.restaurants.schema import LocationUpdate, ProfileUpdate, RestaurantCreate
from app.modules.users.model import Role, User


def create_restaurant(db: Session, data: RestaurantCreate, owner: User) -> Restaurant:
    if owner.role not in (Role.RESTAURANT_OWNER, Role.ADMIN):
        raise Forbidden("Only restaurant owners can create restaurants")
    with transaction(db):
        fields = data.model_dump()
        fields["cuisines"] = ", ".join(fields["cuisines"])  # stored as one text column
        restaurant = Restaurant(owner_id=owner.id, **fields)
        db.add(restaurant)
    return restaurant


def get_restaurant(db: Session, restaurant_id: uuid.UUID) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFound("Restaurant not found")
    return restaurant


def list_restaurants(db: Session, limit: int, offset: int) -> list[Restaurant]:
    # LIMIT/OFFSET pagination. Every list endpoint is paginated: an unbounded
    # SELECT is a slow query today and an outage once the table is large.
    stmt = select(Restaurant).where(Restaurant.is_open.is_(True)).order_by(Restaurant.name).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


def ensure_can_manage(db: Session, restaurant_id: uuid.UUID, user: User) -> Restaurant:
    """Public interface for other modules: may this user manage this restaurant?

    Being a RESTAURANT_OWNER isn't enough. You must own THIS restaurant.
    Checking the role but forgetting the ownership is one of the most common
    API security bugs: owner A edits owner B's menu just by changing an ID in
    the URL. OWASP lists it as the top API risk (Broken Object Level Authorization).
    """
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFound("Restaurant not found")
    if user.role is Role.ADMIN:
        return restaurant
    if user.role is not Role.RESTAURANT_OWNER or restaurant.owner_id != user.id:
        raise Forbidden("You can only manage your own restaurant")
    return restaurant


def owns_restaurant(db: Session, restaurant_id: uuid.UUID, user: User) -> bool:
    restaurant = db.get(Restaurant, restaurant_id)
    return restaurant is not None and user.role is Role.RESTAURANT_OWNER and restaurant.owner_id == user.id


def set_location(db: Session, restaurant_id: uuid.UUID, data: LocationUpdate, user: User) -> Restaurant:
    with transaction(db):
        restaurant = ensure_can_manage(db, restaurant_id, user)
        for field, value in data.model_dump().items():
            setattr(restaurant, field, value)
    return restaurant


def set_profile(db: Session, restaurant_id: uuid.UUID, data: ProfileUpdate, user: User) -> Restaurant:
    with transaction(db):
        restaurant = ensure_can_manage(db, restaurant_id, user)
        restaurant.cuisines = ", ".join(data.cuisines)
        restaurant.avg_prep_minutes = data.avg_prep_minutes
    return restaurant


def list_mine(db: Session, owner: User) -> list[Restaurant]:
    """The partner app's restaurant picker (Phase 14). Uses the index on owner_id."""
    return list(
        db.execute(select(Restaurant).where(Restaurant.owner_id == owner.id).order_by(Restaurant.name)).scalars()
    )


def set_open(db: Session, restaurant_id: uuid.UUID, is_open: bool, user: User) -> Restaurant:
    """The partner app's "accepting orders" switch, like going offline on Zomato or Swiggy
    when the kitchen is overwhelmed. Closed restaurants drop out of "near me" and refuse
    new orders; orders already placed carry on."""
    with transaction(db):
        restaurant = ensure_can_manage(db, restaurant_id, user)
        restaurant.is_open = is_open
    return restaurant
