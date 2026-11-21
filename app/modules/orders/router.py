import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.orders import dispatch, kitchen, service
from app.modules.orders.model import Order
from app.modules.orders.schema import (
    CancelRequest,
    KitchenOrder,
    OrderCreate,
    OrderOut,
    OrderSummary,
    PoolOrder,
    QuoteOut,
    RiderDay,
    RiderOrder,
    SalesReport,
    StatusEventOut,
    StatusUpdate,
    TimeoutReport,
)
from app.modules.users.model import Role, User

router = APIRouter(tags=["orders"])


def present(db: Session, order: Order, viewer: User) -> OrderOut:
    """The order as this viewer may see it.

    The delivery code is the customer's secret: if the rider or the restaurant
    could read it from the API, it would prove nothing at the door.
    """
    rider = db.get(User, order.rider_id) if order.rider_id else None
    return OrderOut.model_validate(order).model_copy(
        update={
            "rider_name": rider.name if rider else None,
            "delivery_code": order.delivery_code if viewer.id == order.customer_id else None,
        }
    )


@router.post("/orders", response_model=OrderOut, status_code=201)
def place_order(body: OrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Customers only. The order belongs to the logged-in customer."""
    return present(db, service.place_order(db, body, user), user)


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
    """Visible to: the customer who placed it, the restaurant's owner, the rider who claimed it, admins."""
    return present(db, service.get_order(db, order_id, user), user)


@router.get("/orders/{order_id}/timeline", response_model=list[StatusEventOut])
def order_timeline(order_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.timeline(db, order_id, user)


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_status(
    order_id: uuid.UUID, body: StatusUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Restaurant owner: ACCEPTED, REJECTED, PREPARING, READY. Its rider: OUT_FOR_DELIVERY, then DELIVERED
    with the customer's `delivery_code` (422 if wrong, locked after 5 wrong tries). Admin: CANCELLED."""
    order = service.change_status(db, order_id, body.status, user, body.note, body.delivery_code)
    return present(db, order, user)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID, body: CancelRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Customers can cancel their own order before the restaurant accepts it; admins any time before delivery."""
    return present(db, service.cancel(db, order_id, user, body.reason), user)


@router.post("/admin/jobs/order-timeouts", response_model=TimeoutReport, tags=["admin"])
def run_order_timeouts(db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN))):
    """Admins only. Manual trigger for now; in Phase 4 a scheduler runs this every minute."""
    return service.run_timeouts(db)


# Phase 14: restaurant partners


@router.get("/restaurants/{restaurant_id}/orders", response_model=list[KitchenOrder], tags=["partners"])
def order_board(
    restaurant_id: uuid.UUID,
    view: Literal["active", "recent"] = "active",
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.RESTAURANT_OWNER, Role.ADMIN)),
):
    """The restaurant's owner. `active`: paid orders the kitchen still has to act on, oldest first.
    `recent`: finished, cancelled and picked-up orders, newest first."""
    return kitchen.board(db, restaurant_id, user, view, limit)


@router.get("/restaurants/{restaurant_id}/sales", response_model=SalesReport, tags=["partners"])
def sales_report(
    restaurant_id: uuid.UUID,
    day: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.RESTAURANT_OWNER, Role.ADMIN)),
):
    """The restaurant's owner. One day's orders, sales, commission and estimated payout
    (default: today in the restaurant's time zone)."""
    return kitchen.sales(db, restaurant_id, user, day)


# Phase 14: riders


@router.get("/rider/pool", response_model=list[PoolOrder], tags=["riders"])
def rider_pool(db: Session = Depends(get_db), _: User = Depends(require_roles(Role.RIDER))):
    """Riders. Accepted orders nobody has claimed yet, food closest to ready first."""
    return dispatch.pool(db)


@router.get("/rider/me", response_model=RiderDay, tags=["riders"])
def rider_day(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.RIDER))):
    """Riders. Your delivery in progress, and today's deliveries and earnings."""
    return dispatch.my_day(db, user)


@router.post("/orders/{order_id}/claim", response_model=RiderOrder, tags=["riders"])
def claim_order(order_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.RIDER))):
    """Riders. Take an order from the pool. 409 if someone else got it first, or if you
    already have a delivery in progress."""
    return dispatch.rider_order(db, dispatch.claim(db, order_id, user))


@router.post("/orders/{order_id}/release", response_model=RiderOrder, tags=["riders"])
def release_order(order_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.RIDER))):
    """Riders. Give your order back to the pool, before you've picked it up."""
    return dispatch.rider_order(db, dispatch.release(db, order_id, user))
