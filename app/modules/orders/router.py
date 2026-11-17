import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.orders import repository, service
from app.modules.orders.schema import (
    CancelRequest,
    OrderCreate,
    OrderOut,
    StatusEventOut,
    StatusUpdate,
    TimeoutReport,
)

router = APIRouter(tags=["orders"])


@router.post("/orders", response_model=OrderOut, status_code=201)
def place_order(body: OrderCreate, db: Session = Depends(get_db)):
    return service.place_order(db, body)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_order(db, order_id)


@router.get("/orders/{order_id}/timeline", response_model=list[StatusEventOut])
def order_timeline(order_id: uuid.UUID, db: Session = Depends(get_db)):
    service.get_order(db, order_id)
    return repository.list_events(db, order_id)


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_status(order_id: uuid.UUID, body: StatusUpdate, db: Session = Depends(get_db)):
    return service.change_status(db, order_id, body.status, body.actor, body.note)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: uuid.UUID, body: CancelRequest, db: Session = Depends(get_db)):
    return service.cancel(db, order_id, body.actor, body.reason)


@router.post("/admin/jobs/order-timeouts", response_model=TimeoutReport, tags=["admin"])
def run_order_timeouts(db: Session = Depends(get_db)):
    """Manual trigger for now. In Phase 4 a scheduler runs this every minute."""
    return service.run_timeouts(db)
