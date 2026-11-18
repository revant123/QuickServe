"""Phase 12: ratings and reviews. Who may review, once, and totals that stay right under concurrency."""

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import Conflict, NotFound, Unprocessable
from app.database.session import SessionLocal
from app.modules.orders.model import OrderStatus as S
from app.modules.orders.model import OrderStatusEvent
from app.modules.orders.service import change_status, place_order
from app.modules.payments.schema import SimulatedOutcome
from app.modules.payments.service import pay
from app.modules.restaurants.model import Restaurant
from app.modules.reviews.schema import ReviewCreate
from app.modules.reviews.service import create_review, recompute_ratings, restaurant_reviews
from app.modules.users.model import Role
from tests.conftest import TEST_PASSWORD
from tests.helpers import order_payload


@pytest.fixture
def deliver(db, restaurant, make_item, owner, rider):
    """Place, pay and deliver an order for `customer`. Returns the order."""
    item = make_item("Dal Makhani", "240.00", stock=100)

    def _deliver(customer, until=S.DELIVERED):
        order = place_order(db, order_payload(restaurant, (item, 1)), customer)
        pay(db, order.id, f"key-{order.id}", SimulatedOutcome.success, customer)
        steps = [
            (S.ACCEPTED, owner),
            (S.PREPARING, owner),
            (S.READY, owner),
            (S.OUT_FOR_DELIVERY, rider),
            (S.DELIVERED, rider),
        ]
        for status, actor in steps:
            change_status(db, order.id, status, actor)
            if status is until:
                break
        db.refresh(order)
        return order

    return _deliver


def totals(db, restaurant):
    db.refresh(restaurant)
    return restaurant.rating_count, restaurant.rating_sum


def stars(n, comment=""):
    return ReviewCreate(rating=n, comment=comment)


def test_a_customer_rates_their_delivered_order(db, restaurant, customer, deliver):
    order = deliver(customer)
    review = create_review(db, order.id, stars(4, "  Hot and fresh  "), customer)
    assert review.rating == 4 and review.comment == "Hot and fresh"
    assert review.reviewer == "User"  # first name only ("User 1" in tests)
    assert totals(db, restaurant) == (1, 4)
    assert restaurant.rating is None  # "New" until 3 reviews


def test_rating_appears_after_enough_reviews(db, restaurant, make_user, deliver):
    for n in (5, 4, 4):
        c = make_user(Role.CUSTOMER)
        create_review(db, deliver(c).id, stars(n), c)
    assert totals(db, restaurant) == (3, 13)
    assert restaurant.rating == Decimal("4.3")


def test_only_after_delivery(db, customer, deliver):
    order = deliver(customer, until=S.OUT_FOR_DELIVERY)
    with pytest.raises(Unprocessable, match="delivered"):
        create_review(db, order.id, stars(5), customer)


def test_only_your_own_order(db, customer, make_user, owner, deliver):
    order = deliver(customer)
    stranger = make_user(Role.CUSTOMER)
    for who in (stranger, owner):
        with pytest.raises(NotFound):  # 404: don't even confirm the order exists
            create_review(db, order.id, stars(1), who)


def test_only_once_per_order(db, restaurant, customer, deliver):
    order = deliver(customer)
    create_review(db, order.id, stars(5), customer)
    before = REGISTRY.get_sample_value("quickserve_reviews_total", {"stars": "1"}) or 0
    with pytest.raises(Conflict, match="already reviewed"):
        create_review(db, order.id, stars(1), customer)
    assert totals(db, restaurant) == (1, 5)  # the failed review moved nothing
    assert (REGISTRY.get_sample_value("quickserve_reviews_total", {"stars": "1"}) or 0) == before


def test_reviews_close_after_the_window(db, customer, deliver):
    order = deliver(customer)
    db.execute(
        update(OrderStatusEvent)
        .where(OrderStatusEvent.order_id == order.id, OrderStatusEvent.to_status == S.DELIVERED)
        .values(created_at=text("now() - interval '8 days'"))
    )
    db.commit()
    with pytest.raises(Unprocessable, match="7 days"):
        create_review(db, order.id, stars(5), customer)


