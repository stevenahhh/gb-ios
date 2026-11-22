"""Races of the assistant: one card per tool and row, no waiting for a held card, and runs that end."""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import agent_worker
from agent_findings import Finding
from agent_hcx import ChatTurn, ToolDefinition, Turn
from agent_run import run_agent
from agent_settings import AgentSettings
from agent_store import owner_lock
from agent_tables import AgentRunRow
from agent_types import RunRequest, RunResponse
from tests.agent_core_support import ORDER, ask, bounded, chat_of, rows, says, set_mode, wants
from tests.agent_proactive_support import store
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


async def test_a_tick_leaves_a_card_the_owner_raised_meanwhile(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await set_mode(database, "auto")
    detect = agent_worker.fresh_findings

    async def raced(db: AsyncSession, settings: AgentSettings, now: datetime) -> list[Finding]:
        found = await detect(db, settings, now)
        assert ("mark_packed", ORDER) in {(finding.tool, finding.target.id) for finding in found}
        _ = await ask(client, chat_of(wants("mark_packed", order="1040"), says("네")), "포장할 거 있어?")
        return found

    monkeypatch.setattr(agent_worker, "fresh_findings", raced)
    async with bounded():
        _ = await agent_worker.run_tick(NOW)
    twins = await rows(
        database,
        """SELECT tool, target_id FROM agent_proposals WHERE state = 'open' AND target_id IS NOT NULL
        GROUP BY tool, target_kind, target_id HAVING count(*) > 1""",
    )
    assert twins == []


async def test_a_cancelled_run_ends_and_its_send_id_answers(database: AsyncEngine) -> None:
    await set_mode(database, "auto")
    started = asyncio.Event()

    async def hanging(
        messages: Sequence[Turn], tools: Sequence[ToolDefinition], *, max_tokens: int, seconds: float,
    ) -> ChatTurn:
        del messages, tools, max_tokens, seconds
        started.set()
        _ = await asyncio.Event().wait()
        return says("끝")

    body = RunRequest.model_validate(
        {"question": "1040 포장 끝났어", "source": "chat", "requestId": "cancelled-send-0001"},
    )
    async with bounded():
        task = asyncio.create_task(run_agent(body, NOW, hanging))
        _ = await started.wait()
        _ = task.cancel()
        with pytest.raises(asyncio.CancelledError):
            _ = await task
    assert await rows(database, "SELECT status, error FROM agent_runs") == [("failed", "cancelled")]
    again = await run_agent(body, NOW, hanging)
    assert again.status == "failed"
    assert again.answer


async def test_a_held_proposal_is_refused_at_once(database: AsyncEngine, client: AsyncClient) -> None:
    await set_mode(database, "auto")
    body = await ask(client, chat_of(wants("mark_packed", order="1040"), says("네")), "포장할 거 있어?")
    [card] = RunResponse.model_validate(body).proposals
    path, revision = f"/agent/proposals/{card.id}", {"expectedRevision": card.expected_revision}
    async with bounded(10), database.connect() as other, other.begin():
        _ = await other.execute(
            text("SELECT id FROM agent_proposals WHERE id = :id FOR UPDATE"), {"id": card.id},
        )
        answers = [
            await client.post(f"{path}/approve", json=revision),
            await client.post(f"{path}/dismiss"),
            await client.post(f"/agent/invoices/{card.id}/approve?filename=a.csv", content=b"a"),
        ]
    for answer in answers:
        assert answer.status_code == 409
        assert "다른 곳에서 처리하고 있어요. 잠시 뒤 다시 확인해 주세요." in answer.text
    assert (await client.post(f"{path}/approve", json=revision)).status_code == 200
    again = await client.post(f"{path}/approve", json=revision)
    assert again.status_code == 409
    assert "이미 승인한 제안이에요." in again.text


def left_running(key: str, minutes: int) -> AgentRunRow:
    started = NOW - timedelta(minutes=minutes)
    return AgentRunRow(
        id=f"run-{key}", source="chat", question="", status="running", created_at=started, started_at=started,
    )


RUNS = "SELECT id, status, error FROM agent_runs WHERE source = 'chat' ORDER BY id"


@pytest.mark.parametrize("mode", ["off", "auto"])
async def test_a_tick_closes_what_a_dead_process_left_running(migrated: AsyncEngine, mode: str) -> None:
    await set_mode(migrated, mode)
    await store(migrated, left_running("old", 11), left_running("recent", 9))
    _ = await agent_worker.run_tick(NOW)
    assert await rows(migrated, RUNS) == [("run-old", "failed", "abandoned"), ("run-recent", "running", None)]
    [(answer,)] = await rows(migrated, "SELECT answer FROM agent_runs WHERE id = 'run-old'")
    assert "확인해 주세요" in str(answer)


async def test_a_tick_closes_nothing_while_the_owner_lock_is_held(migrated: AsyncEngine) -> None:
    await store(migrated, left_running("old", 11))
    async with owner_lock():
        _ = await agent_worker.run_tick(NOW)
    assert await rows(migrated, RUNS) == [("run-old", "running", None)]
    _ = await agent_worker.run_tick(NOW)
    assert await rows(migrated, RUNS) == [("run-old", "failed", "abandoned")]
