from app.modules.orders import dispatch
from app.modules.orders.model import Order
from app.modules.orders.model import OrderStatus as S
from app.modules.orders.schema import GeoPoint, OrderCreate, OrderLineIn
from app.modules.orders.service import change_status

# About 1 km by road from the test restaurant in Sector 17 (see conftest.py).
NEAR = GeoPoint(lat=30.7333, lng=76.7794)


def order_payload(restaurant, *lines, location: GeoPoint = NEAR, coupon: str | None = None, expected_total=None):
    """lines: (menu_item, quantity) pairs. The customer comes from the logged-in user, not the payload."""
    return OrderCreate(
        restaurant_id=restaurant.id,
        delivery_address="House 12, Sector 22, Chandigarh",
        delivery_location=location,
        items=[OrderLineIn(menu_item_id=item.id, quantity=qty) for item, qty in lines],
        coupon_code=coupon,
        expected_total=expected_total,
    )


def rider_steps(db, order_id, rider, until=S.DELIVERED):
    """Phase 14: the rider claims the order, picks it up, and delivers it with the customer's code."""
    dispatch.claim(db, order_id, rider)
    change_status(db, order_id, S.OUT_FOR_DELIVERY, rider)
    if until is S.DELIVERED:
        code = db.get(Order, order_id, populate_existing=True).delivery_code
        change_status(db, order_id, S.DELIVERED, rider, delivery_code=code)
