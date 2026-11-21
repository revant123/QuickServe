"""Phase 14: riders claiming orders, delivery codes, the restaurant's order board and sales."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.core.exceptions import Conflict, InvalidTransition, NotFound, WrongDeliveryCode
from app.database.session import SessionLocal
from app.modules.coupons import service as coupons
from app.modules.coupons.schema import CouponCreate
from app.modules.notifications.templates import messages_for
from app.modules.orders import dispatch, kitchen
from app.modules.orders.model import Order
from app.modules.orders.model import OrderStatus as S
from app.modules.orders.service import cancel, change_status, get_order, new_delivery_code, place_order, run_timeouts
from app.modules.outbox.model import OutboxEvent
from app.modules.payments.schema import SimulatedOutcome
from app.modules.payments.service import pay
from app.modules.pricing.calculator import CouponKind
from app.modules.restaurants import service as restaurants
from app.modules.users.model import Role
from tests.helpers import order_payload, rider_steps
from tests.test_orm_behaviour import count_queries

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def paid(db, restaurant, customer, make_item):
    item = make_item("Dal Makhani", "240.00", stock=100)

    def _paid(qty=1, coupon=None, who=None):
        who = who or customer
        order = place_order(db, order_payload(restaurant, (item, qty), coupon=coupon), who)
        pay(db, order.id, f"key-{order.id}", SimulatedOutcome.success, who)
        db.refresh(order)
        return order

    return _paid


@pytest.fixture
def accepted(db, paid, owner):
    def _accepted(until=S.ACCEPTED, **kw):
        order = paid(**kw)
        for status in (S.ACCEPTED, S.PREPARING, S.READY):
            change_status(db, order.id, status, owner)
            if status is until:
                break
        return order

    return _accepted


def _run_concurrently(n, fn):
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


# ----- the pool -----


def test_the_pool_lists_accepted_unclaimed_orders_readiest_first_without_the_address(db, paid, accepted, rider):
    paid()  # PAID: the restaurant hasn't accepted it, so no rider should ride over yet
    cooking = accepted(until=S.PREPARING)
    waiting = accepted(until=S.ACCEPTED)
    packed = accepted(until=S.READY)

    pool = dispatch.pool(db)
    assert [p.id for p in pool] == [packed.id, cooking.id, waiting.id]
    assert "delivery_address" not in pool[0].model_dump()
    # 20 + 6 per km, whole rupees
    assert pool[0].rider_pay == (D("20") + D("6") * packed.distance_km).quantize(D("1"))
    assert pool[0].item_count == 1

    with pytest.raises(NotFound):
        get_order(db, packed.id, rider)  # not theirs (yet): the order "doesn't exist"


def test_claiming_gives_the_order_to_one_rider(db, accepted, make_user, customer):
    order = accepted()
    first, second = make_user(Role.RIDER), make_user(Role.RIDER)

    claimed = dispatch.claim(db, order.id, first)
    assert claimed.rider_id == first.id and claimed.rider_pay is not None
    assert get_order(db, order.id, first).id == order.id
    assert dispatch.pool(db) == []

    with pytest.raises(Conflict, match="Another delivery partner"):
        dispatch.claim(db, order.id, second)
    with pytest.raises(NotFound):
        change_status(db, order.id, S.OUT_FOR_DELIVERY, second)

    event = db.execute(select(OutboxEvent).where(OutboxEvent.event_type == "order.rider_assigned")).scalar_one()
    [message] = messages_for(event.event_type, event.payload)
    assert message.user_id == str(customer.id) and message.title == f"{first.name.split()[0]} will deliver your order"


def test_unpaid_or_finished_orders_cant_be_claimed(db, restaurant, customer, make_item, rider, paid):
    unpaid = place_order(db, order_payload(restaurant, (make_item(stock=5), 1)), customer)
    with pytest.raises(NotFound):
        dispatch.claim(db, unpaid.id, rider)
    with pytest.raises(NotFound):
        dispatch.claim(db, paid().id, rider)  # paid, but not accepted


def test_ten_riders_tap_accept_at_once_and_one_gets_it(db, accepted, make_user):
    order = accepted(until=S.READY)
    riders = [make_user(Role.RIDER) for _ in range(10)]

    def try_claim(i):
        session = SessionLocal()
        try:
            dispatch.claim(session, order.id, riders[i])
            return "ok"
        except Conflict:
            return "taken"
        finally:
            session.close()

    results = _run_concurrently(10, try_claim)
    assert results.count("ok") == 1 and results.count("taken") == 9
    db.expire_all()
    assert db.get(Order, order.id).rider_id in {r.id for r in riders}


def test_a_rider_has_one_delivery_at_a_time(db, accepted, rider):
    first, second = accepted(until=S.READY), accepted()
    dispatch.claim(db, first.id, rider)
    with pytest.raises(Conflict, match="Finish your current delivery"):
        dispatch.claim(db, second.id, rider)

    rider_steps_after_claim(db, first.id, rider)
    dispatch.claim(db, second.id, rider)  # delivered: free again


def test_one_rider_double_claiming_on_two_phones_is_stopped_by_the_database(db, accepted, rider):
    """Both claims pass the WHERE clause (each order is free). Only the partial
    unique index notices that both rows would be the same rider's active order."""
    orders = [accepted(), accepted()]

    def try_claim(i):
        session = SessionLocal()
        try:
            dispatch.claim(session, orders[i].id, rider)
            return "ok"
        except Conflict:
            return "refused"
        finally:
            session.close()

    assert sorted(_run_concurrently(2, try_claim)) == ["ok", "refused"]
    db.expire_all()
    mine = db.execute(select(Order).where(Order.rider_id == rider.id)).scalars().all()
    assert len(mine) == 1


