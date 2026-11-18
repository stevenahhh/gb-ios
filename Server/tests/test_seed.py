"""The seed is explicit, idempotent, relative to its day, and free of sample wording."""

from datetime import date, timedelta

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from seed import apply_seed
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


async def seed(engine: AsyncEngine, day: date) -> int:
    async with engine.begin() as connection:
        return await apply_seed(connection, day)


async def test_app_startup_does_not_seed(migrated: AsyncEngine, client: AsyncClient) -> None:
    today = (await client.get("/today")).json()
    assert today["tasks"]["groups"] == []
    assert (await client.get("/inquiries")).json() == []


async def test_second_run_inserts_nothing_and_keeps_owner_changes(
    migrated: AsyncEngine,
    client: AsyncClient,
) -> None:
    assert await seed(migrated, NOW.date()) > 40
    edited = await client.put(
        "/workshop",
        json={
            "name": "새 이름 공방",
            "ownerTitle": "대표",
            "phone": "",
            "address": "순천시",
            "description": "",
            "latitude": None,
            "longitude": None,
            "expectedRevision": 0,
        },
    )
    assert edited.status_code == 200
    assert await seed(migrated, NOW.date() + timedelta(days=30)) == 0
    assert (await client.get("/settings")).json()["workshop"]["name"] == "새 이름 공방"


async def test_seeded_text_has_no_sample_wording(database: AsyncEngine) -> None:
    async with database.connect() as connection:
        dump = await connection.scalar(
            text(
                "SELECT string_agg(customer || subject || array_to_string(facts, ' '), ' ') FROM inquiries",
            ),
        )
    assert dump is not None
    assert "가상" not in dump
    assert "데모" not in dump


@pytest.mark.parametrize("offset", [0, 1, 45])
async def test_seed_dates_follow_the_seeding_day(migrated: AsyncEngine, offset: int) -> None:
    day = NOW.date() + timedelta(days=offset)
    await seed(migrated, day)
    async with migrated.connect() as connection:
        local_day = await connection.scalar(
            text(
                "SELECT (starts_at AT TIME ZONE 'Asia/Seoul')::date FROM class_sessions "
                "WHERE id = 'session-today-morning'",
            ),
        )
    assert local_day == day
