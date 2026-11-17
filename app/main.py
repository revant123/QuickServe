from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.database.models  # noqa: F401  (registers every model with SQLAlchemy)
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.database.session import engine

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Food ordering and delivery platform: a learning project for backend, DevOps and FinOps.",
    version="0.3.0",
)
app.include_router(api_router)


@app.exception_handler(DomainError)
def domain_error_handler(_: Request, exc: DomainError):
    # The HTTP standard says a 401 should tell the client how to authenticate.
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message}, headers=headers)


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
    to this instance while this fails, but nothing gets restarted."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "not ready", "database": "unreachable"})
    return {"status": "ready", "database": "ok"}
