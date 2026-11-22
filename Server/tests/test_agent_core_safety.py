"""A newer request replaces an older card, every failure ends in an answer, and old undo text goes away."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Final

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agent_hcx import ChatTurn, ModelUnavailableError, Turn, hcx_tool_chat
from agent_invoice_store import InvoiceChoice, InvoiceRequest, InvoiceResult, register_invoices
from agent_perform import STORAGE, SUPERSEDED
from agent_run import claim_run, queue_run, run_agent, run_claimed
from agent_store import NO_ANSWER, UNDO_KEPT_FOR
from agent_tools import TOOLS
from agent_types import Outcome, Plan, RunRequest, TargetRef, ToolEnv
from ai import AskResponse
from database import transaction
from shipments import INVOICE_LOCK, InvoiceRegistration, register_invoice
from tests.agent_core_support import (
    ORDER,
    Body,
    ask,
    bounded,
    chat_of,
    execute,
    rows,
    says,
    scalar,
    set_mode,
    wants,
)
from tests.conftest import NOW, downgrade, upgrade

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
PACKED: Final = "1040 포장 끝났어"
SEND_ID: Final = "0b5b0f6e-5a6c-4c1e-9a2f-1d3c5e7a9b22"
PLAIN: Final = "읽어서 알려 드릴게요."
NUMBER: Final = "610311119284"
CARRIER: Final = "CJ대한통운"


@pytest.fixture
async def database(database: AsyncEngine) -> AsyncEngine:
    """Switch the assistant on; a new schema leaves it off."""
    await set_mode(database, "auto")
    return database


@pytest.fixture(autouse=True)
def plain_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(body: object, now: object) -> AskResponse:
        del body, now
        return AskResponse(answer=PLAIN, intent="lookup")

    monkeypatch.setattr("agent_run.ask", answered)


async def broken(*_args: object) -> ChatTurn:
    raise RuntimeError


async def card(client: AsyncClient, **more: JsonValue) -> Body:
    """Ask in a way that leaves a card to approve."""
    chat = chat_of(wants("mark_packed", order="1040"), says("네"))
    [proposal] = (await ask(client, chat, "포장할 거 있어?", **more))["proposals"]
    return proposal


async def moved_card(client: AsyncClient, day: str) -> Body:
    """Ask for one entry to move to a day."""
    chat = chat_of(wants("move_event", event="가마 소성", day=day), says("네"))
    [proposal] = (await ask(client, chat, f"가마 소성 {day[-2:]}일로 옮겨줘"))["proposals"]
    return proposal


async def approve(client: AsyncClient, proposal: Body) -> int:
    path = f"/agent/proposals/{proposal['id']}/approve"
    answer = await client.post(path, json={"expectedRevision": proposal["expectedRevision"]})
    return answer.status_code


async def closed(database: AsyncEngine, proposal: Body) -> list[tuple[object, ...]]:
    return await rows(
        database, "SELECT state, result FROM agent_proposals WHERE id = :id", id=proposal["id"],
    )


async def test_asking_the_same_again_keeps_the_open_card(database: AsyncEngine, client: AsyncClient) -> None:
    first, second = await card(client), await card(client)
    assert first["id"] == second["id"]
    assert await scalar(database, "SELECT count(*) FROM agent_proposals") == 1


async def test_another_date_replaces_the_open_card(database: AsyncEngine, client: AsyncClient) -> None:
    await set_mode(database, "ask")
    older, newer = await moved_card(client, "2026-11-22"), await moved_card(client, "2026-11-23")
    assert await closed(database, older) == [("dismissed", SUPERSEDED)]
    assert [item["id"] for item in (await client.get("/agent/proposals")).json()["items"]] == [newer["id"]]
    assert (await approve(client, older), await approve(client, newer)) == (409, 200)
    starts = await scalar(database, "SELECT starts_at FROM calendar_events WHERE id = 'event-firing'")
    assert isinstance(starts, datetime)
    assert starts.astimezone(NOW.tzinfo).date().isoformat() == "2026-11-23"


async def test_a_run_that_acts_closes_the_card_it_answers(database: AsyncEngine, client: AsyncClient) -> None:
    waiting = await card(client)
    body = await ask(client, chat_of(wants("mark_packed", order="1040"), says("네")), PACKED)
    assert [step["decision"] for step in body["steps"]] == ["auto"]
    assert await closed(database, waiting) == [("dismissed", SUPERSEDED)]


@pytest.mark.parametrize("read", ["detail", "list", "replay"])
async def test_an_expired_card_is_closed_on_every_read_and_never_reused(
    database: AsyncEngine, client: AsyncClient, read: str,
) -> None:
    waiting = await card(client, requestId=SEND_ID)
    await execute(
        database, "UPDATE agent_proposals SET expires_at = :past", past=NOW - timedelta(seconds=1),
    )
    run_id = await scalar(database, "SELECT id FROM agent_runs")
    match read:
        case "detail":
            run = (await client.get(f"/agent/runs/{run_id}")).json()
        case "list":
            [run] = (await client.get("/agent/runs")).json()["items"]
        case _:
            run = await ask(client, chat_of(), "포장할 거 있어?", requestId=SEND_ID)
    assert [item["state"] for item in run["proposals"]] == ["expired"]
    assert (await card(client))["id"] != waiting["id"]


async def test_a_loop_that_breaks_before_acting_answers_plainly(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    body = await ask(client, chat_of(wants("find_orders"), broken), "주문 현황 알려줘")
    assert (body["status"], body["answer"]) == ("fallback", PLAIN)
    assert await rows(database, "SELECT status, error FROM agent_runs") == [("fallback", "loop_failed")]


async def test_a_loop_that_breaks_after_acting_says_what_was_done(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    body = await ask(client, chat_of(wants("mark_packed", order="1040"), broken), PACKED)
    assert body["status"] == "failed"
    assert "끝낸 일" in body["answer"]
    assert "남은 건 이어서 부탁해 주세요" in body["answer"]
    assert await rows(database, "SELECT status, error FROM agent_runs") == [("failed", "loop_failed")]
    status = await scalar(database, "SELECT status FROM shipments WHERE id = :id", id=ORDER)
    assert status == "invoice_pending"


async def test_a_run_that_cannot_be_prepared_answers_plainly(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent_run.prompt_notes", broken)
    body = await ask(client, chat_of(), PACKED)
    assert (body["status"], body["answer"], body["steps"]) == ("fallback", PLAIN, [])
    _ = await queue_run(RunRequest(question=PACKED), NOW)
    claimed = await claim_run(NOW)
    assert claimed is not None
    assert await run_claimed(claimed, NOW, chat_of()) == "fallback"
    assert await rows(database, "SELECT DISTINCT status, error FROM agent_runs") == [
        ("fallback", "prepare_failed"),
    ]


async def test_a_tool_that_breaks_is_refused_and_leaves_nothing_behind(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    plan = TOOLS["mark_packed"].plan

    async def breaking(db: AsyncSession, raw: dict[str, JsonValue], env: ToolEnv) -> Plan:
        planned = await plan(db, raw, env)

        async def execute_then_break(session: AsyncSession, target: TargetRef) -> Outcome:
            _ = await planned.execute(session, target)
            raise RuntimeError

        return replace(planned, execute=execute_then_break)

    object.__setattr__(TOOLS["mark_packed"], "plan", breaking)
    try:
        body = await ask(client, chat_of(wants("mark_packed", order="1040"), says("네")), PACKED)
    finally:
        object.__setattr__(TOOLS["mark_packed"], "plan", plan)
    assert [(step["decision"], step["reason"]) for step in body["steps"]] == [("refused", STORAGE)]
    assert "건너뛴 일" in body["answer"]
    assert await scalar(database, "SELECT status FROM shipments WHERE id = :id", id=ORDER) == "packing"
    assert await scalar(database, "SELECT status FROM agent_runs") == "done"


async def test_a_plain_answer_that_breaks_still_answers(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent_run.ask", broken)
    body = await ask(client, chat_of(ModelUnavailableError()), "오늘 주문 몇 건이야?")
    assert (body["status"], body["answer"]) == ("fallback", NO_ANSWER)
    assert await scalar(database, "SELECT answer FROM agent_runs") == NO_ANSWER


async def test_a_cancelled_run_is_not_answered_by_the_fallback(database: AsyncEngine) -> None:
    started = asyncio.Event()

    async def hanging() -> ChatTurn:
        started.set()
        _ = await asyncio.Event().wait()
        return says("늦은 답이에요.")

    async with bounded():
        task = asyncio.create_task(run_agent(RunRequest(question=PACKED), NOW, chat_of(hanging)))
        _ = await started.wait()
        _ = task.cancel()
        with pytest.raises(asyncio.CancelledError):
            _ = await task
    assert await scalar(database, "SELECT status FROM agent_runs") == "failed"
    assert await scalar(database, "SELECT error FROM agent_runs") == "cancelled"


async def test_a_missing_model_key_is_a_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOVA_STUDIO_API_KEY", raising=False)
    with pytest.raises(ModelUnavailableError):
        _ = await hcx_tool_chat([Turn("user", "안녕")], (), max_tokens=8, seconds=1)


@pytest.mark.parametrize(("hours", "kept"), [(47, True), (49, False)])
async def test_undo_text_is_kept_for_two_days(
    database: AsyncEngine, client: AsyncClient, hours: int, *, kept: bool,
) -> None:
    chat = chat_of(
        wants("save_content_draft", draft="주말 클래스 모집 글", text="새 본문이에요."), says("네"),
    )
    body = await ask(client, chat, "주말 클래스 모집 글을 바꿔줘")
    [step] = body["steps"]
    assert step["undoable"] is True
    await execute(
        database,
        "UPDATE agent_steps SET undo_until = :moment",
        moment=NOW + UNDO_KEPT_FOR - timedelta(hours=hours),
    )
    _ = await ask(client, chat_of(says("네")), "안녕")
    stored = await rows(
        database, "SELECT undo_path IS NOT NULL, undo_data ->> 'body' IS NOT NULL FROM agent_steps",
    )
    assert stored == [(kept, kept)]
    shown = (await client.get(f"/agent/runs/{body['runId']}")).json()["steps"]
    assert [item["undoable"] for item in shown] == [kept]
    undone = await client.post(f"/agent/steps/{step['id']}/undo")
    assert undone.status_code == (200 if kept else 409)


async def test_a_new_or_rebuilt_schema_leaves_the_assistant_off(migrated: AsyncEngine) -> None:
    assert await scalar(migrated, "SELECT mode FROM agent_settings") == "off"
    await set_mode(migrated, "auto")
    await downgrade(migrated, "0005_k25")
    await upgrade(migrated)
    assert await scalar(migrated, "SELECT mode FROM agent_settings") == "off"


async def waits_for_invoice_lock(database: AsyncEngine, task: asyncio.Task[object]) -> bool:
    """Tell when a task stands behind the invoice lock; false when it finished without waiting."""
    query = (
        "SELECT count(*) FROM pg_locks JOIN pg_database ON pg_database.oid = pg_locks.database "
        "WHERE datname = current_database() AND locktype = 'advisory' AND NOT granted AND objid = :key"
    )
    while not task.done():
        if await scalar(database, query, key=INVOICE_LOCK):
            return True
    return False


async def register_1041(db: AsyncSession) -> list[InvoiceResult]:
    """Register one number the owner's words carry, as the assistant does."""
    choice = InvoiceChoice("shipment-order-1041", 0, CARRIER, NUMBER)
    request = InvoiceRequest(
        f"1041 CJ {NUMBER}", (choice,), all_or_nothing=True, decided_by="owner", source="turn",
    )
    return await register_invoices(db, request, NOW)


