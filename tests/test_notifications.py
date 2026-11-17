"""The outbox pattern and the notifier: nothing lost, nothing duplicated, in order."""

import threading
from datetime import timedelta

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import func, select, text, update

from app import notifier
from app.core.exceptions import OutOfStock
from app.modules.notifications.model import Notification
from app.modules.notifications.templates import UnknownEvent, messages_for
from app.modules.orders import service as orders
from app.modules.orders.model import OrderStatus
from app.modules.outbox import service as outbox
from app.modules.outbox.model import OutboxEvent
from app.modules.payments import service as payments
from app.modules.payments.schema import SimulatedOutcome
from tests.conftest import TEST_PASSWORD
from tests.helpers import order_payload


def events(db) -> list[OutboxEvent]:
    db.expire_all()
    return list(db.execute(select(OutboxEvent).order_by(OutboxEvent.id)).scalars())


def notes_for(db, user) -> list[Notification]:
    db.expire_all()
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at, Notification.event_id)
    )
    return list(db.execute(stmt).scalars())


def paid_order(db, restaurant, customer, make_item, key="pay-0001"):
    order = orders.place_order(db, order_payload(restaurant, (make_item(stock=5), 2)), customer)
    payments.pay(db, order.id, key, SimulatedOutcome.success, customer)
    return order


# ---------- Writing events: the same transaction as the change ----------


def test_placing_an_order_writes_an_event_in_the_same_transaction(db, restaurant, customer, make_item, owner):
    order = orders.place_order(db, order_payload(restaurant, (make_item(stock=5), 2)), customer)
    [event] = events(db)
    assert event.event_type == "order.placed" and event.aggregate_id == order.id
    p = event.payload
    assert p["customer_id"] == str(customer.id) and p["owner_id"] == str(owner.id)
    assert p["restaurant_name"] == "Sharma Dhaba" and p["item_count"] == 2 and p["status"] == "PLACED"
    assert event.published_at is None  # waiting for the notifier


def test_a_failed_order_writes_no_event(db, restaurant, customer, make_item):
    item = make_item(stock=1)
    with pytest.raises(OutOfStock):
        orders.place_order(db, order_payload(restaurant, (item, 3)), customer)
    assert events(db) == []  # rolled back together with the order: no phantom notification


def test_every_status_change_writes_an_event(db, restaurant, customer, make_item, owner):
    order = paid_order(db, restaurant, customer, make_item)
    orders.change_status(db, order.id, OrderStatus.ACCEPTED, owner)
    assert [(e.event_type, e.payload["status"], e.payload["previous_status"]) for e in events(db)] == [
        ("order.placed", "PLACED", None),
        ("order.status_changed", "PAID", "PLACED"),
        ("order.status_changed", "ACCEPTED", "PAID"),
    ]


# ---------- Delivering them ----------


def test_notifier_turns_events_into_notifications(db, restaurant, customer, make_item, owner):
    order = paid_order(db, restaurant, customer, make_item)
    report = notifier.run_once()
    assert report.published == 2 and report.retried == 0

    assert [n.title for n in notes_for(db, customer)] == ["Order placed", "Payment received"]
    [for_owner] = notes_for(db, owner)  # the restaurant hears only about the PAID order
    assert for_owner.kind == "order.new_for_restaurant" and for_owner.order_id == order.id
    assert all(e.published_at is not None for e in events(db))

    assert notifier.run_once().handled == 0  # nothing left


def test_redelivery_never_duplicates_a_notification(db, restaurant, customer, make_item):
    paid_order(db, restaurant, customer, make_item)
    notifier.run_once()
    # Simulate at-least-once delivery: the notifier crashed after handling the
    # events but before recording that, so they are delivered again.
    db.execute(update(OutboxEvent).values(published_at=None))
    db.commit()
    report = notifier.run_once()
    assert report.published == 2 and report.notifications == []  # handled again, nothing new
    assert len(notes_for(db, customer)) == 2


