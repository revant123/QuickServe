"""Logout for stateless tokens.

A JWT can't be "un-issued": it stays valid until it expires. So logout keeps a
short deny list in Redis: when you log out, your token's id (jti) is stored
under auth:revoked:<jti> with a TTL equal to the token's remaining lifetime.
After that the key disappears by itself, because the token has expired anyway.
The deny list therefore never holds more than 30 minutes of logouts.

If Redis is down, revoked tokens are accepted again until they expire (fail
open), and a warning is logged. Same availability trade-off as the login rate limit.
"""

import logging
from datetime import UTC, datetime

from app.core.exceptions import ServiceUnavailable
from app.core.logging import log_event
from app.core.redis import RedisError, get_redis
from app.core.security import TokenClaims

log = logging.getLogger("quickserve.auth")


def _key(token_id: str) -> str:
    return f"auth:revoked:{token_id}"


def revoke(claims: TokenClaims) -> None:
    remaining = int((claims.expires_at - datetime.now(UTC)).total_seconds())
    if remaining <= 0:
        return  # already expired, nothing to do
    try:
        get_redis().set(_key(claims.token_id), "1", ex=remaining)
    except RedisError:
        # Unlike the checks, logout must NOT fail silently: the user would believe
        # they're logged out while their token still works.
        raise ServiceUnavailable("Logout is temporarily unavailable, please try again") from None


def is_revoked(claims: TokenClaims) -> bool:
    try:
        return get_redis().exists(_key(claims.token_id)) == 1
    except RedisError as exc:
        log_event(log, logging.WARNING, "token revocation check unavailable (redis down), allowing", error=str(exc))
        return False