def test_a_cancelled_order_frees_its_rider(db, accepted, rider, admin):
    first, second = accepted(until=S.PREPARING), accepted()
    dispatch.claim(db, first.id, rider)
    cancel(db, first.id, admin, "Kitchen fire")
    dispatch.claim(db, second.id, rider)  # CANCELLED is outside the unique index's WHERE


def test_release_puts_the_order_back_until_pickup(db, accepted, rider):
    order = accepted(until=S.READY)
    dispatch.claim(db, order.id, rider)
    released = dispatch.release(db, order.id, rider)
    assert released.rider_id is None and released.rider_pay is None
    assert [p.id for p in dispatch.pool(db)] == [order.id]

    dispatch.claim(db, order.id, rider)
    change_status(db, order.id, S.OUT_FOR_DELIVERY, rider)
    with pytest.raises(InvalidTransition):
        dispatch.release(db, order.id, rider)


def rider_steps_after_claim(db, order_id, rider):
    change_status(db, order_id, S.OUT_FOR_DELIVERY, rider)
    code = db.get(Order, order_id, populate_existing=True).delivery_code
    change_status(db, order_id, S.DELIVERED, rider, delivery_code=code)


# ----- the delivery code -----


def test_codes_are_four_random_digits():
    codes = {new_delivery_code() for _ in range(300)}
    assert all(len(c) == 4 and c.isdigit() for c in codes)
    assert len(codes) > 250  # random, not a counter or a constant


def test_the_rider_needs_the_customers_code_and_wrong_tries_are_counted(db, accepted, rider):
    order = accepted(until=S.READY)
    dispatch.claim(db, order.id, rider)
    change_status(db, order.id, S.OUT_FOR_DELIVERY, rider)
    wrong = "0000" if order.delivery_code != "0000" else "1111"

    with pytest.raises(WrongDeliveryCode, match="4 tries left"):
        change_status(db, order.id, S.DELIVERED, rider, delivery_code=wrong)
    with pytest.raises(WrongDeliveryCode, match="3 tries left"):
        change_status(db, order.id, S.DELIVERED, rider)  # no code at all counts too

    # The count survived the failed request: it was committed before the error.
    db.expire_all()
    assert db.get(Order, order.id).delivery_code_attempts == 2
    assert db.get(Order, order.id).status is S.OUT_FOR_DELIVERY

    change_status(db, order.id, S.DELIVERED, rider, delivery_code=order.delivery_code)
    assert db.get(Order, order.id, populate_existing=True).status is S.DELIVERED


