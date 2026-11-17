"""Cache-aside for the customer menu.

The menu page is the most-read thing in a food app: thousands of people open a
popular restaurant for every one who orders. Building it costs several database
queries and some Python. So:

  read:   look in Redis -> found? return it (HIT)
                        -> not found? build it from PostgreSQL, store it with a
                           short TTL, return it (MISS)
  write:  when the owner changes the menu (new dish, restock, switch off),
          delete the key AFTER the database commit, so the next read rebuilds it.

Why delete after the commit, not before? If we deleted first, a reader could
rebuild the cache from the OLD rows in the gap before our commit, and the stale
copy would then sit in Redis for the whole TTL.

What we deliberately accept: stock badges ("Only 3 left") can be up to
MENU_CACHE_TTL seconds old, because placing an order does not clear the cache
(a busy restaurant would otherwise never get a cache hit). That's safe: the
order itself always checks stock in PostgreSQL with the atomic UPDATE, so a
slightly stale menu can never cause an oversell.
"""

import json
import logging
import uuid

from app.core.config import get_settings
from app.core.logging import log_event
from app.core.redis import RedisError, get_redis
from app.modules.menu.schema import MenuItemPublic

log = logging.getLogger("quickserve.cache")

HIT, MISS, BYPASS = "HIT", "MISS", "BYPASS"  # BYPASS = Redis unavailable, served from the database


def _key(restaurant_id: uuid.UUID) -> str:
    # The "v1" lets us change the cached format later without reading old entries.
    return f"menu:v1:{restaurant_id}"


def get(restaurant_id: uuid.UUID) -> tuple[list[MenuItemPublic] | None, str]:
    try:
        raw = get_redis().get(_key(restaurant_id))
    except RedisError as exc:
        log_event(log, logging.WARNING, "redis unavailable, serving menu from database", error=str(exc))
        return None, BYPASS
    if raw is None:
        return None, MISS
    return [MenuItemPublic.model_validate(item) for item in json.loads(raw)], HIT


def put(restaurant_id: uuid.UUID, items: list[MenuItemPublic]) -> None:
    payload = json.dumps([item.model_dump(mode="json") for item in items])
    try:
        get_redis().set(_key(restaurant_id), payload, ex=get_settings().menu_cache_ttl_seconds)
    except RedisError:
        pass  # caching is an optimisation; failing to cache is not an error


def invalidate(restaurant_id: uuid.UUID) -> None:
    try:
        get_redis().delete(_key(restaurant_id))
    except RedisError as exc:
        # The entry will still expire on its own within the TTL.
        log_event(log, logging.WARNING, "could not invalidate menu cache", restaurant_id=restaurant_id, error=str(exc))
