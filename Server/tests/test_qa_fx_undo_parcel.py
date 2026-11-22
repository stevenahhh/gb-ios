"""Undoing an assistant's step never touches a parcel that was made again after it."""

from typing import Final

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.agent_core_support import ORDER, ask, chat_of, rows, says, scalar, set_mode, wants
from tests.test_agent_api import UNPACKED, approve_file, assert_korean, imported, invoice_file

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
CARRIER: Final = "CJ대한통운"
NUMBERS: Final = ("610311119284", "688899990000")
STEPS: Final = ("pack", "invoice", "deliver")
TOOL: Final = {"pack": "mark_packed", "invoice": "register_invoice", "deliver": "mark_delivered"}
SAID: Final = {
    "pack": "1040 포장 끝났어",
    "invoice": f"1040 {CARRIER} {NUMBERS[0]} 송장 등록해줘",
    "deliver": "1040 도착했어",
}


@pytest.fixture
async def database(database: AsyncEngine) -> AsyncEngine:
    await set_mode(database, "auto")
    return database


async def parcel(database: AsyncEngine) -> tuple[object, ...]:
    [found] = await rows(
        database, "SELECT status, tracking_number, revision FROM shipments WHERE id = :id", id=ORDER,
    )
    return found


async def in_app(client: AsyncClient, database: AsyncEngine, path: str, **body: str) -> None:
    """Act as the owner does in the app, with the revision the app shows."""
    table = "orders" if path.startswith("/orders") else "shipments"
    query = f"SELECT revision FROM {table} WHERE id = :id"  # noqa: S608
    revision = await scalar(database, query, id=path.split("/")[2])
    response = await client.post(path, json={"expectedRevision": revision, **body})
    assert response.status_code == 200, response.text


async def owner_does(client: AsyncClient, database: AsyncEngine, step: str, number: str) -> None:
    body = {"carrier": CARRIER, "trackingNumber": number} if step == "invoice" else {}
    await in_app(client, database, f"/shipments/{ORDER}/{step}", **body)


async def made_again(client: AsyncClient, database: AsyncEngine, last: str) -> None:
    """Take the parcel back, confirm its order again, and bring the new parcel just as far."""
    for _ in range(STEPS.index(last) + 1):
        await in_app(client, database, f"/shipments/{ORDER}/undo")
    await in_app(client, database, "/orders/order-1040/undo-confirm")
    await in_app(client, database, "/orders/order-1040/confirm")
    for step in STEPS[: STEPS.index(last) + 1]:
        await owner_does(client, database, step, NUMBERS[1])


async def assistant_does(client: AsyncClient, database: AsyncEngine, last: str) -> str:
    """Let the owner bring the parcel up to a step the assistant then takes; return that step's id."""
    for step in STEPS[: STEPS.index(last)]:
        await owner_does(client, database, step, NUMBERS[0])
    more = {"tracking_number": NUMBERS[0], "carrier": CARRIER} if last == "invoice" else {}
    body = await ask(client, chat_of(wants(TOOL[last], order="1040", **more), says("네")), SAID[last])
    [step] = body["steps"]
    assert step["decision"] == "auto", step
    return step["id"]


@pytest.mark.parametrize("last", STEPS)
async def test_an_old_undo_leaves_a_parcel_made_again(
    database: AsyncEngine, client: AsyncClient, last: str,
) -> None:
    step = await assistant_does(client, database, last)
    _, _, revision = await parcel(database)
    await made_again(client, database, last)
    before = await parcel(database)
    assert before[2] == revision
    assert_korean(await client.post(f"/agent/steps/{step}/undo"), 409)
    assert await parcel(database) == before


async def test_an_old_undo_of_an_approved_card_leaves_a_parcel_made_again(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    body = await ask(client, chat_of(wants("mark_packed", order="1040"), says("네")), "포장할 거 있어?")
    [proposal] = body["proposals"]
    answer = {"expectedRevision": proposal["expectedRevision"]}
    approved = await client.post(f"/agent/proposals/{proposal['id']}/approve", json=answer)
    assert approved.status_code == 200, approved.text
    await made_again(client, database, "pack")
    before = await parcel(database)
    assert_korean(await client.post(f"/agent/steps/{proposal['stepId']}/undo"), 409)
    assert await parcel(database) == before


async def test_an_old_undo_of_a_file_row_leaves_a_parcel_made_again(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    await owner_does(client, database, "pack", "")
    data = invoice_file(UNPACKED)
    approved = await approve_file(client, (await imported(client, data))["proposalId"], data)
    assert approved.status_code == 200, approved.text
    [step] = approved.json()["steps"]
    _, _, revision = await parcel(database)
    await made_again(client, database, "invoice")
    before = await parcel(database)
    assert before == ("in_transit", NUMBERS[1], revision)
    assert_korean(await client.post(f"/agent/steps/{step['id']}/undo"), 409)
    assert await parcel(database) == before


async def test_the_new_parcels_own_step_is_still_undone(database: AsyncEngine, client: AsyncClient) -> None:
    _ = await assistant_does(client, database, "pack")
    await made_again(client, database, "pack")
    await in_app(client, database, f"/shipments/{ORDER}/undo")
    step = await assistant_does(client, database, "pack")
    assert (await client.post(f"/agent/steps/{step}/undo")).status_code == 200
    assert (await parcel(database))[0] == "packing"
