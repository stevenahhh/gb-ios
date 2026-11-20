"""Executable auth/config/input contracts that do not need a database."""

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Final

import pytest
from fastapi.testclient import TestClient

from database import DatabaseConfigurationError, get_engine
from main import app
from observability import MAX_JSON_BYTES, JsonFormatter

LEAK: Final = "postgresql://secret-value"


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic@127.0.0.1/unused")
    monkeypatch.setenv("DATABASE_SSLMODE", "verify-full")
    monkeypatch.setenv("ROUNDUP_API_KEY", "synthetic-test-key")
    get_engine.cache_clear()
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "route",
    [
        ("GET", "/inquiries"),
        ("PATCH", "/inquiries/inquiry-clay/draft"),
        ("POST", "/inquiries/inquiry-clay/decision"),
        ("GET", "/health/ready"),
        ("GET", "/today"),
        ("GET", "/bookings"),
        ("POST", "/bookings"),
        ("GET", "/orders"),
        ("GET", "/shipments"),
        ("GET", "/channels"),
        ("GET", "/calendar"),
        ("POST", "/calendar/events"),
        ("GET", "/operations"),
        ("GET", "/settings"),
        ("PUT", "/workshop"),
        ("POST", "/tasks/x/completion"),
        ("GET", "/bookings/x"),
        ("GET", "/class-sessions/x"),
        ("GET", "/cards/task/x"),
        ("POST", "/bookings/x/undo-deposit"),
        ("POST", "/orders/x/undo-confirm"),
        ("POST", "/shipments/x/undo"),
        ("POST", "/tasks/x/undo"),
        ("GET", "/assistant-drafts/content/x"),
        ("PATCH", "/assistant-drafts/content/x/draft"),
        ("POST", "/assistant-drafts/content/x/decision"),
        ("POST", "/assistant-drafts/content/x/reopen"),
        ("POST", "/ask"),
        ("POST", "/draft"),
        ("POST", "/rewrite"),
    ],
)
@pytest.mark.parametrize("api_key", ["", "wrong"])
def test_inquiry_routes_require_existing_shared_key(
    http: TestClient, route: tuple[str, str], api_key: str,
) -> None:
    method, path = route
    response = http.request(method, path, headers={"X-Roundup-Key": api_key}, json={})
    assert response.status_code == 401


@pytest.mark.parametrize("revision", [-1, 1.5, "0", True, None])
def test_revision_requires_nonnegative_json_integer(
    http: TestClient, *, revision: float | str | bool | None,
) -> None:
    response = http.patch(
        "/inquiries/inquiry-clay/draft",
        headers={"X-Roundup-Key": "synthetic-test-key"},
        json={"draft": "", "expectedRevision": revision},
    )
    assert response.status_code == 422


def test_unknown_decision_is_rejected_at_boundary(http: TestClient) -> None:
    response = http.post(
        "/inquiries/inquiry-clay/decision",
        headers={"X-Roundup-Key": "synthetic-test-key"},
        json={"decision": "send", "draft": "hello", "expectedRevision": 0},
    )
    assert response.status_code == 422


def test_missing_database_configuration_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_engine.cache_clear()
    with pytest.raises(DatabaseConfigurationError), TestClient(app):
        pytest.fail("startup must fail before requests can run")


@pytest.mark.parametrize(
    ("url", "ssl_mode"),
    [
        ("sqlite:///local.db", "disable"),
        ("postgresql://synthetic@localhost/unused", "prefer"),
        ("postgresql://synthetic@localhost/unused?sslmode=disable", "disable"),
    ],
)
def test_invalid_database_configuration_is_redacted(
    monkeypatch: pytest.MonkeyPatch, url: str, ssl_mode: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_SSLMODE", ssl_mode)
    get_engine.cache_clear()
    with pytest.raises(DatabaseConfigurationError) as failure:
        get_engine()
    assert url not in str(failure.value)


def test_oversized_json_body_is_rejected_before_parsing(http: TestClient) -> None:
    response = http.post(
        "/ask", headers={"X-Roundup-Key": "synthetic-test-key"}, content=b"x" * (MAX_JSON_BYTES + 1),
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "request body too large"}


def test_unexpected_failure_returns_generic_body_and_logs_no_detail(
    http: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    async def explode(_now: datetime) -> list[str]:
        raise RuntimeError(LEAK)

    monkeypatch.setattr("ai.build_context", explode)
    logging.getLogger("roundup").propagate = True
    with caplog.at_level(logging.INFO, logger="roundup"):
        response = http.post("/ask", headers={"X-Roundup-Key": "synthetic-test-key"}, json={"question": "?"})
    logging.getLogger("roundup").propagate = False
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    record = next(item for item in caplog.records if item.getMessage() == "http_request")
    formatted = JsonFormatter().format(record)
    assert json.loads(formatted)["route"] == "/ask"
    assert json.loads(formatted)["error_type"] == "RuntimeError"
    assert LEAK not in formatted


def test_non_ascii_api_key_is_rejected_not_crashed(http: TestClient) -> None:
    response = http.get("/health", headers={"X-Roundup-Key": "키".encode()})
    assert response.status_code == 401


@pytest.mark.parametrize("schema", ["Bad-Name", "x; DROP SCHEMA public", "1digit"])
def test_invalid_schema_name_is_rejected(monkeypatch: pytest.MonkeyPatch, schema: str) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic@127.0.0.1/unused")
    monkeypatch.setenv("DATABASE_SSLMODE", "disable")
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    get_engine.cache_clear()
    with pytest.raises(DatabaseConfigurationError):
        get_engine()


def test_existing_liveness_and_service_routes_remain_registered(http: TestClient) -> None:
    response = http.get("/health", headers={"X-Roundup-Key": "synthetic-test-key"})
    assert response.json() == {"status": "ok"}
    paths = app.openapi()["paths"]
    assert {"/draft", "/ask", "/rewrite", "/stt", "/geocode", "/staticmap"} <= paths.keys()
