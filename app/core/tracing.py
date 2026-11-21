"""Distributed tracing with OpenTelemetry (Phase 15).

A *trace* is the story of one request: every step it took, in every process,
with timings. Each step is a *span* (an HTTP request, one SQL statement, one
Redis command, the notifier handling an event). Spans know their parent, so
Jaeger can draw them as a tree:

    POST /api/v1/orders                       184 ms   quickserve-api
      SELECT menu_items ... FOR UPDATE          3 ms
      pricing.quote                             9 ms
      INSERT INTO orders ...                    2 ms
      ...
    process order.status_changed               12 ms   quickserve-notifier  (seconds later)
      INSERT INTO notifications ...             2 ms

Logs say WHAT happened, metrics say HOW OFTEN and HOW SLOW on average; a trace
says WHERE the time went for one particular request.

Everything here is optional. With TRACING_ENABLED=false (the default, and in
tests) the OpenTelemetry API hands out do-nothing spans, so the code below
costs almost nothing. And tracing must never take the app down: spans are
exported in a background thread, and if Jaeger is unreachable they're dropped.
"""

import logging
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagators.textmap import DefaultGetter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import Settings, get_settings
from app.core.metrics import SUSPECTED_N_PLUS_ONE

log = logging.getLogger("quickserve.tracing")
tracer = trace.get_tracer("quickserve")

# W3C Trace Context: the standard header that carries a trace from one process
# to the next: "traceparent: 00-<32 hex trace id>-<16 hex span id>-<flags>".
# Every tracing system (Jaeger, Zipkin, AWS X-Ray, Datadog...) understands it.
_propagator = TraceContextTextMapPropagator()
_TRACEPARENT = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def configure_tracing(
    service_name: str, *, app=None, engine: Engine | None = None, settings: Settings | None = None
) -> bool:
    """Start exporting spans for this process. Call once, at startup.

    The exporter reads the standard OpenTelemetry environment variables, so the
    same code works with Jaeger here and any other backend elsewhere:
      OTEL_EXPORTER_OTLP_ENDPOINT   where to send spans (http://jaeger:4318)
      OTEL_TRACES_SAMPLER(_ARG)     how many requests to trace (see the README)
    """
    settings = settings or get_settings()
    if not settings.tracing_enabled:
        return False

    # Imported here: a process with tracing off never loads the SDK or exporter.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "service.namespace": "quickserve",
                "deployment.environment.name": settings.environment,
            }
        )
    )
    # Batch: spans are queued in memory and sent every few seconds from a
    # background thread, never on the request's own time. If the queue fills
    # (Jaeger down), new spans are dropped rather than slowing the app.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    if engine is not None:
        instrument_sql(engine, provider)
    RedisInstrumentor().instrument(tracer_provider=provider)
    if app is not None:
        # Probes and Prometheus scrapes would be thousands of useless traces a day.
        # exclude_spans: no extra span per ASGI "send"/"receive" message (three
        # zero-length "http send" spans on every response, pure noise).
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=provider, excluded_urls="health,metrics", exclude_spans=["send", "receive"]
        )
    log.info("tracing enabled", extra={"fields": {"service": service_name}})
    return True


