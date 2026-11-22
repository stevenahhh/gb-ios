from datetime import timedelta

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

import agent_run
from agent_perform import Performed, RunContext, perform
from agent_run import claim_run, queue_run
from agent_types import RunRequest, ToolCall
from ai import AskResponse
from tests.agent_core_support import ORDER, ask, chat_of, rows, says, scalar, set_mode, wants
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


async def test_switching_off_during_a_tool_stops_before_the_next_model_call(
    database: AsyncEngine,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await set_mode(database, "auto")

    async def switched_off_meanwhile(context: RunContext, call: ToolCall) -> Performed:
        performed = await perform(context, call)
        await set_mode(database, "off")
        return performed

    monkeypatch.setattr(agent_run, "perform", switched_off_meanwhile)
    chat = chat_of(wants("find_orders"), says("네"))
    body = await ask(client, chat, "오늘 주문 뭐 있어?")
    assert (len(chat.seen), body["status"]) == (1, "stopped")


async def test_a_background_run_while_off_is_answered_at_once(
    database: AsyncEngine,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answered(_body: object, _now: object) -> AskResponse:
        return AskResponse(answer="읽어서 알려 드릴게요.", intent="lookup")

    monkeypatch.setattr(agent_run, "ask", answered)
    await set_mode(database, "off")
    body = await ask(client, chat_of(), "1040 포장 끝났어", background=True)
    assert (body["status"], body["mode"], body["answer"]) == ("fallback", "off", "읽어서 알려 드릴게요.")
    assert await rows(database, "SELECT id FROM agent_runs WHERE status = 'queued'") == []


@pytest.mark.parametrize(("minutes", "claimed"), [(10, True), (11, False)])
async def test_a_queued_run_older_than_ten_minutes_is_not_started(
    database: AsyncEngine, minutes: int, *, claimed: bool,
) -> None:
    await set_mode(database, "auto")
    run_id = (await queue_run(RunRequest(question="1040 포장 끝났어", background=True), NOW)).run_id
    run = await claim_run(NOW + timedelta(minutes=minutes))
    assert (run is not None) is claimed
    status = await scalar(database, "SELECT status FROM agent_runs WHERE id = :id", id=run_id)
    assert status == ("running" if claimed else "failed")


async def test_a_proposal_of_a_switched_off_tool_is_not_approved(
    database: AsyncEngine,
    client: AsyncClient,
) -> None:
    await set_mode(database, "ask")
    body = await ask(client, chat_of(wants("mark_packed", order="1040"), says("네")), "1040 포장 끝났어")
    [card] = body["proposals"]
    await set_mode(database, "ask", mark_packed="off")
    refused = await client.post(
        f"/agent/proposals/{card['id']}/approve", json={"expectedRevision": card["expectedRevision"]},
    )
    assert refused.status_code == 409
    assert await scalar(database, "SELECT status FROM shipments WHERE id = :id", id=ORDER) == "packing"


async def test_a_file_is_not_approved_while_invoices_are_switched_off(
    database: AsyncEngine,
    client: AsyncClient,
) -> None:
    await set_mode(database, "auto", register_invoice="off")
    refused = await client.post("/agent/invoices/any/approve?filename=a.csv", content=b"a")
    assert (refused.status_code, refused.json()["detail"][:2]) == (409, "설정")