async def test_the_app_waits_for_the_assistants_invoice(database: AsyncEngine, client: AsyncClient) -> None:
    await execute(database, "UPDATE shipments SET status = 'invoice_pending' WHERE id = :id", id=ORDER)
    body = {"expectedRevision": 0, "carrier": CARRIER, "trackingNumber": NUMBER}
    async with bounded():
        async with transaction() as db:
            [sent] = await register_1041(db)
            manual = asyncio.create_task(client.post(f"/shipments/{ORDER}/invoice", json=body))
            assert await waits_for_invoice_lock(database, manual)
        answer = await manual
    assert (sent.outcome, answer.status_code) == ("registered", 409)
    holders = await rows(database, "SELECT id FROM shipments WHERE tracking_number = :number", number=NUMBER)
    assert holders == [("shipment-order-1041",)]


async def test_the_assistant_waits_for_the_apps_invoice(database: AsyncEngine) -> None:
    await execute(database, "UPDATE shipments SET status = 'invoice_pending' WHERE id = :id", id=ORDER)
    body = InvoiceRegistration.model_validate(
        {"expectedRevision": 0, "carrier": CARRIER, "trackingNumber": NUMBER},
    )

    async def assistant() -> list[InvoiceResult]:
        async with transaction() as db:
            return await register_1041(db)

    async with bounded():
        async with transaction() as db:
            _ = await register_invoice(ORDER, body, db, NOW)
            late = asyncio.create_task(assistant())
            assert await waits_for_invoice_lock(database, late)
        [result] = await late
    assert result.outcome == "refused"
    holders = await rows(database, "SELECT id FROM shipments WHERE tracking_number = :number", number=NUMBER)
    assert holders == [(ORDER,)]
