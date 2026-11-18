"""Executable auth/config/input contracts that do not need a database."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from database import DatabaseConfigurationError, get_engine
from main import app


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


def test_existing_liveness_and_service_routes_remain_registered(http: TestClient) -> None:
    response = http.get("/health", headers={"X-Roundup-Key": "synthetic-test-key"})
    assert response.json() == {"status": "ok"}
    paths = http.get("/openapi.json").json()["paths"]
    assert {"/draft", "/ask", "/stt", "/geocode", "/staticmap"} <= paths.keys()
