"""Phase 16: the demo passwords in scripts/seed.py are public, so a live server
must not use them."""

import pytest

from scripts.seed import DEMO_USERS, demo_passwords

LIVE = {"SEED_CUSTOMER_PASSWORD": "customer-secret-1", "SEED_STAFF_PASSWORD": "staff-secret-12"}


def test_local_runs_use_the_public_demo_passwords():
    assert demo_passwords("local", {}) == {email: pw for email, (_n, _r, pw) in DEMO_USERS.items()}


@pytest.mark.parametrize("env", [{}, {"SEED_CUSTOMER_PASSWORD": "x" * 20}, {**LIVE, "SEED_STAFF_PASSWORD": "short"}])
def test_a_live_server_refuses_to_seed_without_real_passwords(env):
    with pytest.raises(SystemExit, match="public"):
        demo_passwords("dev", env)


def test_a_live_server_uses_the_customer_and_staff_passwords():
    passwords = demo_passwords("dev", LIVE)
    assert passwords["customer@quickserve.dev"] == "customer-secret-1"
    assert {passwords[e] for e in ("owner@quickserve.dev", "rider@quickserve.dev", "admin@quickserve.dev")} == {
        "staff-secret-12"
    }
    assert not any(pw.endswith("-pass-123") for pw in passwords.values())
