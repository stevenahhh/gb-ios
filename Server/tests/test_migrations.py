"""Versioned schema behavior on empty and already-deployed databases."""

import importlib.util
from pathlib import Path
from typing import Final

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from httpx2 import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

import models
from database import Base
from tests.conftest import downgrade, upgrade

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
BASELINE: Final = Path(__file__).resolve().parent.parent / "migrations/versions/0001_inquiries_baseline.py"
EDITED: Final = "사장님이 고친 초안"
LEGACY_DDL: Final = """
CREATE TABLE inquiries (
    id TEXT NOT NULL PRIMARY KEY, customer TEXT NOT NULL, subject TEXT NOT NULL, question TEXT NOT NULL,
    facts TEXT[] NOT NULL, draft TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
    CHECK (status IN ('pending', 'approved', 'rejected')), CHECK (revision >= 0)
)
"""


def baseline_error() -> type[Exception]:
    """Load the error class from the revision file Alembic imported by path."""
    spec = importlib.util.spec_from_file_location("baseline_revision", BASELINE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.IncompatibleInquiriesTableError


async def create_legacy_table(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        _ = await connection.execute(text(LEGACY_DDL))
        _ = await connection.execute(
            text(
                "INSERT INTO inquiries VALUES ('inquiry-group', '이도윤 (가상 고객)', '제목', '질문', "
                "ARRAY['데모 규칙 · 문의 답변 승인으로 예약이 생성되지 않습니다.', '수업 정원 · 최대 6명'], "
                ":draft, 'approved', 4)",
            ),
            {"draft": EDITED},
        )


async def test_upgrade_from_empty_matches_every_model(empty_database: AsyncEngine) -> None:
    await upgrade(empty_database)

    def differences(connection: Connection) -> list[tuple[str, ...]]:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    async with empty_database.connect() as connection:
        assert await connection.run_sync(differences) == []
    assert models.InquiryRow.__tablename__ in Base.metadata.tables


async def test_upgrade_adopts_inquiries_only_schema_without_losing_owner_work(
    empty_database: AsyncEngine,
) -> None:
    await create_legacy_table(empty_database)
    await upgrade(empty_database)
    async with empty_database.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT customer, facts, draft, status, revision, received_at IS NOT NULL FROM inquiries",
                ),
            )
        ).one()
    assert row == (
        "이도윤",
        ["예약 안내 · 문의 답변을 승인해도 예약은 자동으로 만들어지지 않습니다.", "수업 정원 · 최대 6명"],
        EDITED,
        "approved",
        4,
        True,
    )


async def test_incompatible_existing_table_stops_the_migration(empty_database: AsyncEngine) -> None:
    async with empty_database.begin() as connection:
        _ = await connection.execute(text("CREATE TABLE inquiries (id text PRIMARY KEY)"))
    with pytest.raises(Exception) as failure:  # noqa: PT011 - Alembic imports its own module copy.
        await upgrade(empty_database)
    assert failure.type.__name__ == baseline_error().__name__
    async with empty_database.connect() as connection:
        version_table = await connection.scalar(text("SELECT to_regclass('alembic_version')"))
    assert version_table is None


async def test_downgrade_keeps_inquiries_and_upgrade_restores_tables(empty_database: AsyncEngine) -> None:
    await create_legacy_table(empty_database)
    await upgrade(empty_database)
    await downgrade(empty_database, "0001")
    async with empty_database.connect() as connection:
        assert await connection.scalar(text("SELECT draft FROM inquiries")) == EDITED
        with pytest.raises(SQLAlchemyError):
            _ = await connection.execute(text("SELECT 1 FROM bookings"))
    await upgrade(empty_database)
    async with empty_database.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM bookings")) == 0


async def test_readiness_requires_the_release_schema_version(
    empty_database: AsyncEngine,
    client: AsyncClient,
) -> None:
    assert (await client.get("/health/ready")).status_code == 503
    await upgrade(empty_database, "0001")
    assert (await client.get("/health/ready")).status_code == 503
    await upgrade(empty_database)
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
