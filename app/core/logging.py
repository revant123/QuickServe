"""Structured (JSON) logs with a request ID on every line.

Plain-text logs are fine while you watch one terminal. In production there are
many app instances writing thousands of lines a second into a log system
(CloudWatch, Loki, ELK). JSON lines let that system filter and count by field:
"all 500s in the last hour", "every line for request 3f2a...". The request ID
ties together every line one request produced, across modules, and it's
returned to the client in the X-Request-ID header so a support ticket can quote it.

FinOps note: log systems bill by volume ingested and stored. One line per
request plus real events (not every SQL statement) keeps that bill sane.
"""

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from opentelemetry import trace

from app.core.config import get_settings

# A ContextVar is like a global variable that's separate for every request,
# even when many requests run at the same time.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_request_id(incoming: str | None) -> str:
    """Reuse the caller's X-Request-ID if it looks sane (so one ID can follow a
    request through several services); otherwise make a fresh one. Never trust
    arbitrary input into logs: an attacker could inject fake log lines."""
    if incoming and _SAFE_REQUEST_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            line["request_id"] = request_id
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            line["trace_id"] = trace_id
        fields = getattr(record, "fields", None)
        if fields:
            line.update(fields)
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        request_id = getattr(record, "request_id", None)
        fields = getattr(record, "fields", None) or {}
        extras = " ".join(f"{k}={v}" for k, v in fields.items())
        out = " ".join(part for part in (base, extras, f"request_id={request_id}" if request_id else "") if part)
        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)
        return out


_default_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    # Stamp the request ID onto the record the moment it's CREATED, inside the
    # request. Reading the ContextVar later, when the line is formatted, goes wrong
    # as soon as formatting happens elsewhere (a background log-shipping thread,
    # or a test that inspects records afterwards).
    record = _default_record_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    # Phase 15: the trace ID too, so a log line leads straight to its trace in
    # Jaeger, and a slow trace leads to its log lines.
    span = trace.get_current_span().get_span_context()
    record.trace_id = format(span.trace_id, "032x") if span.is_valid else None
    return record


def configure_logging() -> None:
    logging.setLogRecordFactory(_record_factory)
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_json else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
    # Our middleware writes one structured line per request, so uvicorn's own
    # plain-text access log would only duplicate it (and double the log bill).
    logging.getLogger("uvicorn.access").disabled = True


def log_event(logger: logging.Logger, level: int, message: str, **fields) -> None:
    """logger.info("x", extra={"fields": {...}}) with less typing."""
    logger.log(level, message, extra={"fields": fields})
