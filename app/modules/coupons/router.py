import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.coupons import service
from app.modules.coupons.schema import CouponCreate, CouponOut
from app.modules.menu.repository import db_now
from app.modules.users.model import User

router = APIRouter(prefix="/coupons", tags=["coupons"])


@router.post("", response_model=CouponOut, status_code=201)
def create_coupon(body: CouponCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Admins: platform-funded coupons. Restaurant owners: coupons for their own restaurant, which they fund."""
    return service.create_coupon(db, body, user)


@router.get("", response_model=list[CouponOut])
def available_coupons(restaurant_id: uuid.UUID | None = Query(None), db: Session = Depends(get_db)):
    """Public. Coupons a customer could try at checkout (per-customer rules are checked in the quote)."""
    return service.list_available(db, restaurant_id, db_now(db))
