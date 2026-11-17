"""Slow down password guessing.

Argon2 makes each guess cost ~100 ms of our CPU, but nothing stops a script
from trying thousands of passwords against one account. So we count FAILED
logins in Redis, per email and per IP address, in a fixed time window:

  login:fail:email:<email>   at most 5 failures per 15 minutes  (protects one account)
  login:fail:ip:<ip>         at most 20 failures per 15 minutes (stops one machine
                              trying a common password against many accounts)

INCR is atomic in Redis, so two simultaneous failures can't both read "4" and
both write "5". The key expires by itself at the end of the window; there's no
cleanup job. A successful login clears the email counter.

When Redis is down we FAIL OPEN: logins still work, just without the limit, and
we log a warning. The other choice, refusing every login while Redis is down,
would turn a cache outage into "nobody can log in". That's a real trade-off
(security vs availability); a bank might choose the opposite.

Behind a load balancer (Phase 6) every request appears to come from the load
balancer's IP. Then the real client IP must be read from the X-Forwarded-For
header, and only when it was set by our own load balancer.
"""

import logging

from app.core.config import get_settings
from app.core.exceptions import TooManyRequests
from app.core.logging import log_event
from app.core.redis import RedisError, get_redis

log = logging.getLogger("quickserve.auth")


def _keys(email: str, ip: str) -> tuple[str, str]:
    return f"login:fail:email:{email}", f"login:fail:ip:{ip}"


def ensure_not_locked(email: str, ip: str) -> None:
    """Call BEFORE checking the password, so a locked-out attacker can't keep guessing."""
    s = get_settings()
    email_key, ip_key = _keys(email, ip)
    try:
        r = get_redis()
        with r.pipeline() as p:  # one network round trip for all four commands
            p.get(email_key)
            p.ttl(email_key)
            p.get(ip_key)
            p.ttl(ip_key)
            email_count, email_ttl, ip_count, ip_ttl = p.execute()
    except RedisError as exc:
        log_event(log, logging.WARNING, "login rate limit unavailable (redis down), allowing", error=str(exc))
        return
    if email_count and int(email_count) >= s.login_max_failures_per_email:
        log_event(log, logging.WARNING, "login blocked: too many failures for this account", ip=ip)
        raise TooManyRequests("Too many failed logins. Try again later.", retry_after=max(int(email_ttl), 1))
    if ip_count and int(ip_count) >= s.login_max_failures_per_ip:
        log_event(log, logging.WARNING, "login blocked: too many failures from this IP", ip=ip)
        raise TooManyRequests("Too many failed logins. Try again later.", retry_after=max(int(ip_ttl), 1))


def record_failure(email: str, ip: str) -> None:
    window = get_settings().login_failure_window_seconds
    email_key, ip_key = _keys(email, ip)
    try:
        with get_redis().pipeline() as p:
            p.incr(email_key)
            p.expire(email_key, window, nx=True)  # start the window on the first failure only
            p.incr(ip_key)
            p.expire(ip_key, window, nx=True)
            p.execute()
    except RedisError:
        pass


def clear_email(email: str) -> None:
    try:
        get_redis().delete(_keys(email, "")[0])
    except RedisError:
        pass
