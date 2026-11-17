"""Behind the gateway (Phase 9): which client IP does the API see?

See app/core/client_ip.py. Getting this wrong is a security bug either way:
trust nothing and every customer shares Envoy's IP (one attacker locks everyone
out of login); trust too much and anyone can claim any IP.
"""

import asyncio

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.client_ip import from_proxy

POD_NETWORK = "10.244.0.0/16"  # TRUSTED_PROXY_CIDRS in infra/k8s/base/config.yaml
ENVOY = "10.244.0.17"


def test_no_proxy_configured_means_the_tcp_peer_is_the_client():
    assert from_proxy("203.0.113.9", "6.6.6.6", trusted_cidrs="") == "203.0.113.9"


def test_through_the_gateway_the_api_sees_the_real_client():
    # Envoy appended the address it saw.
    assert from_proxy(ENVOY, "203.0.113.9", POD_NETWORK) == "203.0.113.9"


def test_a_forged_x_forwarded_for_is_ignored():
    # The client sent "X-Forwarded-For: 6.6.6.6"; Envoy appended the real address.
    assert from_proxy(ENVOY, "6.6.6.6, 203.0.113.9", POD_NETWORK) == "203.0.113.9"


def test_a_client_inside_the_pod_network_cant_forge_either():
    # The case CI caught: the client (here another pod) has an address in the
    # trusted range. We still take only the last entry, the one Envoy wrote.
    assert from_proxy(ENVOY, "6.6.6.6, 10.244.0.42", POD_NETWORK) == "10.244.0.42"


def test_x_forwarded_for_from_anyone_but_the_proxy_is_ignored():
    # Someone reaching the API directly, not through Envoy.
    assert from_proxy("198.51.100.4", "6.6.6.6", POD_NETWORK) == "198.51.100.4"


def test_garbage_in_the_header_falls_back_to_the_peer():
    assert from_proxy(ENVOY, "6.6.6.6, not-an-ip", POD_NETWORK) == ENVOY
    assert from_proxy(ENVOY, None, POD_NETWORK) == ENVOY


def _uvicorn_sees(peer, xff, trusted):
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    scope = {"type": "http", "client": (peer, 40000), "scheme": "http", "headers": [(b"x-forwarded-for", xff.encode())]}
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
    return seen["client"]


def test_why_not_uvicorns_forwarded_allow_ips():
    # uvicorn skips EVERY trusted address from the right. A client inside the
    # trusted range is skipped too, and the forged entry wins. This is the bug
    # the first version of Phase 9 had; CI's gateway check found it.
    assert _uvicorn_sees(ENVOY, "6.6.6.6, 10.244.0.42", POD_NETWORK) == "6.6.6.6"
    # And "*" (trust everyone) believes the left-most entry: always forgeable.
    assert _uvicorn_sees(ENVOY, "6.6.6.6, 203.0.113.9", "*") == "6.6.6.6"
