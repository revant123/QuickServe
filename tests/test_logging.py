"""Request IDs, structured log lines, and what must never be logged."""

import json
import logging

from app.core.logging import JsonFormatter
from app.main import app


def _json_lines(caplog):
    fmt = JsonFormatter()
    return [json.loads(fmt.format(r)) for r in caplog.records]


def test_every_response_carries_a_request_id(client):
    r = client.get("/health")
    assert len(r.headers["X-Request-ID"]) == 32


def test_a_safe_incoming_request_id_is_kept_and_an_unsafe_one_replaced(client):
    assert client.get("/health", headers={"X-Request-ID": "checkout-flow-42"}).headers["X-Request-ID"] == (
        "checkout-flow-42"
    )
    injected = client.get("/health", headers={"X-Request-ID": 'abc" level=ERROR fake=1'})
    assert injected.headers["X-Request-ID"] != 'abc" level=ERROR fake=1'


def test_one_json_line_per_request_with_timing(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/health", headers={"X-Request-ID": "trace-me-123"})
    lines = [line for line in _json_lines(caplog) if line["message"] == "request"]
    assert len(lines) == 1
    line = lines[0]
    assert line["request_id"] == "trace-me-123" and line["path"] == "/health" and line["status"] == 200
    assert isinstance(line["duration_ms"], float) and line["level"] == "INFO"


def test_failed_login_never_logs_the_password_or_email(client, customer, caplog):
    caplog.set_level(logging.INFO)
    client.post("/api/v1/auth/login", data={"username": customer.email, "password": "MySecretGuess!"})
    everything = " ".join(json.dumps(line) for line in _json_lines(caplog))
    assert "login failed" in everything
    assert "MySecretGuess!" not in everything and customer.email not in everything


def test_unexpected_errors_return_a_request_id_not_a_stack_trace(client, caplog):
    def boom():
        raise RuntimeError("database password is hunter2")

    app.add_api_route("/test-boom", boom)
    try:
        caplog.set_level(logging.INFO)
        r = client.get("/test-boom")
    finally:
        app.router.routes.pop()
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error", "request_id": r.headers["X-Request-ID"]}
    assert "hunter2" not in r.text
    errors = [line for line in _json_lines(caplog) if line["message"] == "unhandled error"]
    assert errors and "hunter2" in errors[0]["exception"]  # the details are in OUR logs, not the response
