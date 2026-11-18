from app.modules.orders.schema import GeoPoint, OrderCreate, OrderLineIn

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
