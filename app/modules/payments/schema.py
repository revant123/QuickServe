import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.modules.payments.model import PaymentStatus


class SimulatedOutcome(str, Enum):
    success = "success"
    failure = "failure"


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    amount: Decimal
    status: PaymentStatus
    idempotency_key: str
    provider_reference: str
    failure_reason: str | None
    created_at: datetime
