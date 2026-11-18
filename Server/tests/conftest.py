"""Every PostgreSQL test owns one migrated UUID schema; public tables are never touched."""

import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from common import current_time
from database import get_engine
from display import SEOUL
from main import app
from seed import apply_seed

NOW: Final = datetime(2026, 11, 18, 11, 0, tzinfo=SEOUL)
INI: Final = Path(__file__).resolve().parent.parent / "alembic.ini"


def alembic_config(connection: Connection) -> Config:
    config = Config(str(INI))
    config.attributes["connection"] = connection
    return config


async def upgrade(engine: AsyncEngine, revision: str = "head") -> None:
    def run(connection: Connection) -> None:
        command.upgrade(alembic_config(connection), revision)

    async with engine.connect() as connection:
        await connection.run_sync(run)


async def downgrade(engine: AsyncEngine, revision: str) -> None:
    def run(connection: Connection) -> None:
        command.downgrade(alembic_config(connection), revision)

    async with engine.connect() as connection:
        await connection.run_sync(run)


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
    schema = f"roundup_test_{uuid4().hex}"
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    get_engine.cache_clear()
    admin = get_engine()
    async with admin.begin() as connection:
        _ = await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin.dispose()
    get_engine.cache_clear()
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    engine = get_engine()
    try:
        yield engine
    finally:
        try:
            async with engine.begin() as connection:
                _ = await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await get_engine().dispose()
            await engine.dispose()
            get_engine.cache_clear()


@pytest.fixture
async def migrated(empty_database: AsyncEngine) -> AsyncEngine:
    await upgrade(empty_database)
    return empty_database


@pytest.fixture
async def database(migrated: AsyncEngine) -> AsyncEngine:
    async with migrated.begin() as connection:
        _ = await apply_seed(connection, NOW.date())
    return migrated


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("ROUNDUP_API_KEY", "synthetic-test-key")
    app.dependency_overrides[current_time] = lambda: NOW
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=20,
            headers={"X-Roundup-Key": "synthetic-test-key"},
        ) as http:
            yield http
    finally:
        app.dependency_overrides.clear()