def test_events_of_one_order_are_delivered_in_order_even_after_a_failure(
    db, restaurant, customer, make_item, owner, monkeypatch
):
    order = paid_order(db, restaurant, customer, make_item)
    orders.change_status(db, order.id, OrderStatus.ACCEPTED, owner)

    real = notifier.handle_event

    def flaky(session, event):
        if event.payload["status"] == "PAID":
            raise ConnectionError("push provider timed out")
        return real(session, event)

    monkeypatch.setattr(notifier, "handle_event", flaky)
    report = notifier.run_once()
    # "Order placed" went out; "PAID" failed; "ACCEPTED" must WAIT behind it.
    assert (report.published, report.retried) == (1, 1)
    assert [n.title for n in notes_for(db, customer)] == ["Order placed"]
    paid_event = events(db)[1]
    assert paid_event.attempts == 1 and "push provider timed out" in paid_event.last_error

    # The provider recovers; once the retry delay has passed, both go out in order.
    monkeypatch.setattr(notifier, "handle_event", real)
    db.execute(update(OutboxEvent).values(available_at=func.now()))
    db.commit()
    notifier.run_once()
    notifier.run_once()
    assert [n.title for n in notes_for(db, customer)] == [
        "Order placed",
        "Payment received",
        "Sharma Dhaba accepted your order",
    ]


def test_a_failure_waits_longer_each_time(db, restaurant, customer, make_item, monkeypatch):
    orders.place_order(db, order_payload(restaurant, (make_item(stock=5), 1)), customer)
    monkeypatch.setattr(notifier, "handle_event", lambda *_: (_ for _ in ()).throw(RuntimeError("down")))
    notifier.run_once()
    [event] = events(db)
    wait = db.execute(select(OutboxEvent.available_at - func.now())).scalar_one()
    assert timedelta(seconds=1) < wait <= timedelta(seconds=2)  # first retry in ~2 s
    assert outbox.retry_delay(3) == timedelta(seconds=8)
    assert outbox.retry_delay(20) == timedelta(minutes=5)  # capped
    assert notifier.run_once().handled == 0  # not due yet: not retried early


def test_after_max_attempts_an_event_is_dead_lettered(db, restaurant, customer, make_item):
    orders.place_order(db, order_payload(restaurant, (make_item(stock=5), 1)), customer)
    db.execute(update(OutboxEvent).values(event_type="order.teleported"))  # a type nobody understands
    db.commit()
    for _ in range(5):
        db.execute(update(OutboxEvent).values(available_at=func.now()))
        db.commit()
        notifier.run_once()
    [event] = events(db)
    assert event.dead_at is not None and event.attempts == 5 and "order.teleported" in event.last_error
    assert notifier.run_once().handled == 0  # never retried again; a human looks at it
    notifier.housekeeping()
    assert REGISTRY.get_sample_value("quickserve_outbox_dead_events") == 1


def test_a_dead_event_does_not_block_its_order_forever(db, restaurant, customer, make_item, owner):
    order = paid_order(db, restaurant, customer, make_item)
    db.execute(update(OutboxEvent).where(OutboxEvent.payload["status"].astext == "PLACED").values(dead_at=func.now()))
    db.commit()
    notifier.run_once()
    assert [n.title for n in notes_for(db, customer)] == ["Payment received"]
    assert order.id


def test_two_notifiers_at_once_deliver_each_event_once(db, restaurant, customer, make_item):
    for i in range(6):
        orders.place_order(db, order_payload(restaurant, (make_item(name=f"Dish {i}", stock=5), 1)), customer)
    reports = []
    threads = [threading.Thread(target=lambda: reports.append(notifier.run_once())) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r.published for r in reports) == 6  # SKIP LOCKED: no event taken twice
    assert len(notes_for(db, customer)) == 6


def test_delivered_events_are_deleted_after_the_retention_period(db, restaurant, customer, make_item):
    paid_order(db, restaurant, customer, make_item)
    notifier.run_once()
    db.execute(text("UPDATE outbox_events SET published_at = now() - interval '8 days' WHERE id = 1"))
    db.commit()
    assert notifier.housekeeping() == 1
    assert len(events(db)) == 1
    assert len(notes_for(db, customer)) == 2  # the notifications themselves stay


def test_backlog_gauges(db, restaurant, customer, make_item):
    paid_order(db, restaurant, customer, make_item)
    notifier.housekeeping()
    assert REGISTRY.get_sample_value("quickserve_outbox_pending_events") == 2
    notifier.run_once()
    notifier.housekeeping()
    assert REGISTRY.get_sample_value("quickserve_outbox_pending_events") == 0
    assert REGISTRY.get_sample_value("quickserve_outbox_oldest_pending_age_seconds") == 0


