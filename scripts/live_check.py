"""Smoke test for the live site (Phase 16): is the NEW version up, and healthy?

    python3 scripts/live_check.py --url https://quickserve-you.duckdns.org --expect-commit 0519a88

GitHub Actions runs it right after each deploy. If any check fails, the
deploy job rolls the server back to the previous version. Standard library
only, so it runs anywhere Python does, with nothing to install.

What it checks, and why each one matters:
  1. /health reports the commit we just deployed  (not the old container still answering)
  2. /health/ready: the database answers            (the app can actually serve orders)
  3. the home page is the React app                 (the web container and Caddy's routing work)
  4. a real API call: restaurants near a location   (the API, PostgreSQL and the routing together)
  5. HTTPS: the certificate is valid for 7+ days, HTTP redirects to HTTPS, HSTS is on
"""

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # report the redirect instead of following it


def fetch(url: str, follow: bool = True) -> tuple[int, dict, bytes]:
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "quickserve-live-check"})
    try:
        with opener.open(request, timeout=15) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def certificate_days_left(host: str) -> float:
    context = ssl.create_default_context()  # verifies the chain and the name, like a browser
    with socket.create_connection((host, 443), timeout=15) as raw, context.wrap_socket(raw, server_hostname=host) as s:
        not_after = s.getpeercert()["notAfter"]
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=UTC)
    return (expires - datetime.now(UTC)).total_seconds() / 86400


def run_checks(base: str, expect_commit: str | None) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))

    status, _, body = fetch(f"{base}/health")
    info = json.loads(body) if status == 200 else {}
    commit = str(info.get("commit", "?"))
    if expect_commit:
        same = commit[:7] == expect_commit[:7]
        check("new version is live", status == 200 and same, f"commit {commit[:7]}, expected {expect_commit[:7]}")
    else:
        check("API alive", status == 200, f"HTTP {status}, commit {commit[:7]}")

    status, _, body = fetch(f"{base}/health/ready")
    check("database reachable", status == 200, body.decode(errors="replace")[:120])

    status, headers, body = fetch(f"{base}/")
    is_app = status == 200 and b'id="root"' in body and "text/html" in headers.get("Content-Type", "")
    check("React app served", is_app, f"HTTP {status}, {len(body)} bytes")

    status, _, body = fetch(f"{base}/api/v1/restaurants/near?lat=30.7333&lng=76.7794")
    try:
        count = len(json.loads(body)) if status == 200 else 0
    except ValueError:
        status, count = -1, 0
    check("API + database together", status == 200, f"HTTP {status}, {count} restaurants near Sector 22")

    parts = urlsplit(base)
    if parts.scheme == "https":
        host = parts.hostname or ""
        days = certificate_days_left(host)
        check("certificate valid", days > 7, f"expires in {days:.0f} days")
        status, headers, _ = fetch(f"http://{host}/health", follow=False)
        location = headers.get("Location", "")
        check(
            "HTTP redirects to HTTPS",
            status in (301, 308) and location.startswith("https://"),
            f"{status} -> {location}",
        )
        _, headers, _ = fetch(f"{base}/health")
        hsts = headers.get("Strict-Transport-Security", "")
        check("HSTS header", "max-age=" in hsts, hsts or "missing")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="the live site, e.g. https://quickserve-you.duckdns.org")
    parser.add_argument("--expect-commit", help="the Git commit that should be answering")
    parser.add_argument("--timeout", type=float, default=120, help="seconds to keep retrying failed checks")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    # Retry for a while: right after a deploy, a check can fail for a few
    # seconds (Caddy's next health check, a cold cache). After that, it's real.
    deadline = time.monotonic() + args.timeout
    while True:
        try:
            results = run_checks(base, args.expect_commit)
        except (OSError, ssl.SSLError, ValueError, KeyError) as e:
            results = [("site reachable", False, f"{type(e).__name__}: {e}")]
        if all(ok for _, ok, _ in results) or time.monotonic() > deadline:
            break
        time.sleep(5)

    print(f"Live check of {base}\n")
    print("| Check | Result | Detail |\n|---|---|---|")
    for name, ok, detail in results:
        print(f"| {name} | {'ok' if ok else 'FAILED'} | {detail} |")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
