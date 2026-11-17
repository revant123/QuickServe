import uuid

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.database.session import get_db
from app.modules.payments import service
from app.modules.payments.model import Payment
from app.modules.payments.schema import PaymentOut, SimulatedOutcome

router = APIRouter(tags=["payments"])


@router.post("/orders/{order_id}/payments", response_model=PaymentOut, status_code=201)
def pay(
    order_id: uuid.UUID,
    response: Response,
    idempotency_key: str = Header(min_length=8, max_length=100, alias="Idempotency-Key"),
    simulate: SimulatedOutcome = Query(SimulatedOutcome.success),
    db: Session = Depends(get_db),
):
    payment, replayed = service.pay(db, order_id, idempotency_key, simulate)
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return payment


@router.get("/orders/{order_id}/payments", response_model=list[PaymentOut])
def list_payments(order_id: uuid.UUID, db: Session = Depends(get_db)):
    return list(db.execute(select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at)).scalars())


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: uuid.UUID, db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise NotFound("Payment not found")
    return payment
