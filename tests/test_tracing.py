"""Phase 15: tracing. Spans go to an in-memory exporter instead of Jaeger.

The rest of the suite runs with tracing off (the default). This module turns
it on for the API app and the test engine, and turns it off again afterwards.
"""

import logging

import pytest
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app import notifier, worker
from app.core import tracing
from app.core.config import Settings
from app.core.metrics import SUSPECTED_N_PLUS_ONE
from app.database.session import SessionLocal, engine
from app.main import app
from app.modules.outbox.model import OutboxEvent
from tests.conftest import SECTOR_22, TEST_PASSWORD

EXPORTER = InMemorySpanExporter()
PROVIDER = TracerProvider()
PROVIDER.add_span_processor(SimpleSpanProcessor(EXPORTER))


@pytest.fixture(scope="module", autouse=True)
def traced():
    # The global provider can only be set once per process; later modules just
    # send their few manual spans into the in-memory exporter.
    trace.set_tracer_provider(PROVIDER)
    tracing.instrument_sql(engine, PROVIDER)
    # Earlier tests have already built the app's middleware stack; in production
    # tracing is set up before the first request. Drop it so it's rebuilt with
    # the tracing middleware, exactly as in production.
    app.middleware_stack = None
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=PROVIDER, excluded_urls="health,metrics", exclude_spans=["send", "receive"]
    )
    yield
    FastAPIInstrumentor.uninstrument_app(app)
    app.middleware_stack = None
    # Our SQL listeners stay attached, but with no span they cost one dict lookup.


@pytest.fixture(autouse=True)
def fresh_spans():
    EXPORTER.clear()
    yield
    EXPORTER.clear()


def spans_in(trace_id: int):
    return [s for s in EXPORTER.get_finished_spans() if s.context.trace_id == trace_id]


