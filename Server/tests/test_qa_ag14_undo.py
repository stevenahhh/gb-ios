"""Undoing an assistant's step never touches what the owner recorded afterwards."""

from datetime import timedelta

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_types import RunResponse
from common import current_time
from main import app
from tests.agent_core_support import ask, chat_of, execute, rows, says, scalar, set_mode, wants
from tests.conftest import NOW
from tests.test_agent_tools_deals import BOOKING, QUOTE, Deal, add_quote

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


async def acted(engine: AsyncEngine, client: AsyncClient, deal: Deal) -> tuple[str, str]:
    """Let the assistant act on the owner's words; return the step's and the target's id."""
    await set_mode(engine, "auto")
    body = await ask(client, chat_of(wants(deal.tool, **deal.args), says("네")), deal.said)
    [step] = RunResponse.model_validate(body).steps
    assert step.decision == "auto", step
    assert step.target is not None, step
    return step.id, step.target.id


@pytest.mark.parametrize("record", ["arrived", "notice"])
async def test_a_booking_with_a_later_record_is_not_taken_back(
    database: AsyncEngine, client: AsyncClient, record: str,
) -> None:
    step, booking = await acted(database, client, BOOKING)
    if record == "arrived":
        marked = await client.post(f"/bookings/{booking}/attendance", json={"status": "arrived"})
        assert marked.status_code == 200, marked.text
    else:
        await execute(
            database,
            """INSERT INTO policy_versions (id, workshop_id, version, rules, unread, source_text, approved_at)
            VALUES ('policy-qa', 1, 1, '[]', '{}', '', now())""",
        )
        await execute(
            database,
            """INSERT INTO policy_notices (id, booking_id, policy_version_id, noticed_at)
            VALUES ('notice-qa', :id, 'policy-qa', now())""",
            id=booking,
        )
    assert (await client.post(f"/agent/steps/{step}/undo")).status_code == 409
    assert await scalar(database, "SELECT count(*) FROM bookings WHERE id = :id", id=booking) == 1
    table = "booking_marks" if record == "arrived" else "policy_notices"
    kept = f"SELECT count(*) FROM {table} WHERE booking_id = :id"  # noqa: S608
    assert await scalar(database, kept, id=booking) == 1


async def test_a_task_the_owner_finished_again_stays_done(database: AsyncEngine, client: AsyncClient) -> None:
    await add_quote("quote-school", "task-market")
    step, _ = await acted(database, client, QUOTE)
    task = "SELECT status, revision, completed_at FROM tasks WHERE id = 'task-market'"
    [(_, revision, _)] = await rows(database, task)
    assert isinstance(revision, int)
    app.dependency_overrides[current_time] = lambda: NOW + timedelta(minutes=5)
    opened = await client.post("/tasks/task-market/undo", json={"expectedRevision": revision})
    assert opened.status_code == 200, opened.text
    again = {"done": True, "expectedRevision": revision + 1}
    assert (await client.post("/tasks/task-market/completion", json=again)).status_code == 200
    before = await rows(database, task)
    assert (await client.post(f"/agent/steps/{step}/undo")).status_code == 200
    assert await rows(database, task) == before
    assert await scalar(database, "SELECT outcome FROM outreach_quotes WHERE id = 'quote-school'") is None