def test_five_wrong_codes_lock_the_order(db, accepted, rider):
    order = accepted(until=S.READY)
    dispatch.claim(db, order.id, rider)
    change_status(db, order.id, S.OUT_FOR_DELIVERY, rider)
    wrong = "0000" if order.delivery_code != "0000" else "1111"
    for _ in range(4):
        with pytest.raises(WrongDeliveryCode):
            change_status(db, order.id, S.DELIVERED, rider, delivery_code=wrong)
    with pytest.raises(WrongDeliveryCode, match="locked"):
        change_status(db, order.id, S.DELIVERED, rider, delivery_code=wrong)
    with pytest.raises(Conflict, match="Too many wrong codes"):
        change_status(db, order.id, S.DELIVERED, rider, delivery_code=order.delivery_code)  # even the right one


def test_orders_from_before_phase_14_need_no_code(db, accepted, rider):
    order = accepted(until=S.READY)
    db.execute(text("UPDATE orders SET delivery_code = NULL WHERE id = :id"), {"id": order.id})
    db.commit()
    dispatch.claim(db, order.id, rider)
    change_status(db, order.id, S.OUT_FOR_DELIVERY, rider)
    change_status(db, order.id, S.DELIVERED, rider)


def test_the_riders_day(db, accepted, rider):
    for _ in range(2):
        order = accepted(until=S.READY)
        rider_steps(db, order.id, rider)
    current = accepted()
    dispatch.claim(db, current.id, rider)

    day = dispatch.my_day(db, rider)
    assert day.active.id == current.id and day.active.delivery_address
    assert day.deliveries_today == 2
    assert day.earnings_today == sum(o.rider_pay for o in day.delivered_today)


# ----- the restaurant's order board -----


def test_the_board_shows_paid_orders_oldest_first_and_never_unpaid_ones(
    db, restaurant, customer, make_item, paid, accepted, owner, rider
):
    place_order(db, order_payload(restaurant, (make_item(stock=5), 1)), customer)  # unpaid: hidden
    first = paid()
    second = accepted(until=S.PREPARING)
    done = accepted(until=S.READY)
    rider_steps(db, done.id, rider)

    active = kitchen.board(db, restaurant.id, owner, "active")
    assert [o.id for o in active] == [first.id, second.id]
    assert active[0].items[0].name == "Dal Makhani" and active[0].accept_by is not None
    assert active[0].short_id == str(first.id)[-4:].upper()
    recent = kitchen.board(db, restaurant.id, owner, "recent")
    assert [o.id for o in recent] == [done.id] and recent[0].rider_name == rider.name


def test_the_board_takes_the_same_number_of_queries_for_2_or_12_orders(db, restaurant, paid, owner, make_user):
    def queries_for_board():
        db.expire_all()
        with count_queries() as statements:
            kitchen.board(db, restaurant.id, owner, "active")
        return len(statements)

    for _ in range(2):
        paid(who=make_user())
    few = queries_for_board()
    for _ in range(10):
        paid(who=make_user())
    assert queries_for_board() == few


def test_another_owners_board_and_sales_dont_exist(db, restaurant, make_user):
    stranger = make_user(Role.RESTAURANT_OWNER)
    with pytest.raises(NotFound):
        kitchen.board(db, restaurant.id, stranger, "active")
    with pytest.raises(NotFound):
        kitchen.sales(db, restaurant.id, stranger)


# ----- the day's sales -----


def test_sales_payout_counts_only_the_restaurants_own_discounts(
    db, restaurant, owner, admin, accepted, rider, make_user
):
    terms = dict(description="Flat Rs 50 off", kind=CouponKind.FLAT, value=D("50"), min_order_value=D("100"))
    coupons.create_coupon(db, CouponCreate(code="DHABA50", restaurant_id=restaurant.id, **terms), owner)
    coupons.create_coupon(db, CouponCreate(code="PLATFORM50", **terms), admin)

    for code in ("DHABA50", "PLATFORM50", None):
        order = accepted(until=S.READY, coupon=code, who=make_user())
        rider_steps(db, order.id, rider)
    accepted(who=make_user())  # still cooking: in progress, not in the payout

    report = kitchen.sales(db, restaurant.id, owner)
    food = 3 * (D("240.00") + D("20.00"))  # item + packaging, three delivered orders
    assert report.orders_delivered == 3 and report.orders_in_progress == 1
    assert report.food_sales == food
    assert report.restaurant_discounts == D("50.00")  # the platform paid for PLATFORM50
    commission = ((food - 50) * D("0.20")).quantize(D("0.01"))
    gst = (commission * D("0.18")).quantize(D("0.01"))
    assert (report.commission, report.gst_on_commission) == (commission, gst)
    assert report.estimated_payout == food - 50 - commission - gst
    assert report.top_items[0].name == "Dal Makhani" and report.top_items[0].quantity == 3
    assert report.avg_prep_minutes is not None and report.avg_prep_minutes >= 0


