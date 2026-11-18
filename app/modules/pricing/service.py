"""The parts of pricing that need the database or the clock.

calculator.py does the arithmetic; this module gathers its inputs: how far
the customer is, what time it is in India, and whether it's raining.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotServiceable, Unprocessable
from app.database.session import transaction
from app.modules.menu.repository import db_now
from app.modules.pricing.calculator import Conditions
from app.modules.pricing.geo import road_km
from app.modules.pricing.model import SurgeFlag
from app.modules.restaurants.model import Restaurant
from app.modules.users.model import User

RAIN = "rain"


def local_time(now: datetime, settings: Settings) -> time:
    """The surge windows are written in Indian time; the database speaks UTC."""
    return now.astimezone(ZoneInfo(settings.pricing_timezone)).time()


def rain_until(db: Session, now: datetime) -> datetime | None:
    flag = db.get(SurgeFlag, RAIN)
    return flag.active_until if flag is not None and flag.active_until > now else None


def set_rain(db: Session, minutes: int, admin: User) -> datetime:
    with transaction(db):
        until = db_now(db) + timedelta(minutes=minutes)
        # merge(): INSERT if there's no "rain" row yet, UPDATE if there is.
        db.merge(SurgeFlag(name=RAIN, active_until=until, updated_by=admin.id))
    return until


def stop_rain(db: Session, admin: User) -> None:
    with transaction(db):
        db.merge(SurgeFlag(name=RAIN, active_until=db_now(db), updated_by=admin.id))


def conditions_for(
    db: Session, restaurant: Restaurant, lat: float, lng: float, now: datetime, settings: Settings
) -> Conditions:
    """Distance, time and weather for one order. Raises if the address is too far."""
    if restaurant.latitude is None or restaurant.longitude is None:
        raise Unprocessable(f"{restaurant.name} hasn't set its location yet, so it can't take delivery orders")
    distance = road_km(restaurant.latitude, restaurant.longitude, lat, lng, settings.road_detour_factor)
    if distance > restaurant.delivery_radius_km:
        raise NotServiceable(
            f"{restaurant.name} delivers up to {restaurant.delivery_radius_km} km; this address is {distance} km away"
        )
    return Conditions(
        distance_km=distance, local_time=local_time(now, settings), raining=rain_until(db, now) is not None
    )
