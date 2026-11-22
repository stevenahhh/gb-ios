"""Left-over work joins today's list only when asked, keeps its deadline, and can be taken back."""

from datetime import date, datetime
from typing import Final

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from common import current_time
from display import SEOUL
from main import app
from seed import apply_seed
from tests.conftest import NOW, downgrade, upgrade

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
type Body = dict[str, JsonValue]
CARRY: Final = "/today/carry-overs"
UNDO: Final = "/today/carry-overs/undo"
TASK: Final = ("task", "task-clay")
PARCEL: Final = ("shipment", "shipment-order-1040")
TOMORROW: Final = datetime(2026, 11, 19, 0, 30, tzinfo=SEOUL)
WORK: Final = """
    SELECT id, due_at, status, revision FROM tasks
    UNION ALL SELECT id, ship_by_at, status, revision FROM shipments ORDER BY id
"""


def rows(*pairs: tuple[str, str]) -> Body:
    return {"items": [{"target": target, "id": row_id} for target, row_id in pairs]}


async def fetch(database: AsyncEngine, query: str) -> list[tuple[object, ...]]:
    async with database.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(query))).all()]


async def stored(database: AsyncEngine) -> list[tuple[object, ...]]:
    return await fetch(database, "SELECT target, target_id, carried_on FROM carry_overs ORDER BY target")


async def flags(client: AsyncClient) -> dict[tuple[str, str], bool]:
    groups = (await client.get("/today")).json()["tasks"]["groups"]
    return {(item["target"], item["id"]): item["carriedOver"] for group in groups for item in group["items"]}


async def carried(client: AsyncClient) -> set[tuple[str, str]]:
    return {key for key, flag in (await flags(client)).items() if flag}


@pytest.fixture
async def overdue(database: AsyncEngine) -> AsyncEngine:
    """One task and one parcel were due on the last second of yesterday in Seoul."""
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "UPDATE tasks SET due_at = '2026-11-17 23:59:59+09' WHERE id = 'task-clay'",
        ))
        _ = await connection.execute(text(
            "UPDATE shipments SET ship_by_at = '2026-11-17 23:59:59+09' WHERE id = 'shipment-order-1040'",
        ))
    return database


@pytest.mark.parametrize("key", [TASK, PARCEL])
async def test_carry_then_undo_changes_only_the_flag(
    overdue: AsyncEngine, client: AsyncClient, key: tuple[str, str],
) -> None:
    work, before = await fetch(overdue, WORK), (await client.get("/today")).json()
    assert await carried(client) == set()
    response = await client.post(CARRY, json=rows(key))
    assert (response.status_code, response.content) == (204, b"")
    assert await carried(client) == {key}
    assert await stored(overdue) == [(*key, NOW.date())]
    assert await fetch(overdue, WORK) == work
    after = (await client.get("/today")).json()
    for group in after["tasks"]["groups"]:
        for item in group["items"]:
            item["carriedOver"] = False
    assert after == before
    for _ in range(2):
        assert (await client.post(UNDO, json=rows(key))).status_code == 204
    assert (await client.get("/today")).json() == before
    assert await stored(overdue) == []


async def test_undo_takes_back_only_the_named_rows(overdue: AsyncEngine, client: AsyncClient) -> None:
    assert (await client.post(CARRY, json=rows(TASK, PARCEL))).status_code == 204
    assert (await client.post(UNDO, json=rows(TASK, ("task", "missing")))).status_code == 204
    assert await carried(client) == {PARCEL}


async def test_carrying_again_today_is_idempotent(overdue: AsyncEngine, client: AsyncClient) -> None:
    for body in (rows(TASK), rows(TASK), rows(PARCEL, TASK, TASK)):
        assert (await client.post(CARRY, json=body)).status_code == 204
    assert await stored(overdue) == [(*PARCEL, NOW.date()), (*TASK, NOW.date())]


async def test_a_carry_over_ends_with_its_seoul_day_and_can_be_repeated(
    overdue: AsyncEngine, client: AsyncClient,
) -> None:
    assert (await client.post(CARRY, json=rows(TASK, PARCEL))).status_code == 204
    app.dependency_overrides[current_time] = lambda: TOMORROW
    expired = await flags(client)
    assert (expired[TASK], expired[PARCEL]) == (False, False)
    assert (await client.post(CARRY, json=rows(TASK))).status_code == 204
    assert await carried(client) == {TASK}
    assert await stored(overdue) == [(*PARCEL, NOW.date()), (*TASK, date(2026, 11, 19))]


