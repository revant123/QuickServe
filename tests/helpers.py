from app.modules.orders.schema import OrderCreate, OrderLineIn


def order_payload(restaurant, *lines) -> OrderCreate:
    """lines: (menu_item, quantity) pairs. The customer comes from the logged-in user, not the payload."""
    return OrderCreate(
        restaurant_id=restaurant.id,
        delivery_address="House 12, Sector 22, Chandigarh",
        items=[OrderLineIn(menu_item_id=item.id, quantity=qty) for item, qty in lines],
    )
