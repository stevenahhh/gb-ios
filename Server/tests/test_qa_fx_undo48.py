"""A finished step can be taken back for 48 hours from the moment it ran, by any tool, and not after."""

from datetime import datetime, timedelta

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_perform import purge_old_undo
from agent_store import UNDO_KEPT_FOR
from agent_tools import TOOLS
from common import current_time
from main import app
from tests.agent_core_support import Body, ask, chat_of, execute, rows, says, scalar, set_mode, wants
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
MINUTE = timedelta(minutes=1)
UNDOABLE = sorted(name for name, tool in TOOLS.items() if tool.undo is not None)
EVENTS = "SELECT count(*) FROM calendar_events WHERE title = '재고 확인'"


def at(moment: datetime) -> None:
    app.dependency_overrides[current_time] = lambda: moment


async def add_event(engine: AsyncEngine, client: AsyncClient, mode: str) -> Body:
    await set_mode(engine, mode)
    chat = chat_of(wants("add_event", title="재고 확인", day="2026-11-20", time="15:00"), says("네"))
    return await ask(client, chat, "금요일 3시에 재고 확인 일정 넣어줘")


async def approved_after(engine: AsyncEngine, client: AsyncClient, wait: timedelta) -> Body:
    """Raise a proposal at NOW and approve it after `wait`; return the run."""
    body = await add_event(engine, client, "ask")
    [proposal] = body["proposals"]
    at(NOW + wait)
    accepted = await client.post(
        f"/agent/proposals/{proposal['id']}/approve",
        json={"expectedRevision": proposal["expectedRevision"]},
    )
    assert accepted.status_code == 200, accepted.text
    return body


async def shown(client: AsyncClient, run_id: str) -> list[bool]:
    """Read whether the app offers undo, from the run, the run list, and the proposal's step."""
    one = (await client.get(f"/agent/runs/{run_id}")).json()
    [listed] = [item for item in (await client.get("/agent/runs")).json()["items"] if item["id"] == run_id]
    views = [*one["steps"], *listed["steps"]]
    views += [item["step"] for item in one["proposals"] if item["step"] is not None]
    return [view["undoable"] for view in views]


@pytest.mark.parametrize("tool", UNDOABLE)
async def test_every_tool_closes_after_48_hours_without_a_purge(
    database: AsyncEngine, client: AsyncClient, tool: str,
) -> None:
    body = await add_event(database, client, "auto")
    [step] = body["steps"]
    await execute(database, "UPDATE agent_steps SET tool = :tool WHERE id = :id", tool=tool, id=step["id"])
    at(NOW + UNDO_KEPT_FOR + MINUTE)
    before = await rows(database, "SELECT undone_at, undo_path FROM agent_steps")
    refused = await client.post(f"/agent/steps/{step['id']}/undo")
    assert refused.status_code == 409, refused.text
    assert await rows(database, "SELECT undone_at, undo_path FROM agent_steps") == before


@pytest.mark.parametrize("purged", [False, True])
@pytest.mark.parametrize(("late", "open_"), [(-MINUTE, True), (timedelta(), True), (MINUTE, False)])
async def test_an_automatic_step_counts_from_the_moment_it_ran(
    database: AsyncEngine, client: AsyncClient, late: timedelta, *, open_: bool, purged: bool,
) -> None:
    body = await add_event(database, client, "auto")
    [step] = body["steps"]
    moment = NOW + UNDO_KEPT_FOR + late
    at(moment)
    if purged:
        await purge_old_undo(moment)
    assert set(await shown(client, body["runId"])) == {open_}
    undone = await client.post(f"/agent/steps/{step['id']}/undo")
    assert undone.status_code == (200 if open_ else 409), undone.text
    assert await scalar(database, EVENTS) == (0 if open_ else 1)


@pytest.mark.parametrize("purged", [False, True])
@pytest.mark.parametrize(("late", "open_"), [(-MINUTE, True), (timedelta(), True), (MINUTE, False)])
async def test_an_approved_step_counts_from_its_approval(
    database: AsyncEngine, client: AsyncClient, late: timedelta, *, open_: bool, purged: bool,
) -> None:
    wait = timedelta(hours=23)
    body = await approved_after(database, client, wait)
    [step] = body["steps"]
    moment = NOW + wait + UNDO_KEPT_FOR + late
    at(moment)
    if purged:
        await purge_old_undo(moment)
    assert set(await shown(client, body["runId"])) == {open_}
    undone = await client.post(f"/agent/steps/{step['id']}/undo")
    assert undone.status_code == (200 if open_ else 409), undone.text
    assert await scalar(database, EVENTS) == (0 if open_ else 1)


async def test_the_purge_writes_a_closed_step_once(database: AsyncEngine, client: AsyncClient) -> None:
    _ = await add_event(database, client, "auto")
    moment = NOW + UNDO_KEPT_FOR + MINUTE
    await purge_old_undo(moment)
    version = await scalar(database, "SELECT xmin::text FROM agent_steps")
    await purge_old_undo(moment)
    assert await scalar(database, "SELECT xmin::text FROM agent_steps") == version
    assert await scalar(database, "SELECT undo_path FROM agent_steps") is None
