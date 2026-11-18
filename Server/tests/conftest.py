"""Every PostgreSQL test owns one UUID schema; public tables are never touched."""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.schema import CreateSchema, DropSchema

from database import get_engine
from init_db import initialize
from main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def empty_database(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("ROUNDUP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ROUNDUP_TEST_DATABASE_URL to run real PostgreSQL integration tests")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv(
        "DATABASE_SSLMODE", os.environ.get("ROUNDUP_TEST_DATABASE_SSLMODE", "verify-full"),
    )
    get_engine.cache_clear()
    engine = get_engine()
    schema = f"roundup_test_{uuid4().hex}"
    async with engine.begin() as connection:
        _ = await connection.execute(CreateSchema(schema))
    engine.update_execution_options(schema_translate_map={None: schema})
    try:
        yield engine
    finally:
        try:
            async with engine.begin() as connection:
                _ = await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await engine.dispose()
            get_engine.cache_clear()


@pytest.fixture
async def database(empty_database: AsyncEngine) -> AsyncEngine:
    await initialize(empty_database)
    return empty_database


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("ROUNDUP_API_KEY", "synthetic-test-key")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=20,
        headers={"X-Roundup-Key": "synthetic-test-key"},
    ) as http:
        yield http
