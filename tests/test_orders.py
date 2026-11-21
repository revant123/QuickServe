"""Order lifecycle, the bill, and what each ending does to stock."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.exceptions import Forbidden, InvalidTransition, NotFound
from app.modules.menu import repository as menu_repo
from app.modules.menu.service import restock
from app.modules.orders import repository as order_repo
from app.modules.orders.model import OrderStatus as S
from app.modules.orders.service import cancel, change_status, get_order, place_order, run_timeouts
from app.modules.payments.model import Payment, PaymentStatus
from app.modules.payments.schema import SimulatedOutcome
from app.modules.payments.service import pay
from app.modules.users.model import Role
from tests.helpers import order_payload, rider_steps


def _paid_order(db, customer, restaurant, *lines):
    order = place_order(db, order_payload(restaurant, *lines), customer)
    pay(db, order.id, f"key-{order.id}", SimulatedOutcome.success, customer)
    db.refresh(order)
    return order


def test_bill_below_free_delivery(db, restaurant, customer, make_item):
    item = make_item(price="125.00", stock=10)
    order = place_order(db, order_payload(restaurant, (item, 2)), customer)
    # 1.0 km away (0.8 km straight line x 1.25), so the 0-2 km delivery slab.
    # items 250 + packaging 20 + delivery 20 + platform 14.90
    # GST food 5% of 270 = 13.50 ; GST fees 18% of 34.90 = 6.28
    assert order.distance_km == Decimal("1.0")
    assert order.item_total == Decimal("250.00")
    assert order.delivery_fee == Decimal("20.00")
    assert order.small_order_fee == order.surge_fee == order.discount == Decimal("0.00")
    assert order.gst_food == Decimal("13.50")
    assert order.gst_fees == Decimal("6.28")
    assert order.grand_total == Decimal("324.68")
    assert order.items[0].unit_price == Decimal("125.00")


def test_free_delivery_above_threshold(db, restaurant, customer, make_item):
    item = make_item(price="150.00", stock=10)
    order = place_order(db, order_payload(restaurant, (item, 2)), customer)
    assert order.delivery_fee == Decimal("0.00")


def test_price_snapshot_survives_menu_price_change(db, restaurant, customer, make_item):
    item = make_item(price="150.00", stock=10)
    order = place_order(db, order_payload(restaurant, (item, 1)), customer)
    db.execute(text("UPDATE menu_items SET price = 999 WHERE id = :id"), {"id": item.id})
    db.commit()
    db.refresh(order)
    assert order.items[0].unit_price == Decimal("150.00")


def test_illegal_transitions_are_refused(db, restaurant, customer, make_item, owner, rider):
    item = make_item(stock=10)
    order = place_order(db, order_payload(restaurant, (item, 1)), customer)
    with pytest.raises(InvalidTransition):
        change_status(db, order.id, S.PREPARING, owner)  # not paid or accepted yet
    order = _paid_order(db, customer, restaurant, (item, 1))
    for status, actor in [
        (S.ACCEPTED, owner),
        (S.PREPARING, owner),
        (S.READY, owner),
    ]:
        change_status(db, order.id, status, actor)
    rider_steps(db, order.id, rider)
    with pytest.raises(InvalidTransition):
        change_status(db, order.id, S.PREPARING, owner)  # DELIVERED is final


def test_who_you_are_decides_what_you_can_do(db, restaurant, customer, make_item, make_user, owner, rider):
    item = make_item(stock=10)
    order = _paid_order(db, customer, restaurant, (item, 1))
    other_owner = make_user(Role.RESTAURANT_OWNER)
    other_customer = make_user(Role.CUSTOMER)

    with pytest.raises(Forbidden, match="As customer"):
        change_status(db, order.id, S.ACCEPTED, customer)  # can see it, can't accept it
    with pytest.raises(NotFound):
        change_status(db, order.id, S.ACCEPTED, other_owner)  # not their restaurant: order "doesn't exist"
    with pytest.raises(NotFound):
        change_status(db, order.id, S.ACCEPTED, rider)  # riders only see orders they've claimed
    with pytest.raises(NotFound):
        get_order(db, order.id, other_customer)

    change_status(db, order.id, S.ACCEPTED, owner)
    with pytest.raises(Forbidden, match="As restaurant"):
        change_status(db, order.id, S.CANCELLED, owner)  # restaurants reject, they don't cancel


def test_cancel_before_payment_releases_stock(db, restaurant, customer, make_item):
    item = make_item(stock=10)
    order = place_order(db, order_payload(restaurant, (item, 4)), customer)
    cancel(db, order.id, customer, "Ordered by mistake")
    db.refresh(item)
    assert item.consumed == 0


def test_cancel_after_restock_credits_the_old_cycle(db, restaurant, customer, make_item, owner):
    item = make_item(stock=10)
    order = place_order(db, order_payload(restaurant, (item, 3)), customer)
    restock(db, item.id, quantity=10, carry_over_leftover=False, user=owner)

    cancel(db, order.id, customer, "Changed my mind")

    db.refresh(item)
    old, new = menu_repo.list_cycles(db, item.id)
    assert item.consumed == 0  # the new cycle is untouched
    assert old.units_consumed == 3 and old.units_returned == 3


def test_cancel_while_preparing_counts_as_waste_and_refunds(db, restaurant, customer, make_item, owner, admin):
    item = make_item(stock=10)
    order = _paid_order(db, customer, restaurant, (item, 2))
    change_status(db, order.id, S.ACCEPTED, owner)
    change_status(db, order.id, S.PREPARING, owner)

    with pytest.raises(InvalidTransition, match="contact support"):
        cancel(db, order.id, customer, "Too slow")
    cancel(db, order.id, admin, "Rider unavailable")

    db.refresh(item)
    cycle = menu_repo.list_cycles(db, item.id)[0]
    assert item.consumed == 2  # the food was cooked; it is not back on sale
    assert cycle.units_wasted == 2
    payment = db.query(Payment).filter_by(order_id=order.id).one()
    db.refresh(payment)
    assert payment.status is PaymentStatus.REFUNDED


def test_restaurant_that_never_accepts_is_auto_rejected(db, restaurant, customer, make_item):
    item = make_item(stock=10)
    order = _paid_order(db, customer, restaurant, (item, 2))
    db.execute(text("UPDATE orders SET accept_by = now() - interval '1 second' WHERE id = :id"), {"id": order.id})
    db.commit()

    report = run_timeouts(db)

    assert report.auto_rejected == 1
    db.refresh(order)
    db.refresh(item)
    assert order.status is S.REJECTED and item.consumed == 0
    payment = db.query(Payment).filter_by(order_id=order.id).one()
    db.refresh(payment)
    assert payment.status is PaymentStatus.REFUNDED


def test_unpaid_order_expires_and_frees_stock(db, restaurant, customer, make_item):
    item = make_item(stock=3)
    order = place_order(db, order_payload(restaurant, (item, 3)), customer)
    db.execute(text("UPDATE orders SET pay_by = now() - interval '1 second' WHERE id = :id"), {"id": order.id})
    db.commit()

    assert run_timeouts(db).payment_expired == 1
    db.refresh(order)
    db.refresh(item)
    assert order.status is S.PAYMENT_FAILED and item.available == 3


def test_timeline_records_every_change(db, restaurant, customer, make_item, owner):
    item = make_item(stock=10)
    order = _paid_order(db, customer, restaurant, (item, 1))
    change_status(db, order.id, S.ACCEPTED, owner)
    steps = [(e.from_status, e.to_status, e.actor) for e in order_repo.list_events(db, order.id)]
    assert steps == [(None, S.PLACED, "customer"), (S.PLACED, S.PAID, "system"), (S.PAID, S.ACCEPTED, "restaurant")]
