import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.database.models  # noqa: F401  (registers every model with SQLAlchemy)
from app.api.router import api_router
from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.exceptions import DomainError, TooManyRequests
from app.core.logging import configure_logging, log_event, new_request_id, request_id_var
from app.core.metrics import HTTP_DURATION, HTTP_REQUESTS, route_label, start_metrics_server, track_db_pool
from app.core.redis import redis_is_up
from app.database.session import engine

VERSION = "0.5.0"
settings = get_settings()
configure_logging()
log = logging.getLogger("quickserve.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Prometheus metrics on their own port (9100), not on the public API port.
    if start_metrics_server(settings.metrics_port, VERSION):
        log_event(log, logging.INFO, "metrics server started", port=settings.metrics_port)
    track_db_pool(engine)
    yield


app = FastAPI(
    title=settings.app_name,
    description="Food ordering and delivery platform: a learning project for backend, DevOps and FinOps.",
    version=VERSION,
    lifespan=lifespan,
)
app.include_router(api_router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Runs around every request: give it an ID, time it, write one log line."""
    request_id = new_request_id(request.headers.get("X-Request-ID"))
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Anything nobody handled. Log the full error for us, but give the client
        # only the request ID: stack traces can leak file paths, SQL and secrets.
        log.exception("unhandled error", extra={"fields": {"path": request.url.path}})
        response = JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
    duration = time.perf_counter() - started
    duration_ms = round(duration * 1000, 1)
    response.headers["X-Request-ID"] = request_id

    # Label by the route TEMPLATE ("/api/v1/orders/{order_id}"), never the real
    # path: one time series per route, not one per order ID.
    route = route_label(request.scope)
    HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    HTTP_DURATION.labels(request.method, route).observe(duration)

    log_event(
        log,
        logging.WARNING if response.status_code >= 500 else logging.INFO,
        "request",
        method=request.method,
        path=request.url.path,  # path only: query strings can contain personal data
        status=response.status_code,
        client_ip=client_ip(request),  # the real client, also behind the gateway
        duration_ms=duration_ms,
    )
    request_id_var.reset(token)
    return response


@app.exception_handler(DomainError)
def domain_error_handler(_: Request, exc: DomainError):
    headers = {}
    if exc.status_code == 401:
        # The HTTP standard says a 401 should tell the client how to authenticate.
        headers["WWW-Authenticate"] = "Bearer"
    if isinstance(exc, TooManyRequests):
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message}, headers=headers or None)


@app.get("/", tags=["health"])
def home():
    return {"message": "Welcome to QuickServe!", "docs": "/docs"}


@app.get("/health", tags=["health"])
def liveness():
    """Liveness: is the process up? Kubernetes restarts the container if this fails.
    Deliberately does NOT touch the database: a DB outage should not make
    Kubernetes kill every healthy app container in a restart loop."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def readiness():
    """Readiness: can we serve traffic? The load balancer stops sending requests
    to this instance while this fails, but nothing gets restarted.

    Only the database decides readiness. Redis is reported, but if it's down we
    still serve traffic (menus come from PostgreSQL, login protection pauses), so
    taking every instance out of the load balancer would turn a small problem
    into a full outage."""
    redis_status = "ok" if redis_is_up() else "down (degraded: no cache, no login rate limits)"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503, content={"status": "not ready", "database": "unreachable", "redis": redis_status}
        )
    return {"status": "ready", "database": "ok", "redis": redis_status}
