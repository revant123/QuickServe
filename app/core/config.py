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
    notifier_metrics_port: int = 9102

    # Notifier (Phase 8): delivers outbox events as notifications.
    notifier_interval_seconds: float = 2.0  # how often to look for new events when idle
    notifier_batch_size: int = 100
    notifier_max_attempts: int = 5  # then the event is dead-lettered for a human to look at
    outbox_retention_days: int = 7  # delivered events are deleted after this

    # Behind a proxy (Phase 9): addresses of OUR reverse proxy (the gateway),
    # comma-separated, as IPs or networks. Only requests coming from these may
    # tell us the client's address in X-Forwarded-For. Empty = no proxy: the
    # TCP peer is the client. See app/core/client_ip.py.
    trusted_proxy_cidrs: str = ""

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

    # Phase 14: riders and restaurant payouts. Illustrative numbers, not any
    # platform's real rates.
    # A rider's pay for one order: a base amount plus a per-km amount for the
    # restaurant-to-customer distance, rounded to whole rupees.
    rider_base_pay: Decimal = Decimal("20")
    rider_pay_per_km: Decimal = Decimal("6")
    # Wrong delivery codes allowed before the order is locked for support.
    # 5 tries at a 4-digit code: a 0.05% chance of guessing it.
    delivery_code_max_attempts: int = 5
    # The platform's commission on the restaurant's food sales, and the GST the
    # restaurant pays on that commission (a service). Reported Indian commission
    # rates range from about 16% to 30%.
    restaurant_commission_percent: Decimal = Decimal("20")
    gst_on_commission_percent: Decimal = Decimal("18")
    # An order that is never paid releases its reserved stock after this window.
    unpaid_order_timeout_seconds: int = 600

    # --- Pricing (Phase 11). See app/modules/pricing/calculator.py and the README. ---
    # Illustrative values modelled on Zomato/Swiggy in 2026. Real platforms tune
    # them per city and per week, which is why they're settings, not constants.
    # The timezone the surge windows below are written in.
    pricing_timezone: str = "Asia/Kolkata"
    # Flat, every order, before GST (Zomato's was Rs 14.90 from March 2026).
    platform_fee: Decimal = Decimal("14.90")
    # Delivery fee by ROAD distance, as (up to km, fee) slabs. Beyond the last
    # slab nobody delivers, whatever the restaurant's own radius says.
    delivery_fee_slabs: list[tuple[Decimal, Decimal]] = [
        (Decimal("2"), Decimal("20.00")),
        (Decimal("4"), Decimal("30.00")),
        (Decimal("6"), Decimal("45.00")),
        (Decimal("8"), Decimal("60.00")),
    ]
    # Free delivery for bigger orders, but only nearby: a long ride costs the
    # platform the same whatever the order is worth.
    free_delivery_above: Decimal = Decimal("299.00")
    free_delivery_max_km: Decimal = Decimal("4")
    # Straight-line distance x this = estimated road distance (a "detour index").
    road_detour_factor: Decimal = Decimal("1.25")
    # Small orders cost the platform as much to deliver as big ones.
    small_order_below: Decimal = Decimal("149.00")
    small_order_fee: Decimal = Decimal("15.00")
    # Surge: time windows in pricing_timezone, "HH:MM-HH:MM" (may cross midnight).
    peak_hours: list[str] = ["19:00-22:00"]
    peak_fee: Decimal = Decimal("10.00")
    late_night_hours: list[str] = ["23:00-05:00"]
    late_night_fee: Decimal = Decimal("15.00")
    # Charged while an admin has switched "rain mode" on (it switches itself off).
    rain_fee: Decimal = Decimal("25.00")
    # GST, applied by the platform as the e-commerce operator (Section 9(5)).
    gst_rate_food: Decimal = Decimal("0.05")  # restaurant food and packaging
    gst_rate_fees: Decimal = Decimal("0.18")  # the platform's own services: delivery, platform, small-order, surge

    # --- Discovery (Phase 12): near me, ETA, ratings, search. See the README. ---
    # ETA, the way Swiggy's engineering blog breaks it down:
    #   max(find a rider + ride to the restaurant, cooking) + ride to you (+ handing over)
    rider_first_mile_minutes: int = 8
    rider_speed_kmph: Decimal = Decimal("20")  # average city speed, signals included
    handoff_minutes: int = 4  # parking, finding the door, handing over
    # Ratings. Fewer reviews than this shows "New" instead of an average.
    rating_min_count: int = 3
    # Ranking by rating uses a Bayesian average: every restaurant starts with this
    # many imaginary reviews at the platform's average, so 1 five-star review
    # can't beat 400 reviews averaging 4.6. Used until the platform has ratings.
    rating_prior_weight: int = 10
    rating_prior_mean: Decimal = Decimal("4.0")
    # Customers can review an order for this many days after delivery.
    review_window_days: int = 7
    # Typo tolerance: how similar (0-1, pg_trgm word_similarity) a dish name must
    # be when the exact search found nothing. "paner" vs "Kadhai Paneer" is 0.67.
    search_fuzzy_threshold: float = 0.4

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
