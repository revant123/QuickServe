import uuid

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.payments import service
from app.modules.payments.schema import PaymentOut, SimulatedOutcome
from app.modules.users.model import User

router = APIRouter(tags=["payments"])


@router.post("/orders/{order_id}/payments", response_model=PaymentOut, status_code=201)
def pay(
    order_id: uuid.UUID,
    response: Response,
    idempotency_key: str = Header(min_length=8, max_length=100, alias="Idempotency-Key"),
    simulate: SimulatedOutcome = Query(SimulatedOutcome.success),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Pay for your own order. Retrying with the same Idempotency-Key returns the first result."""
    payment, replayed = service.pay(db, order_id, idempotency_key, simulate, user)
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return payment


@router.get("/orders/{order_id}/payments", response_model=list[PaymentOut])
def list_payments(order_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_for_order(db, order_id, user)


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.get_payment(db, payment_id, user)