def _login(client, email):
    token = client.post("/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


# ----- requests -----


def test_a_request_is_one_trace_with_its_sql_inside_and_the_id_in_the_response(client, restaurant, caplog):
    caplog.set_level(logging.INFO, logger="quickserve.http")
    response = client.get("/api/v1/restaurants/near", params=SECTOR_22)
    assert response.status_code == 200

    [server] = [s for s in EXPORTER.get_finished_spans() if s.kind is SpanKind.SERVER]
    trace_id = format(server.context.trace_id, "032x")
    assert response.headers["X-Trace-Id"] == trace_id

    sql = [
        s
        for s in spans_in(server.context.trace_id)
        if s.attributes.get("db.system.name", s.attributes.get("db.system"))
    ]
    assert sql, "SQL statements should be spans in the request's trace"
    assert server.attributes["db.query_count"] >= len(sql) >= 1

    [line] = [r for r in caplog.records if r.getMessage() == "request"]
    assert line.trace_id == trace_id  # logs and traces point at each other
    assert line.fields["queries"] == server.attributes["db.query_count"]


def test_health_checks_are_not_traced(client):
    client.get("/health")
    assert [s.name for s in EXPORTER.get_finished_spans()] == []


def test_a_server_error_is_marked_on_the_trace(client, monkeypatch):
    from app.modules.pricing import router as pricing_router

    def broken(*_args, **_kwargs):
        raise RuntimeError("pricing exploded")

    monkeypatch.setattr(pricing_router, "get_settings", broken)
    response = client.get("/api/v1/pricing")
    assert response.status_code == 500 and "X-Trace-Id" in response.headers
    [server] = [s for s in EXPORTER.get_finished_spans() if s.kind is SpanKind.SERVER]
    assert server.status.status_code is StatusCode.ERROR


# ----- across the outbox -----


def test_the_notifier_continues_the_trace_of_the_request_that_wrote_the_event(
    client, db, restaurant, customer, make_item
):
    item = make_item("Dal Makhani", "240.00", stock=10)
    headers = _login(client, customer.email)
    body = {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "delivery_address": "House 12, Sector 22-B",
        "delivery_location": SECTOR_22,
    }
    order = client.post("/api/v1/orders", json=body, headers=headers)
    assert order.status_code == 201
    pay = client.post(
        f"/api/v1/orders/{order.json()['id']}/payments",
        headers={**headers, "Idempotency-Key": "trace-test-1"},
    )
    assert pay.status_code == 201
    pay_trace = int(pay.headers["X-Trace-Id"], 16)

    # The event row carries the paying request's trace.
    event = db.execute(select(OutboxEvent).order_by(OutboxEvent.id.desc())).scalars().first()
    assert event.trace_parent.split("-")[1] == pay.headers["X-Trace-Id"]

    EXPORTER.clear()
    notifier.run_once(Settings())
    finished = EXPORTER.get_finished_spans()

    consumers = [s for s in finished if s.kind is SpanKind.CONSUMER]
    paid = [s for s in consumers if s.context.trace_id == pay_trace]
    assert len(paid) == 1, "one consumer span, in the paying request's trace"
    assert paid[0].name == "process order.status_changed"
    assert paid[0].parent.span_id == int(event.trace_parent.split("-")[2], 16)
    assert paid[0].attributes["quickserve.event.wait_ms"] >= 0

    # Its SQL is inside it; the polling queries weren't traced at all.
    children = [s for s in finished if s.parent and s.parent.span_id == paid[0].context.span_id]
    assert any("notifications" in s.name or "INSERT" in s.name for s in children)
    assert all(s.parent is not None for s in finished), "no stray root spans from polling"


def test_a_failing_event_is_an_error_on_its_trace(client, db, restaurant, customer, make_item, monkeypatch):
    item = make_item("Dal Makhani", "240.00", stock=10)
    headers = _login(client, customer.email)
    body = {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        "delivery_address": "House 12, Sector 22-B",
        "delivery_location": SECTOR_22,
    }
    client.post("/api/v1/orders", json=body, headers=headers)

    def boom(*_args):
        raise RuntimeError("SMS provider down")

    monkeypatch.setattr(notifier, "handle_event", boom)
    EXPORTER.clear()
    notifier.run_once(Settings())
    [span] = [s for s in EXPORTER.get_finished_spans() if s.kind is SpanKind.CONSUMER]
    assert span.status.status_code is StatusCode.ERROR
    assert span.events[0].name == "exception"


def test_bad_or_missing_traceparents_start_a_new_trace():
    for value in (None, "", "not-a-traceparent", "00-xyz-abc-01"):
        assert trace.get_current_span(tracing.context_from_traceparent(value)).get_span_context().is_valid is False
    good = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    restored = trace.get_current_span(tracing.context_from_traceparent(good)).get_span_context()
    assert format(restored.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_the_worker_traces_each_pass(db):
    worker.run_once()
    [span] = [s for s in EXPORTER.get_finished_spans() if s.name == "worker.timeouts"]
    assert span.attributes["quickserve.orders.auto_rejected"] == 0
    assert any(s.parent and s.parent.span_id == span.context.span_id for s in EXPORTER.get_finished_spans())


def test_pricing_has_its_own_span_with_the_numbers(client, restaurant, customer, make_item):
    item = make_item("Dal Makhani", "240.00", stock=10)
    body = {
        "restaurant_id": str(restaurant.id),
        "items": [{"menu_item_id": str(item.id), "quantity": 2}],
        "delivery_address": "House 12",
        "delivery_location": SECTOR_22,
    }
    response = client.post("/api/v1/orders/quote", json=body, headers=_login(client, customer.email))
    assert response.status_code == 200
    [span] = [s for s in EXPORTER.get_finished_spans() if s.name == "pricing.bill"]
    assert span.attributes["quickserve.item_total"] == 480.0
    assert span.attributes["quickserve.grand_total"] == float(response.json()["grand_total"])


# ----- the N+1 detector -----


def test_sql_spans_carry_the_statement_but_not_the_values(db):
    with tracing.tracer.start_as_current_span("test"):
        db.execute(text("SELECT :secret AS x"), {"secret": "9876543210"})
    [sql] = [s for s in EXPORTER.get_finished_spans() if s.attributes.get("db.system.name") == "postgresql"]
    assert "9876543210" not in str(sql.attributes)


def test_the_same_statement_many_times_is_flagged(db, caplog):
    caplog.set_level(logging.WARNING, logger="quickserve.tracing")
    before = SUSPECTED_N_PLUS_ONE.labels("/test")._value.get()
    with tracing.query_audit() as audit:
        for i in range(12):  # one query per "row": the N+1 shape
            db.execute(text("SELECT :i"), {"i": i})
    assert audit.most_repeated()[1] == 12
    assert tracing.report_queries(audit, "/test", Settings(n_plus_one_threshold=10)) is True
    assert SUSPECTED_N_PLUS_ONE.labels("/test")._value.get() == before + 1
    assert "suspected N+1" in caplog.text


def test_many_different_statements_are_not_an_n_plus_one(db):
    with tracing.query_audit() as audit:
        for i in range(12):
            db.execute(text(f"SELECT {i} AS col_{i}"))
    assert audit.total == 12 and audit.most_repeated()[1] == 1
    assert tracing.report_queries(audit, "/test", Settings(n_plus_one_threshold=10)) is False


def test_tracing_stays_off_unless_enabled():
    assert tracing.configure_tracing("quickserve-test", settings=Settings(tracing_enabled=False)) is False


def test_a_failing_statement_is_a_failed_sql_span(db):
    with tracing.tracer.start_as_current_span("test"):
        with pytest.raises(ProgrammingError):
            db.execute(text("SELECT * FROM no_such_table"))
    db.rollback()
    [sql] = [s for s in EXPORTER.get_finished_spans() if s.attributes.get("db.system.name") == "postgresql"]
    assert sql.name == "SELECT no_such_table"
    assert sql.status.status_code is StatusCode.ERROR


def test_paying_reads_the_order_items_once(db, restaurant, customer, make_item):
    """A trace showed order_items read twice per payment; now only under the lock."""
    from app.modules.orders.service import place_order
    from app.modules.payments.schema import SimulatedOutcome
    from app.modules.payments.service import pay
    from tests.helpers import order_payload

    order = place_order(db, order_payload(restaurant, (make_item(stock=5), 1)), customer)
    with SessionLocal() as fresh, tracing.query_audit() as audit:  # a new session, like a new request
        pay(fresh, order.id, "trace-pay-once", SimulatedOutcome.success, fresh.get(type(customer), customer.id))
    reads = sum(n for statement, n in audit.statements.items() if "FROM order_items" in statement)
    assert reads == 1
