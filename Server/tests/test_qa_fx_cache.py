"""Agent answers are never cached, and a request without the key is refused before its body is read."""

from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from main import app
from observability import MAX_JSON_BYTES

pytestmark = pytest.mark.anyio
KEY = "synthetic-test-key"
REFUSED = {"detail": "앱 연결 정보가 맞지 않아요. 연결 설정을 살펴봐 주세요."}


@pytest.fixture
async def stranger(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("ROUNDUP_API_KEY", KEY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=20) as http:
        yield http


async def test_agent_answer_is_not_stored(client: AsyncClient, database: AsyncEngine) -> None:
    del database
    response = await client.get("/agent/settings")
    assert (response.status_code, response.headers.get_list("cache-control")) == (200, ["no-store"])


@pytest.mark.parametrize(("method", "path", "body", "status"), [
    ("GET", "/agent/nothing", b"", 404),
    ("DELETE", "/agent/settings", b"", 405),
    ("POST", "/agent/run", b"{not json", 422),
    ("POST", "/agent/run", b"x" * (MAX_JSON_BYTES + 1), 413),
])
async def test_agent_refusal_is_not_stored(
    client: AsyncClient, method: str, path: str, body: bytes, status: int,
) -> None:
    response = await client.request(method, path, content=body, headers={"Content-Type": "application/json"})
    assert (response.status_code, response.headers.get_list("cache-control")) == (status, ["no-store"])


async def test_other_routes_keep_their_headers(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert (response.status_code, response.headers.get("cache-control")) == (200, None)


@pytest.mark.parametrize("headers", [{}, {"X-Roundup-Key": ""}, {"X-Roundup-Key": "wrong"}])
@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/agent/run"), ("PUT", "/agent/settings"), ("POST", "/agent/proposals/x/approve"),
    ("POST", "/agent/proposals/x/dismiss"), ("POST", "/agent/steps/x/undo"),
    ("POST", "/agent/invoices/import"),
])
async def test_missing_key_is_refused_before_the_body(
    stranger: AsyncClient, method: str, path: str, headers: dict[str, str],
) -> None:
    read: list[int] = []

    async def body() -> AsyncIterator[bytes]:
        read.append(1)
        yield b"{not json"

    response = await stranger.request(
        method, path, content=body(), headers={"Content-Type": "application/json", **headers},
    )
    assert (response.status_code, response.json(), read) == (401, REFUSED, [])
    assert response.headers.get_list("cache-control") == ["no-store"]


async def test_missing_key_is_refused_before_the_size(stranger: AsyncClient) -> None:
    response = await stranger.post("/agent/run", content=b"x" * (MAX_JSON_BYTES + 1))
    assert (response.status_code, response.json()) == (401, REFUSED)


async def test_unset_server_key_is_an_outage_not_a_pass(
    stranger: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROUNDUP_API_KEY")
    response = await stranger.post("/agent/run", content=b"{}", headers={"X-Roundup-Key": KEY})
    assert response.status_code == 503
