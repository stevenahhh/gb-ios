"""Run evaluation cases through the real loop, with a throwaway schema and recorded handlers."""

import json
import sys
import time
from collections.abc import AsyncGenerator, Callable, Generator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from os import environ
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import Connection, Table, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

import agent_hcx
import agent_perform
import agent_run
import agent_tools
import providers
from agent_hcx import ChatTurn, ToolChat, hcx_tool_chat
from agent_types import Outcome, Plan, RunRequest, RunResponse, TargetRef, Tool, ToolCall, ToolEnv
from database import Base, get_engine
from display import SEOUL
from scripts.agent_eval_meter import CapReachedError, Meter, Send, canned_send, metered_send
from scripts.agent_eval_score import Actual, CaseResult, EvalCase, Observed, Setup, score
from seed import apply_seed

type Backend = Literal["scripted", "live"]

JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)

FIXED_NOW: Final = datetime(2026, 11, 18, 11, 0, tzinfo=SEOUL)
SERVER: Final = Path(__file__).resolve().parent.parent
AGENT_TABLES: Final = ("agent_proposals", "agent_steps", "agent_runs", "agent_memories")
RESET_SETTINGS: Final = (
    "UPDATE agent_settings SET mode = 'auto', per_tool = '{}'::jsonb, daily_cap = 20, "
    "quiet_start = '22:00', quiet_end = '08:00' WHERE id = 1"
)


@dataclass(frozen=True, slots=True)
class Options:
    """What one evaluation run covers."""

    backend: Backend
    cases: tuple[EvalCase, ...]
    max_calls: int
    max_tokens: int


@dataclass(frozen=True, slots=True)
class Executed:
    """A handler call the recorder intercepted: the tool, its validated arguments, and its target."""

    tool: str
    args: Mapping[str, JsonValue]
    target: str | None


def schema_table(name: str) -> Table:
    """Look up a mapped table."""
    return Base.metadata.tables[name]


def row_values(values: Mapping[str, JsonValue]) -> dict[str, object]:
    """Turn {"$dt": iso} values into moments and leave the rest."""
    return {
        column: datetime.fromisoformat(str(value["$dt"])) if isinstance(value, dict) else value
        for column, value in values.items()
    }


async def set_row(
    connection: AsyncConnection, table: str, row_id: str | int, values: Mapping[str, JsonValue],
) -> None:
    """Change columns of one row."""
    target = schema_table(table)
    _ = await connection.execute(update(target).where(target.c.id == row_id).values(**row_values(values)))


async def read_row(
    connection: AsyncConnection, table: str, row_id: str | int, columns: Sequence[str],
) -> dict[str, JsonValue]:
    """Read columns of one row, with moments as {"$dt": iso}."""
    target = schema_table(table)
    picked = [target.c[column] for column in columns]
    cells = (await connection.execute(select(*picked).where(target.c.id == row_id))).one()
    return keyed(columns, cells)


def keyed(columns: Sequence[str], cells: Sequence[object]) -> dict[str, JsonValue]:
    """Name a row's cells, writing moments as {"$dt": iso}."""
    return {
        column: {"$dt": value.isoformat()} if isinstance(value, datetime) else JSON.validate_python(value)
        for column, value in zip(columns, cells, strict=True)
    }


async def reset_agent(engine: AsyncEngine) -> None:
    """Empty the agent's own tables and restore the owner's default switches."""
    async with engine.begin() as connection:
        _ = await connection.execute(text(f"TRUNCATE {', '.join(AGENT_TABLES)} RESTART IDENTITY CASCADE"))
        _ = await connection.execute(text(RESET_SETTINGS))


async def apply_setup(engine: AsyncEngine, setups: Sequence[Setup]) -> list[Setup]:
    """Apply one case's setup and return what undoes it."""
    undo: list[Setup] = []
    async with engine.begin() as connection:
        for item in setups:
            before = await read_row(connection, item.table, item.id, list(item.values))
            undo.append(Setup(table=item.table, id=item.id, values=before))
            await set_row(connection, item.table, item.id, item.values)
    return undo


async def undo_setup(engine: AsyncEngine, undo: Sequence[Setup]) -> None:
    """Put back the rows a setup changed."""
    async with engine.begin() as connection:
        for item in reversed(undo):
            await set_row(connection, item.table, item.id, item.values)


async def migrate(connection: AsyncConnection) -> None:
    """Apply every migration to the schema the connection selects."""
    config = Config(str(SERVER / "alembic.ini"))

    def upgrade(sync: Connection) -> None:
        config.attributes["connection"] = sync
        command.upgrade(config, "head")

    await connection.run_sync(upgrade)


@asynccontextmanager
async def scratch_schema() -> AsyncGenerator[AsyncEngine]:
    """Create a seeded throwaway schema, point the engine at it, and drop it at the end."""
    name = f"roundup_eval_{uuid4().hex}"
    _ = environ.pop("DATABASE_SCHEMA", None)
    get_engine.cache_clear()
    admin = get_engine()
    async with admin.begin() as connection:
        _ = await connection.execute(text(f'CREATE SCHEMA "{name}"'))
    await admin.dispose()
    get_engine.cache_clear()
    environ["DATABASE_SCHEMA"] = name
    engine = get_engine()
    try:
        async with engine.connect() as connection:
            await migrate(connection)
        async with engine.begin() as connection:
            _ = await apply_seed(connection, FIXED_NOW.date())
        _ = sys.stderr.write(f"seeded scratch schema {name}\n")
        yield engine
    finally:
        async with engine.begin() as connection:
            _ = await connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        await engine.dispose()
        get_engine.cache_clear()
        _ = environ.pop("DATABASE_SCHEMA", None)


