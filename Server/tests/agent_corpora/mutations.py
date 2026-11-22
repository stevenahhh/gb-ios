"""Guards switched off one at a time; each switch must make its named case fail."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import agent_perform
import agent_policy
import agent_run
import agent_tools
import agent_tools_orders
from agent_run import RunSeed
from agent_types import Outcome, Plan, Resolution, RunRequest, TargetRef, Tool, ToolEnv, ToolRule
from prompts import HistoryTurn
from tests.agent_corpora import harness
from tests.agent_corpora.cases import BumpOp
from tests.agent_corpora.harness import apply


@dataclass(frozen=True, slots=True)
class Mutation:
    rule: str
    case: str
    apply: Callable[[pytest.MonkeyPatch], None]


async def no_count(_db: AsyncSession, _now: object) -> int:
    return 0


async def no_stop() -> bool:
    return False


def evidence_anywhere(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_policy, "find_evidence", lambda claim, _turn, _today: claim.value)


def questions_count(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_policy, "is_question", lambda _sentence: False)


def negations_count(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_policy, "is_negated", lambda _sentence: False)


def request_ids_ignored(patch: pytest.MonkeyPatch) -> None:
    original = agent_run.start

    async def start(seed: RunSeed, now: object) -> object:
        return await original(replace(seed, request_id=None), now)

    patch.setattr(agent_run, "start", start)


def voice_is_chat(patch: pytest.MonkeyPatch) -> None:
    original = harness.run_agent

    async def run_agent(body: RunRequest, now: object, chat: object) -> object:
        return await original(body.model_copy(update={"source": "chat"}), now, chat)

    patch.setattr(harness, "run_agent", run_agent)


def unfinished_counts(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_policy, "is_unfinished", lambda _sentence: False)


def partial_names_count(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_policy, "CONFIDENCE_THRESHOLD", 0.0)


def no_daily_cap(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_perform, "auto_count", no_count)


def no_kill_switch(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_run, "kill_switch", no_stop)
    patch.setattr(agent_policy, "tool_mode", lambda _tool, _settings: "auto")


def no_call_limit(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_run, "MAX_TOOL_CALLS", 100)


def first_candidate_wins(patch: pytest.MonkeyPatch) -> None:
    original = agent_perform.judge

    def judge(tool: Tool, args: dict[str, object], verdict: object, masker: object, plan: Plan) -> object:
        chosen = original(tool, args, verdict, masker, plan)
        first = plan.resolution.candidates[:1]
        return replace(chosen, draft=replace(chosen.draft, target=first[0])) if first else chosen

    patch.setattr(agent_policy, "undecided", lambda _context: None)
    patch.setattr(agent_perform, "judge", judge)


def history_is_evidence(patch: pytest.MonkeyPatch) -> None:
    original = agent_run.prepare

    async def prepare(run_id: str, question: str, history: Sequence[HistoryTurn], now: object) -> object:
        prepared = await original(run_id, question, history, now)
        turn = " ".join([*(item.text for item in history), question])
        return replace(prepared, context=replace(prepared.context, turn=turn))

    patch.setattr(agent_run, "prepare", prepare)


async def sent(_db: AsyncSession, _target: TargetRef) -> Outcome:
    return Outcome(summary="보냈어요.")


def a_tool_to_send(patch: pytest.MonkeyPatch) -> None:
    async def plan(_db: AsyncSession, _args: Mapping[str, object], _env: ToolEnv) -> Plan:
        return Plan(args={}, resolution=Resolution(()), claims=(), checks=(), preview=(), execute=sent)

    tool = Tool(
        rule=ToolRule("send_message", "T0", "none"), title="문자", description="문자를 보냅니다.",
        parameters={}, plan=plan,
    )
    tools = MappingProxyType({**agent_tools.TOOLS, "send_message": tool})
    for module in (agent_run, agent_perform, agent_tools):
        patch.setattr(module, "TOOLS", tools)


MUTATIONS: Final[tuple[Mutation, ...]] = (
    Mutation("evidence_source", "RT-A01", evidence_anywhere),
    Mutation("statement_form_question", "RT-B02", questions_count),
    Mutation("statement_form_negation", "RT-B17", negations_count),
    Mutation("statement_form_unfinished", "RT-B18", unfinished_counts),
    Mutation("confidence", "RT-P01", partial_names_count),
    Mutation("daily_cap", "RT-M07", no_daily_cap),
    Mutation("kill_switch", "RT-H04", no_kill_switch),
    Mutation("call_limit", "RT-K06", no_call_limit),
    Mutation("target_unique", "RT-C01", first_candidate_wins),
    Mutation("history_not_evidence", "RT-J03", history_is_evidence),
    Mutation("t3_never_offered", "RT-G01", a_tool_to_send),
    Mutation("voice_never_t2_auto", "RT-V00", voice_is_chat),
)

type RunAuto = Callable[..., Awaitable[object]]


def racing(original: RunAuto, engine: AsyncEngine, table: str, row_id: str) -> RunAuto:
    async def run_auto(db: AsyncSession, context: object, judged: object) -> object:
        async with engine.begin() as connection:
            await apply(connection, BumpOp(op="bump", table=table, id=row_id))
        return await original(db, context, judged)

    return run_auto


async def unchecked_lock(db: AsyncSession, model: type, row_id: str, _expected: int | None) -> object:
    return await db.scalar(select(model).where(model.id == row_id).with_for_update())


def ignored_revision(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(agent_tools_orders, "lock_row", unchecked_lock)
