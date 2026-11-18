"""Who is the client? The real customer's address, also behind the gateway.

Since Phase 9 every request reaches the API from the gateway (Envoy), so the
TCP peer is Envoy's pod for every customer. Used as is, the "20 failed logins
per IP" rule would lock EVERYONE out after 20 failures from anyone.

Envoy appends the address it received the request from to X-Forwarded-For:

    X-Forwarded-For: <whatever the client sent>, <the address Envoy saw>

Only the LAST entry was written by our proxy. Everything to its left came from
the client and can be anything, so we never look at it. That's "trust exactly
one hop", Envoy's xff_num_trusted_hops model.

It applies only when the request really comes from our proxy
(TRUSTED_PROXY_CIDRS). Anyone else's X-Forwarded-For is ignored.

Why not uvicorn's --forwarded-allow-ips? It walks the list from the right and
skips every TRUSTED address. When the client itself sits inside the trusted
range (a pod, or `kubectl port-forward`, which arrives from a pod address),
uvicorn skips it too and believes the forged entry. Our CI caught exactly that:
a request claiming "X-Forwarded-For: 6.6.6.6" was logged as coming from 6.6.6.6.
"""

import ipaddress
from functools import lru_cache

from starlette.requests import Request

from app.core.config import get_settings


@lru_cache
def _networks(cidrs: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(c.strip(), strict=False) for c in cidrs.split(",") if c.strip())


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def from_proxy(peer: str, forwarded_for: str | None, trusted_cidrs: str) -> str:
    """The client address, given the TCP peer and the X-Forwarded-For header."""
    networks = _networks(trusted_cidrs)
    if not forwarded_for or not networks or not _is_ip(peer):
        return peer
    if not any(ipaddress.ip_address(peer) in n for n in networks):
        return peer  # not our proxy: its X-Forwarded-For means nothing
    last = forwarded_for.split(",")[-1].strip()
    return last if _is_ip(last) else peer


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    return from_proxy(peer, request.headers.get("x-forwarded-for"), get_settings().trusted_proxy_cidrs)
