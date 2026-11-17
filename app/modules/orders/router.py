import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.orders import service
from app.modules.orders.schema import (
    CancelRequest,
    OrderCreate,
    OrderOut,
    StatusEventOut,
    StatusUpdate,
    TimeoutReport,
)
from app.modules.users.model import Role, User

router = APIRouter(tags=["orders"])


@router.post("/orders", response_model=OrderOut, status_code=201)
def place_order(body: OrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Customers only. The order belongs to the logged-in customer."""
    return service.place_order(db, body, user)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Visible to: the customer who placed it, the restaurant's owner, riders once it's READY, admins."""
    return service.get_order(db, order_id, user)


@router.get("/orders/{order_id}/timeline", response_model=list[StatusEventOut])
def order_timeline(order_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.timeline(db, order_id, user)


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_status(
    order_id: uuid.UUID, body: StatusUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Restaurant owner: ACCEPTED, REJECTED, PREPARING, READY. Rider: OUT_FOR_DELIVERY, DELIVERED. Admin: CANCELLED."""
    return service.change_status(db, order_id, body.status, user, body.note)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID, body: CancelRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Customers can cancel their own order before the restaurant accepts it; admins any time before delivery."""
    return service.cancel(db, order_id, user, body.reason)


@router.post("/admin/jobs/order-timeouts", response_model=TimeoutReport, tags=["admin"])
def run_order_timeouts(db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN))):
    """Admins only. Manual trigger for now; in Phase 4 a scheduler runs this every minute."""
    return service.run_timeouts(db)