def current_trace_id() -> str | None:
    """The 32-character trace ID of the current span, for logs and the X-Trace-Id header."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def current_traceparent() -> str | None:
    """The current trace as a traceparent string, to store with an outbox event."""
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


def context_from_traceparent(traceparent: str | None) -> otel_context.Context:
    """The trace context saved with an outbox event, to continue that trace.

    Starts from an EMPTY context, not the current one. The notifier runs its
    polling queries with instrumentation suppressed (see app/notifier.py), and
    that suppression flag lives in the current context; it must not leak into
    the event's own spans.
    """
    if not traceparent or not _TRACEPARENT.match(traceparent):
        return otel_context.Context()
    return _propagator.extract({"traceparent": traceparent}, context=otel_context.Context(), getter=DefaultGetter())


@contextmanager
def continue_trace(traceparent: str | None, name: str, **span_options) -> Iterator[trace.Span]:
    """Run a block as a new span in the trace saved with an outbox event.

    The saved context is ATTACHED (made current) before the span starts, not just
    passed as its parent. Otherwise the span would be a child of the right trace
    but the current context would still carry the notifier's "instrumentation
    suppressed" flag, and the SQL inside the block would vanish from the trace.
    (A test caught exactly that.)
    """
    token = otel_context.attach(context_from_traceparent(traceparent))
    try:
        with tracer.start_as_current_span(name, **span_options) as span:
            yield span
    finally:
        otel_context.detach(token)


# ---------------------------------------------------------------------------
# SQL spans
# ---------------------------------------------------------------------------
# OpenTelemetry's own SQLAlchemy instrumentation declares support for
# SQLAlchemy < 2.1 only; with our 2.1.9 it logs a warning and does nothing. So
# QuickServe traces SQL itself, on SQLAlchemy's cursor events. This is all an
# auto-instrumentation library does: open a span when a statement starts,
# close it when it finishes, mark it failed if it raised.

_TABLE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+\"?([a-z_][a-z0-9_]*)", re.IGNORECASE)
_SPANS = "quickserve.otel_spans"


def instrument_sql(engine: Engine, tracer_provider=None) -> None:
    from opentelemetry.instrumentation.utils import is_instrumentation_enabled

    sql_tracer = trace.get_tracer("quickserve.sql", tracer_provider=tracer_provider)
    url = engine.url
    base = {
        "db.system.name": "postgresql",
        "db.namespace": url.database or "",
        "server.address": url.host or "",
        "server.port": url.port or 5432,
    }

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if not is_instrumentation_enabled():  # suppressed (the notifier's polling)
            return
        words = statement.split(None, 1)
        operation = words[0].upper() if words else "SQL"
        table = _TABLE.search(statement)
        name = f"{operation} {table.group(1)}" if table else operation
        span = sql_tracer.start_span(
            name,
            kind=trace.SpanKind.CLIENT,
            attributes={
                **base,
                "db.operation.name": operation,
                "db.collection.name": table.group(1) if table else "",
                # The statement with placeholders (%(id_1)s), never the values:
                # those can be names, addresses or phone numbers.
                "db.query.text": statement[:2000],
            },
        )
        conn.info.setdefault(_SPANS, []).append(span)

    @event.listens_for(engine, "after_cursor_execute")
    def _end(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        stack = conn.info.get(_SPANS)
        if stack:
            span = stack.pop()
            if cursor.rowcount is not None and cursor.rowcount >= 0:
                span.set_attribute("db.response.returned_rows", cursor.rowcount)
            span.end()

    @event.listens_for(engine, "handle_error")
    def _failed(ctx):
        stack = ctx.connection.info.get(_SPANS) if ctx.connection is not None else None
        if stack:
            span = stack.pop()
            span.record_exception(ctx.original_exception)
            span.set_status(trace.Status(trace.StatusCode.ERROR, type(ctx.original_exception).__name__))
            span.end()


# ---------------------------------------------------------------------------
# N+1 detection
# ---------------------------------------------------------------------------
# The N+1 problem (section 5 of the README): code that runs one query for a list,
# then one more query per item. It works, passes tests, and gets slower with every
# row. A trace shows it as a staircase of identical SQL spans; this detector
# notices it without anyone looking: it counts the statements each request
# runs, and flags a request when the SAME statement runs many times.


@dataclass
class QueryAudit:
    statements: Counter[str] = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.statements.values())

    def most_repeated(self) -> tuple[str, int]:
        if not self.statements:
            return "", 0
        return self.statements.most_common(1)[0]


_audit: ContextVar[QueryAudit | None] = ContextVar("query_audit", default=None)


def install_query_audit(engine: Engine) -> None:
    """Count every statement this engine runs, per request (or per audited block)."""

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        audit = _audit.get()
        if audit is not None:
            # SQLAlchemy sends the statement with placeholders (%(id_1)s), so the
            # same query for different rows has the same text and counts together.
            audit.statements[statement] += 1


@contextmanager
def query_audit() -> Iterator[QueryAudit]:
    audit = QueryAudit()
    token = _audit.set(audit)
    try:
        yield audit
    finally:
        _audit.reset(token)


def report_queries(audit: QueryAudit, route: str, settings: Settings | None = None) -> bool:
    """Put the counts on the request's span; flag a suspected N+1. True if flagged."""
    settings = settings or get_settings()
    statement, repeats = audit.most_repeated()
    span = trace.get_current_span()
    span.set_attribute("db.query_count", audit.total)
    span.set_attribute("db.max_repeated_query", repeats)
    if repeats < settings.n_plus_one_threshold:
        return False
    span.set_attribute("quickserve.n_plus_one", True)
    span.add_event("suspected N+1", {"db.query.text": statement[:500], "db.repeats": repeats})
    SUSPECTED_N_PLUS_ONE.labels(route).inc()
    log.warning(
        "suspected N+1 queries",
        extra={
            "fields": {"route": route, "repeats": repeats, "total_queries": audit.total, "statement": statement[:200]}
        },
    )
    return True
