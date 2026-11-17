"""Behind the gateway (Phase 9): which client IP does the API see?

Every request reaches the API from the Envoy pod, so `request.client.host` would
be Envoy's IP for every customer, and the "20 failed logins per IP" rule would
lock EVERYONE out after 20 failures from anyone. Envoy appends the real client
address to X-Forwarded-For; uvicorn's ProxyHeadersMiddleware reads it, but only
for requests from a trusted proxy (FORWARDED_ALLOW_IPS). These tests pin down
exactly what it trusts, because getting this wrong is a security bug.
"""

import asyncio

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

POD_NETWORK = "10.244.0.0/16"  # FORWARDED_ALLOW_IPS in infra/k8s/base/config.yaml
ENVOY_POD = "10.244.0.17"


def seen_by_app(peer, xff=None, trusted=POD_NETWORK):
    """Run one request through uvicorn's middleware; return (client ip, scheme) the app sees."""
    seen = {}

    async def app(scope, receive, send):
        seen["client"], seen["scheme"] = scope["client"][0], scope["scheme"]

    headers = [(b"x-forwarded-for", xff.encode()), (b"x-forwarded-proto", b"https")] if xff else []
    scope = {"type": "http", "client": (peer, 40000), "scheme": "http", "headers": headers}
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
    return seen["client"], seen["scheme"]


def test_through_the_gateway_the_app_sees_the_real_client():
    # Envoy appended the address it saw (the customer) to the header.
    assert seen_by_app(ENVOY_POD, xff="203.0.113.9") == ("203.0.113.9", "https")


def test_a_client_cannot_pretend_to_be_someone_else():
    # The attacker sends "X-Forwarded-For: 6.6.6.6"; Envoy appends their real
    # address. uvicorn reads from the RIGHT and stops at the first address that
    # isn't a trusted proxy, so the forged left part is ignored.
    assert seen_by_app(ENVOY_POD, xff="6.6.6.6, 203.0.113.9")[0] == "203.0.113.9"


def test_the_header_is_ignored_when_it_doesnt_come_from_a_trusted_proxy():
    # Someone reaching the API directly (not through Envoy) can't set their IP.
    assert seen_by_app("198.51.100.4", xff="6.6.6.6") == ("198.51.100.4", "http")


def test_trusting_everyone_is_the_classic_mistake():
    # FORWARDED_ALLOW_IPS="*" makes uvicorn believe the LEFT-most entry, which
    # the client wrote. This is why the config names the pod network instead.
    assert seen_by_app(ENVOY_POD, xff="6.6.6.6, 203.0.113.9", trusted="*")[0] == "6.6.6.6"
