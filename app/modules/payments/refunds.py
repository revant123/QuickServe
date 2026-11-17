"""Public interface the orders module uses to trigger refunds.

In a modular monolith, one module calls another only through a small public
interface like this, never by reaching into its tables or internals. That is
what makes it possible to move payments into its own service later: this
function becomes an HTTP call or a message, and callers don't change.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.payments.model import Payment, PaymentStatus


def refund_for_order(db: Session, order_id: uuid.UUID) -> bool:
    payment = db.execute(
        select(Payment)
        .where(Payment.order_id == order_id, Payment.status == PaymentStatus.SUCCESS)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if payment is None:
        return False
    payment.status = PaymentStatus.REFUNDED  # mock: a real gateway call would go here
    return True