def recorded(tool: Tool, log: list[Executed]) -> Tool:
    """Return the tool with its execution replaced by a log entry; planning and reads stay real."""
    if tool.rule.tier == "T0":
        return tool

    async def plan(db: AsyncSession, args: Mapping[str, JsonValue], env: ToolEnv) -> Plan:
        made = await tool.plan(db, args, env)

        async def execute(_: AsyncSession, target: TargetRef) -> Outcome:
            log.append(Executed(tool.rule.name, dict(made.args), target.id))
            return Outcome(summary="(시험 실행) 기록만 했어요.")

        return replace(made, execute=execute)

    return replace(tool, plan=plan, undo=None)


@contextmanager
def dry_run(log: list[Executed], offered: set[str]) -> Generator[None]:
    """Make every write handler record instead of act, and note the tools the model was offered."""
    tools = MappingProxyType({name: recorded(tool, log) for name, tool in agent_tools.registry().items()})

    def definitions(known: Mapping[str, Tool]) -> list[dict[str, JsonValue]]:
        offered.update(known)
        return agent_tools.tool_definitions(known)

    with (
        patch.object(agent_run, "TOOLS", tools), patch.object(agent_perform, "TOOLS", tools),
        patch.object(agent_tools, "TOOLS", tools), patch.object(agent_run, "tool_definitions", definitions),
    ):
        yield


class ScriptedChat:
    """The scripted backend's model: it makes the calls a case expects, then answers in one line."""

    def __init__(self, case: EvalCase, meter: Meter, prompts: list[int]) -> None:
        """Queue the expected calls of one case."""
        self.meter: Meter = meter
        self.prompts: list[int] = prompts
        self.calls: list[ToolCall] = [
            ToolCall(f"call-{index}", call.tool, dict(call.args))
            for index, call in enumerate(case.expect.calls)
        ]

    async def __call__(
        self, messages: Sequence[agent_hcx.Turn], tools: Sequence[agent_hcx.ToolDefinition],
        **_limits: object,
    ) -> ChatTurn:
        """Return the expected calls once, then a closing line; note the prompt size."""
        self.meter.admit()
        size = len(str([message.wire() for message in messages])) + len(json.dumps(list(tools)))
        self.prompts.append(size)
        self.meter.add(0)
        calls, self.calls = tuple(self.calls), []
        return ChatTurn("" if calls else "확인했어요.", calls, 0)


def actuals_of(response: RunResponse, log: Sequence[Executed]) -> tuple[Actual, ...]:
    """Pair each recorded step with the arguments its handler saw, in order."""
    remaining = list(log)
    found: list[Actual] = []
    for step in response.steps:
        tool = agent_tools.registry().get(step.tool)
        if tool is not None and tool.rule.tier == "T0":
            continue
        ran = None
        if step.decision == "auto":
            ran = next((item for item in remaining if item.tool == step.tool), None)
        if ran is not None:
            remaining.remove(ran)
        target = step.target.id if step.target else None
        found.append(Actual(step.tool, step.decision, target, ran.args if ran else {}))
    return tuple(found)


async def run_case(case: EvalCase, engine: AsyncEngine, chat: ToolChat, meter: Meter) -> CaseResult:
    """Run one request in dry-run mode and score what happened."""
    log: list[Executed] = []
    offered: set[str] = set()
    answer = ""
    started, calls, tokens = time.monotonic(), meter.calls, meter.tokens
    error: str | None = None
    actuals: tuple[Actual, ...] = ()
    await reset_agent(engine)
    undo = await apply_setup(engine, case.setup)
    try:
        with dry_run(log, offered):
            response = await agent_run.run_agent(
                RunRequest(question=case.turn, history=case.history, source=case.source), FIXED_NOW, chat,
            )
        actuals, answer = actuals_of(response, log), response.answer or ""
    except HTTPException as failure:
        error = f"HTTPException {failure.status_code}"
    finally:
        await undo_setup(engine, undo)
    if meter.capped:
        raise CapReachedError
    scored = score(case, actuals, Observed(answer, frozenset(offered)))
    return CaseResult(
        id=case.id, kind=case.kind, turn=case.turn, expected=tuple(case.expect.calls),
        passed=scored.passed and error is None, unsafe=scored.unsafe, noisy=scored.noisy,
        problems=scored.problems, actual=actuals, offered=tuple(sorted(offered)), answer=answer,
        model_calls=meter.calls - calls,
        tokens=meter.tokens - tokens, seconds=round(time.monotonic() - started, 2), error=error,
    )


async def evaluate(options: Options, results: list[CaseResult], meter: Meter, prompts: list[int]) -> None:
    """Run the cases in one scratch schema, stopping at the cap; results grow as cases finish."""
    wrap: dict[Backend, Callable[[Send, Meter], Send]] = {"live": metered_send, "scripted": canned_send}
    replacement = wrap[options.backend](providers.send, meter)
    async with scratch_schema() as engine:
        with patch.object(providers, "send", replacement), patch.object(agent_hcx, "send", replacement):
            for case in options.cases:
                if meter.capped:
                    break
                chat = ScriptedChat(case, meter, prompts) if options.backend == "scripted" else hcx_tool_chat
                try:
                    results.append(await run_case(case, engine, chat, meter))
                except CapReachedError:
                    break