def test_sales_use_the_restaurants_day_not_the_utc_day(db, restaurant, owner, paid):
    late = paid()  # 00:30 IST on 21 Nov is still 20 Nov in UTC
    early = paid()  # 23:50 IST on 20 Nov
    for order, local in ((late, datetime(2026, 11, 21, 0, 30)), (early, datetime(2026, 11, 20, 23, 50))):
        db.execute(
            text("UPDATE orders SET created_at = :t WHERE id = :id"),
            {"t": local.replace(tzinfo=IST), "id": order.id},
        )
    db.commit()
    assert kitchen.sales(db, restaurant.id, owner, date(2026, 11, 21)).orders_in_progress == 1
    assert kitchen.sales(db, restaurant.id, owner, date(2026, 11, 20)).orders_in_progress == 1


def test_missed_orders_are_counted(db, restaurant, owner, paid):
    order = paid()
    db.execute(text("UPDATE orders SET accept_by = now() - interval '1 second' WHERE id = :id"), {"id": order.id})
    db.commit()
    run_timeouts(db)
    report = kitchen.sales(db, restaurant.id, owner)
    assert (report.orders_missed, report.orders_cancelled) == (1, 1)


# ----- restaurant switches -----


def test_owners_list_their_restaurants_and_go_offline(db, restaurant, owner, make_user):
    assert [r.id for r in restaurants.list_mine(db, owner)] == [restaurant.id]
    assert restaurants.list_mine(db, make_user(Role.RESTAURANT_OWNER)) == []
    assert restaurants.set_open(db, restaurant.id, False, owner).is_open is False


# ----- HTTP -----


def _login(client, email):
    from tests.conftest import TEST_PASSWORD

    token = client.post("/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def test_partner_and_rider_endpoints(client, db, restaurant, owner, customer, rider, accepted):
    order = accepted(until=S.READY)
    owner_h, rider_h, cust_h = _login(client, owner.email), _login(client, rider.email), _login(client, customer.email)

    assert [r["id"] for r in client.get("/api/v1/restaurants/mine", headers=owner_h).json()] == [str(restaurant.id)]
    assert client.get("/api/v1/restaurants/mine", headers=cust_h).status_code == 403
    board = client.get(f"/api/v1/restaurants/{restaurant.id}/orders", headers=owner_h).json()
    assert board[0]["id"] == str(order.id)
    assert client.get(f"/api/v1/restaurants/{restaurant.id}/orders?view=everything", headers=owner_h).status_code == 422
    assert client.get(f"/api/v1/restaurants/{restaurant.id}/sales", headers=owner_h).json()["orders_in_progress"] == 1
    assert client.get(f"/api/v1/restaurants/{restaurant.id}/sales", headers=rider_h).status_code == 403
    closed = client.put(f"/api/v1/restaurants/{restaurant.id}/open", json={"is_open": False}, headers=owner_h)
    assert closed.json()["is_open"] is False

    assert client.get("/api/v1/rider/pool", headers=cust_h).status_code == 403
    claimed = client.post(f"/api/v1/orders/{order.id}/claim", headers=rider_h)
    assert claimed.status_code == 200 and claimed.json()["delivery_address"]
    assert client.post(f"/api/v1/orders/{order.id}/claim", headers=rider_h).status_code == 409
    assert client.get(f"/api/v1/orders/{order.id}", headers=owner_h).json()["delivery_code"] is None
    assert client.get("/api/v1/rider/me", headers=rider_h).json()["active"]["id"] == str(order.id)
    bad = client.patch(
        f"/api/v1/orders/{order.id}/status", json={"status": "DELIVERED", "delivery_code": "12"}, headers=rider_h
    )
    assert bad.status_code == 422  # not 4 digits: refused before it counts as a try
    released = client.post(f"/api/v1/orders/{order.id}/release", headers=rider_h)
    assert released.status_code == 200 and released.json()["rider_pay"] is None
