import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.orders import service
from app.modules.orders.schema import (
    CancelRequest,
    OrderCreate,
    OrderOut,
    OrderSummary,
    QuoteOut,
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


@router.get("/orders", response_model=list[OrderSummary])
def my_orders(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.CUSTOMER)),
):
    """Customers only: your own orders, newest first (the app's "My orders" screen)."""
    return service.list_my_orders(db, user, limit, offset)


@router.post("/orders/quote", response_model=QuoteOut)
def quote_order(body: OrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The bill for this cart, right now: every line, with the reasons. Reserves nothing.

    Show it at checkout, then place the order with expected_total set to its
    grand_total: if anything changed in between, the order is refused (409)
    with the new total instead of silently charging more.
    """
    bill, coupon_error = service.quote(db, body, user)
    return QuoteOut(
        restaurant_id=body.restaurant_id,
        distance_km=bill.distance_km,
        surge_reasons=list(bill.surge_reasons),
        coupon_code=bill.coupon_code,
        coupon_error=coupon_error,
        lines=[line.__dict__ for line in bill.lines],
        item_total=bill.item_total,
        discount=bill.discount,
        grand_total=bill.grand_total,
    )


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
