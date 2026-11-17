"""One shared Redis client.

Redis is an in-memory key-value store: microsecond reads, keys that expire on
their own (TTL), and atomic counters. QuickServe uses it for three things that
are fine to lose and must be fast:

  menu:v1:<restaurant_id>        cached customer menu           (expires in seconds)
  login:fail:email:<email>       failed-login counter            (expires after the window)
  login:fail:ip:<ip>             failed-login counter per IP     (expires after the window)
  auth:revoked:<token id>        logged-out token                (expires when the token would)

PostgreSQL stays the source of truth for everything that matters (orders,
stock, money). If Redis disappears, QuickServe keeps working: the menu comes
straight from the database, and login protection pauses (and logs a warning).
"""

import logging
from functools import lru_cache

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import get_settings

log = logging.getLogger("quickserve.redis")

# Every Redis failure we choose to survive is one of these.
RedisError = redis.RedisError


def make_redis(url: str) -> redis.Redis:
    timeout = get_settings().redis_timeout_seconds
    return redis.Redis.from_url(
        url,
        decode_responses=True,  # give us str, not bytes
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        # By default the client retries a failed command several times with
        # growing pauses. With Redis down, that made EVERY request wait ~4 seconds
        # (a test caught it). One immediate retry is enough for a dropped
        # connection; after that we fail fast and degrade.
        retry=Retry(NoBackoff(), retries=1),
        health_check_interval=30,
    )


@lru_cache
def get_redis() -> redis.Redis:
    return make_redis(get_settings().redis_url)


def redis_is_up() -> bool:
    try:
        return bool(get_redis().ping())
    except RedisError:
        return False