@pytest.mark.parametrize("change", [
    "UPDATE tasks SET status = 'done', completed_at = now() WHERE id = 'task-clay'",
    "UPDATE tasks SET due_at = '2026-11-18 00:00+09' WHERE id = 'task-clay'",
])
async def test_ineligible_task_refuses_the_whole_batch(
    overdue: AsyncEngine, client: AsyncClient, change: str,
) -> None:
    async with overdue.begin() as connection:
        _ = await connection.execute(text(change))
    assert (await client.post(CARRY, json=rows(PARCEL, TASK))).status_code == 409
    assert await stored(overdue) == []


@pytest.mark.parametrize(("change", "status"), [
    ("status = 'invoice_pending'", 204),
    ("status = 'in_transit', carrier = '택배', tracking_number = '1'", 409),
    ("status = 'delivered', carrier = '택배', tracking_number = '1'", 409),
    ("ship_by_at = '2026-11-18 00:00+09'", 409),
])
async def test_parcel_is_carried_only_while_unshipped_and_late(
    overdue: AsyncEngine, client: AsyncClient, change: str, status: int,
) -> None:
    async with overdue.begin() as connection:
        _ = await connection.execute(text(f"UPDATE shipments SET {change} WHERE id = 'shipment-order-1040'"))  # noqa: S608
    assert (await client.post(CARRY, json=rows(PARCEL))).status_code == status
    assert len(await stored(overdue)) == (status == 204)


@pytest.mark.parametrize("missing", [("task", "zz"), ("shipment", "zz"), ("shipment", "task-clay")])
async def test_unknown_row_refuses_the_whole_batch(
    overdue: AsyncEngine, client: AsyncClient, missing: tuple[str, str],
) -> None:
    assert (await client.post(CARRY, json=rows(TASK, PARCEL, missing))).status_code == 404
    assert await stored(overdue) == []


@pytest.mark.parametrize("path", [CARRY, UNDO])
@pytest.mark.parametrize("body", [
    {"items": []},
    rows(*[("task", f"task-{index}") for index in range(101)]),
    rows(("session", "session-today-morning")),
])
async def test_invalid_body_is_refused(
    database: AsyncEngine, client: AsyncClient, path: str, body: Body,
) -> None:
    assert (await client.post(path, json=body)).status_code == 422


async def test_a_recreated_parcel_does_not_inherit_the_carry_over(
    overdue: AsyncEngine, client: AsyncClient,
) -> None:
    assert (await client.post(CARRY, json=rows(TASK, PARCEL))).status_code == 204
    undone = await client.post("/orders/order-1040/undo-confirm", json={"expectedRevision": 0})
    assert undone.status_code == 200
    confirmed = await client.post("/orders/order-1040/confirm", json={"expectedRevision": 1})
    assert confirmed.status_code == 200
    current = await flags(client)
    assert (current[TASK], current[PARCEL]) == (True, False)
    assert await stored(overdue) == [(*TASK, NOW.date())]


async def test_retiring_a_seed_parcel_forgets_its_carry_over(
    overdue: AsyncEngine, client: AsyncClient,
) -> None:
    assert (await client.post(CARRY, json=rows(TASK, PARCEL))).status_code == 204
    async with overdue.begin() as connection:
        _ = await connection.execute(text("""
            INSERT INTO orders (id, order_number, customer_id, channel_id, product_name, quantity,
                                amount_won, status, ordered_at)
            SELECT 'order-collected-1', 9001, customer_id, channel_id, product_name, quantity,
                   amount_won, 'paid', ordered_at
            FROM orders WHERE id = 'order-1040'
        """))
        _ = await apply_seed(connection, NOW.date())
    assert await fetch(overdue, "SELECT id FROM shipments WHERE id = 'shipment-order-1040'") == []
    assert await stored(overdue) == [(*TASK, NOW.date())]


async def test_migration_adds_and_removes_only_its_own_table(empty_database: AsyncEngine) -> None:
    tables = "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
    await upgrade(empty_database, "0005_k25")
    before = set(await fetch(empty_database, tables))
    await upgrade(empty_database, "0006")
    assert set(await fetch(empty_database, tables)) - before == {("carry_overs",)}
    await downgrade(empty_database, "0005_k25")
    assert set(await fetch(empty_database, tables)) == before
    await upgrade(empty_database)
    assert await stored(empty_database) == []
