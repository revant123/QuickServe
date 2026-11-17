"""Application settings.

Every value that changes between environments (local, CI, staging, prod) or that
the business changes over time (fees, tax rates, timeouts) lives here, read
from environment variables or a .env file. Nothing like this is hard-coded in
business logic.

Why? Twelve-factor config: the same Docker image runs everywhere, and only the
environment differs. It is also a FinOps habit: a fee or timeout you can change
without a redeploy is cheaper to operate.
"""

from decimal import Decimal
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-before-deploying"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "QuickServe API"
    environment: str = "local"

    # postgresql+psycopg:// selects the psycopg 3 driver. A bare postgresql://
    # URL would make SQLAlchemy look for the older psycopg2 driver.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5434/quickserve"

    # Print every SQL statement SQLAlchemy sends. Turn this on while learning.
    sql_echo: bool = False

    # --- Login tokens (JWT) ---
    # Anyone who knows this secret can create valid tokens for ANY user, so in a
    # real deployment it comes from a secrets manager, never from Git.
    # Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # --- Redis (Phase 4): cache, login rate limits, logged-out tokens ---
    # Host port 6380, not the default 6379, so it can't collide with another
    # project's Redis on the same machine (same idea as PostgreSQL on 5434).
    redis_url: str = "redis://localhost:6380/0"
    # If Redis is slow or down, give up quickly instead of making every request
    # wait. Every Redis feature here degrades gracefully without it.
    redis_timeout_seconds: float = 0.5

    # Customer menu cache. Short on purpose: stock badges ("Only 3 left") may be
    # this many seconds old. Ordering is never affected, because the order itself
    # always checks stock in PostgreSQL.
    menu_cache_ttl_seconds: int = 10

    # Failed logins allowed per window before answering 429 Too Many Requests.
    login_max_failures_per_email: int = 5
    login_max_failures_per_ip: int = 20
    login_failure_window_seconds: int = 900

    # Background worker: how often to run the order timeout job.
    worker_interval_seconds: int = 30

    # Prometheus metrics, served on their OWN port, never on the public API port.
    # 0 turns the metrics server off (tests do this). The API and the worker need
    # different ports when they run on the same machine.
    metrics_port: int = 9100
    worker_metrics_port: int = 9101

    # Logging: JSON lines (for log tools) or plain text (easier to read while coding).
    log_level: str = "INFO"
    log_json: bool = True

    # Connection pool. See README: "What is connection pooling and why does it cost money?"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30

    # --- Real-world order rules (see README: "Business rules borrowed from Zomato and Swiggy") ---
    # A restaurant must accept a paid order within this window, or it is auto-rejected.
    restaurant_accept_timeout_seconds: int = 240
    # An order that is never paid releases its reserved stock after this window.
    unpaid_order_timeout_seconds: int = 600

    # --- Bill components. Illustrative values; real platforms change these often. ---
    platform_fee: Decimal = Decimal("12.00")
    delivery_fee: Decimal = Decimal("30.00")
    free_delivery_above: Decimal = Decimal("299.00")
    gst_rate_food: Decimal = Decimal("0.05")  # restaurant service via an e-commerce operator
    gst_rate_fees: Decimal = Decimal("0.18")  # platform's own fees (platform + delivery)

    @model_validator(mode="after")
    def refuse_dev_secret_outside_local(self):
        # Fail at startup, loudly, instead of running in production with a
        # secret that is published on GitHub.
        if self.environment not in ("local", "test", "ci") and self.jwt_secret_key == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set to a real secret outside local development")
        if len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
