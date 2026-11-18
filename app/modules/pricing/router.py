from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.menu.repository import db_now
from app.modules.pricing import service
from app.modules.pricing.calculator import Conditions, surge
from app.modules.pricing.schema import PricingInfo, RainOut, RainRequest
from app.modules.users.model import Role, User

router = APIRouter(tags=["pricing"])


@router.get("/pricing", response_model=PricingInfo)
def pricing_info(db: Session = Depends(get_db)):
    """Public. The fee rules, and which surge fees apply right now."""
    s = get_settings()
    now = db_now(db)
    raining_until = service.rain_until(db, now)
    _, reasons = surge(Conditions(distance_km=0, local_time=service.local_time(now, s), raining=bool(raining_until)), s)
    return PricingInfo(
        local_time=service.local_time(now, s),
        surge_now=list(reasons),
        rain_until=raining_until,
        **s.model_dump(
            include={
                "platform_fee",
                "delivery_fee_slabs",
                "free_delivery_above",
                "free_delivery_max_km",
                "small_order_below",
                "small_order_fee",
                "peak_hours",
                "peak_fee",
                "late_night_hours",
                "late_night_fee",
                "rain_fee",
            }
        ),
    )


@router.put("/admin/surge/rain", response_model=RainOut, tags=["admin"])
def start_rain(body: RainRequest, db: Session = Depends(get_db), admin: User = Depends(require_roles(Role.ADMIN))):
    """Admins only. Every order pays the rain fee until it switches itself off."""
    return RainOut(raining=True, until=service.set_rain(db, body.minutes, admin))


@router.delete("/admin/surge/rain", response_model=RainOut, tags=["admin"])
def end_rain(db: Session = Depends(get_db), admin: User = Depends(require_roles(Role.ADMIN))):
    service.stop_rain(db, admin)
    return RainOut(raining=False, until=None)