# ---------- What people are told ----------

PAYLOAD = {
    "order_id": "o",
    "customer_id": "c",
    "owner_id": "r",
    "restaurant_name": "Pal Dhaba",
    "grand_total": "540.00",
    "item_count": 2,
    "note": None,
}


@pytest.mark.parametrize(
    ("status", "previous", "who"),
    [
        ("ACCEPTED", "PAID", ["c"]),
        ("PREPARING", "ACCEPTED", ["c"]),
        ("OUT_FOR_DELIVERY", "READY", ["c"]),
        ("DELIVERED", "OUT_FOR_DELIVERY", ["c"]),
        ("REJECTED", "PAID", ["c"]),
        ("PAYMENT_FAILED", "PLACED", ["c"]),
        ("CANCELLED", "PLACED", ["c"]),  # never paid: the restaurant never knew about it
        ("CANCELLED", "PAID", ["c", "r"]),  # paid: the restaurant must stop cooking
    ],
)
def test_who_is_told_about_each_status(status, previous, who):
    msgs = messages_for("order.status_changed", {**PAYLOAD, "status": status, "previous_status": previous})
    assert [m.user_id for m in msgs] == who


def test_refund_is_mentioned_only_when_money_was_taken():
    paid = messages_for("order.status_changed", {**PAYLOAD, "status": "CANCELLED", "previous_status": "PAID"})
    unpaid = messages_for("order.status_changed", {**PAYLOAD, "status": "CANCELLED", "previous_status": "PLACED"})
    assert "refund of ₹540" in paid[0].body and "refund" not in unpaid[0].body


def test_unknown_event_types_are_refused():
    with pytest.raises(UnknownEvent):
        messages_for("order.teleported", PAYLOAD)


# ---------- The API ----------


def _login(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_api_shows_only_my_notifications_and_marks_them_read(client, db, restaurant, customer, make_item, owner):
    paid_order(db, restaurant, customer, make_item)
    notifier.run_once()
    me, them = _login(client, customer.email), _login(client, owner.email)

    mine = client.get("/api/v1/notifications", headers=me).json()
    assert [n["title"] for n in mine] == ["Payment received", "Order placed"]  # newest first
    assert len(client.get("/api/v1/notifications", headers=them).json()) == 1

    read = client.post(f"/api/v1/notifications/{mine[0]['id']}/read", headers=me)
    assert read.status_code == 200 and read.json()["read_at"] is not None
    assert len(client.get("/api/v1/notifications?unread_only=true", headers=me).json()) == 1

    # Someone else's notification: 404, not 403 (don't confirm it exists).
    assert client.post(f"/api/v1/notifications/{mine[1]['id']}/read", headers=them).status_code == 404
    assert client.get("/api/v1/notifications").status_code == 401


# ---------- The notifier process ----------


def test_notifier_loop_delivers_then_stops_cleanly(db, restaurant, customer, make_item):
    from app.core.config import Settings

    paid_order(db, restaurant, customer, make_item)
    settings = Settings(notifier_interval_seconds=0.05, notifier_metrics_port=0)
    notifier.stop_requested.clear()
    t = threading.Thread(target=notifier.run_forever, args=(settings,))
    t.start()
    for _ in range(100):  # up to ~5 s
        if len(notes_for(db, customer)) == 2:
            break
        threading.Event().wait(0.05)
    notifier.stop_requested.set()  # what SIGTERM does
    t.join(timeout=5)
    assert not t.is_alive()
    assert len(notes_for(db, customer)) == 2
    notifier.stop_requested.clear()


def test_notifier_healthcheck_reads_its_own_heartbeat():
    import socket
    import time

    from app.core.metrics import NOTIFIER_LAST_RUN, start_metrics_server
    from app.worker import healthcheck

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    start_metrics_server(port, "test")
    NOTIFIER_LAST_RUN.set(time.time())
    assert healthcheck(port, 60, notifier.HEARTBEAT_METRIC)
    NOTIFIER_LAST_RUN.set(time.time() - 3600)
    assert not healthcheck(port, 60, notifier.HEARTBEAT_METRIC)