def test_the_database_refuses_impossible_totals(db, restaurant):
    # 1 review can't add up to 6 stars: the CHECK constraint stops a buggy update.
    with pytest.raises(IntegrityError, match="rating_totals_consistent"):
        db.execute(update(Restaurant).where(Restaurant.id == restaurant.id).values(rating_count=1, rating_sum=6))
        db.flush()
    db.rollback()


# ---------- Concurrency ----------


def _run_concurrently(n, fn):
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def test_ten_reviews_at_once_are_all_counted(db, restaurant, make_user, deliver):
    """The lost-update race. With "count = count + 1" computed in Python, two
    reviews that read the same old count both write count + 1, and one is lost.
    The atomic UPDATE makes PostgreSQL do the arithmetic on the latest value."""
    customers = [make_user(Role.CUSTOMER) for _ in range(10)]
    orders = [deliver(c) for c in customers]
    ratings = [5, 4, 3, 5, 2, 4, 5, 1, 3, 4]

    def review(i):
        with SessionLocal() as session:
            create_review(session, orders[i].id, stars(ratings[i]), customers[i])

    _run_concurrently(10, review)
    assert totals(db, restaurant) == (10, sum(ratings))
    assert recompute_ratings(db).restaurants_corrected == 0


def test_double_tap_on_submit_counts_once(db, restaurant, customer, deliver):
    order = deliver(customer)

    def review(_):
        with SessionLocal() as session:
            try:
                create_review(session, order.id, stars(5), customer)
                return "ok"
            except Conflict:
                return "duplicate"

    results = _run_concurrently(5, review)
    assert sorted(results) == ["duplicate"] * 4 + ["ok"]
    assert totals(db, restaurant) == (1, 5)


# ---------- Reconciliation ----------


def test_recompute_finds_and_fixes_drift(db, restaurant, customer, make_user, deliver, owner):
    create_review(db, deliver(customer).id, stars(4), customer)
    # Simulate a bug (or a manual edit) that left the totals wrong.
    db.execute(update(Restaurant).where(Restaurant.id == restaurant.id).values(rating_count=2, rating_sum=9))
    db.commit()
    report = recompute_ratings(db)
    assert report.restaurants_checked == 1 and report.restaurants_corrected == 1
    assert totals(db, restaurant) == (1, 4)
    assert recompute_ratings(db).restaurants_corrected == 0  # nothing left to fix


# ---------- Reading ----------


def test_restaurant_reviews_newest_first_with_distribution(db, restaurant, make_user, deliver):
    for n, comment in [(5, "first"), (3, "second"), (5, "third")]:
        c = make_user(Role.CUSTOMER)
        create_review(db, deliver(c).id, stars(n, comment), c)
    page = restaurant_reviews(db, restaurant.id, limit=2, offset=0)
    assert page.rating == Decimal("4.3") and page.rating_count == 3
    assert page.distribution == {5: 2, 4: 0, 3: 1, 2: 0, 1: 0}
    assert [r.comment for r in page.reviews] == ["third", "second"]


# ---------- HTTP ----------


def login(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_review_endpoints(client, restaurant, customer, admin, deliver):
    order = deliver(customer)
    h = login(client, customer.email)
    url = f"/api/v1/orders/{order.id}/review"
    assert client.post(url, json={"rating": 6}, headers=h).status_code == 422
    assert client.post(url, json={"rating": 4, "comment": "x" * 501}, headers=h).status_code == 422
    assert client.post(url, json={"rating": 4}).status_code == 401
    r = client.post(url, json={"rating": 4, "comment": "Good dal"}, headers=h)
    assert r.status_code == 201, r.text
    assert client.post(url, json={"rating": 4}, headers=h).status_code == 409

    r = client.get(f"/api/v1/restaurants/{restaurant.id}/reviews")
    assert r.status_code == 200 and r.json()["reviews"][0]["comment"] == "Good dal"
    assert r.json()["distribution"]["4"] == 1

    job = "/api/v1/admin/jobs/recompute-ratings"
    assert client.post(job, headers=h).status_code == 403
    assert client.post(job, headers=login(client, admin.email)).json()["restaurants_corrected"] == 0
