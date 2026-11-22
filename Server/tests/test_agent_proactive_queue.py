"""The worker answers the owner's queued questions through the core; nothing else may reach the model."""

from collections.abc import Sequence
from datetime import datetime
from typing import Final

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import agent_worker
from agent_hcx import ChatTurn, ToolDefinition, Turn
from agent_run import queue_run
from agent_store import owner_lock
from agent_types import RunRequest
from agent_worker import run_one, run_queue
from tests.agent_proactive_support import MINUTE, NOW, set_settings

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
QUESTION: Final = "오늘 예약이 몇 건이에요?"


class ScriptedChat:
    def __init__(self) -> None:
        self.calls: int = 0

    async def __call__(
        self, _messages: Sequence[Turn], _tools: Sequence[ToolDefinition], **_limits: float,
    ) -> ChatTurn:
        self.calls += 1
        return ChatTurn("오늘 예약은 두 건이에요.", (), 3)


@pytest.fixture(autouse=True)
def fixed_worker_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_worker, "current_time", lambda: NOW)


async def queue_a_question(at: datetime = NOW) -> str:
    return (await queue_run(RunRequest(question=QUESTION, background=True), at)).run_id


async def stored(engine: AsyncEngine, run_id: str) -> tuple[str, str | None]:
    async with engine.connect() as connection:
        row = (await connection.execute(
            text("SELECT status, error FROM agent_runs WHERE id = :id"), {"id": run_id},
        )).one()
    return str(row[0]), row[1]


@pytest.fixture
async def switched_on(migrated: AsyncEngine) -> AsyncEngine:
    await set_settings(mode="auto")
    return migrated


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> ScriptedChat:
    chat = ScriptedChat()
    monkeypatch.setattr(agent_worker, "hcx_tool_chat", chat)
    return chat


async def test_a_question_from_before_the_switch_on_is_never_answered(
    migrated: AsyncEngine, scripted: ScriptedChat,
) -> None:
    run_id = await queue_a_question(NOW - MINUTE)

    await run_queue(anyio.Event())
    before = (scripted.calls, await stored(migrated, run_id))
    await set_settings(mode="ask")
    await run_queue(anyio.Event())

    assert before == (0, ("queued", None))
    assert (scripted.calls, await stored(migrated, run_id)) == (0, ("failed", "stale"))


async def test_queued_questions_are_answered_once_each(
    switched_on: AsyncEngine, scripted: ScriptedChat,
) -> None:
    first, second = await queue_a_question(), await queue_a_question()

    await run_queue(anyio.Event())
    again = await run_one(NOW)

    assert [(await stored(switched_on, first))[0], (await stored(switched_on, second))[0]] == ["done", "done"]
    assert (scripted.calls, again) == (2, False)


async def test_a_question_waits_while_the_assistant_is_off(
    switched_on: AsyncEngine, scripted: ScriptedChat,
) -> None:
    run_id = await queue_a_question()
    await set_settings(mode="off")

    await run_queue(anyio.Event())

    assert (scripted.calls, await stored(switched_on, run_id)) == (0, ("queued", None))


async def test_a_stopping_worker_starts_nothing_new(switched_on: AsyncEngine, scripted: ScriptedChat) -> None:
    run_id = await queue_a_question()
    stop = anyio.Event()
    stop.set()

    await run_queue(stop)

    assert (scripted.calls, await stored(switched_on, run_id)) == (0, ("queued", None))


async def test_a_failing_run_is_closed_as_failed_and_the_next_one_still_runs(
    switched_on: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(_run: object, _now: object, _chat: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(agent_worker, "run_claimed", broken)
    first, second = await queue_a_question(), await queue_a_question()

    await run_queue(anyio.Event())

    outcomes = [await stored(switched_on, first), await stored(switched_on, second)]
    assert outcomes == [("failed", "RuntimeError"), ("failed", "RuntimeError")]


async def test_a_question_goes_back_to_the_queue_while_the_owner_is_busy(
    switched_on: AsyncEngine, scripted: ScriptedChat,
) -> None:
    run_id = await queue_a_question()

    async with owner_lock():
        answered = await run_one(NOW)
    waiting = await stored(switched_on, run_id)
    later = await run_one(NOW)

    assert (answered, waiting, later) == (False, ("queued", None), True)
    assert (await stored(switched_on, run_id))[0] == "done"
