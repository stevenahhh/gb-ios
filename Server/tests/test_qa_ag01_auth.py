"""Agent routes answer bad input as bad input, not as an outage."""

from collections.abc import AsyncIterator

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.anyio
TOO_MUCH = 80


async def oversized() -> AsyncIterator[bytes]:
    """Stream past the JSON limit without a Content-Length."""
    for _ in range(TOO_MUCH):
        yield b"x" * 1024


@pytest.mark.parametrize("path", ["/agent/runs/a%00b", "/agent/runs/%00"])
async def test_id_with_a_nul_is_bad_input(client: AsyncClient, database: AsyncEngine, path: str) -> None:
    del database
    response = await client.get(path)
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["question", "history"])
async def test_body_with_a_nul_is_bad_input(client: AsyncClient, database: AsyncEngine, field: str) -> None:
    del database
    body: dict[str, object] = {"question": "안녕", "background": True}
    body[field] = "a\x00b" if field == "question" else [{"role": "owner", "text": "a\x00b"}]
    response = await client.post("/agent/run", json=body)
    assert response.status_code == 422


async def test_streamed_body_past_the_limit_is_too_large(client: AsyncClient) -> None:
    response = await client.post(
        "/agent/run", content=oversized(), headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
