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

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "QuickServe API"
    environment: str = "local"

    # postgresql+psycopg:// selects the psycopg 3 driver. A bare postgresql://
    # URL would make SQLAlchemy look for the older psycopg2 driver.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/quickserve"

    # Print every SQL statement SQLAlchemy sends. Turn this on while learning.
    sql_echo: bool = False

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
