"""The assistant's worker process: it raises what the rules found and runs the owner's queued questions.

It opens no port and never calls a model by itself. Every pass reads the settings again, so mode off,
quiet hours, or a missing settings row take effect at once, and the kill switch is read before every
proposal. The model is reached only through the core's queue, for questions the owner asked. Whatever
the settings say, a tick drops undo text that is too old and closes runs a dead process left running.
"""

import argparse
import json
import logging
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Final, Literal

import anyio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_findings import Finding
from agent_hcx import hcx_tool_chat
from agent_perform import purge_old_undo
from agent_proactive import detect
from agent_run import (
    AgentBusyError,
    agent_session,
    claim_run,
    finish_run,
    raise_proposal,
    run_claimed,
)
from agent_settings import DEFAULT_SETTINGS, AgentSettings, load_settings, stop_requested
from agent_store import RunEnd, finish, owner_lock
from agent_tables import AgentProposalRow, AgentRunRow, AgentStepRow
from common import current_time
from database import DatabaseConfigurationError, get_engine, transaction
from display import day_start, local, next_day_start
from observability import configure_logging

LOGGER: Final = logging.getLogger("roundup.agent")
TICK_LOCK: Final = (0x61677074, 1)
QUESTION: Final = "오늘 챙길 일 살펴보기"
POLL: Final = timedelta(seconds=5)
PER_TICK: Final = 10
"""Raised in one tick, so the owner's own question never waits long for the shared run lock."""
ABANDONED_AFTER: Final = timedelta(minutes=10)
ABANDONED_NOTE: Final = "처리하다가 멈췄어요. 어디까지 했는지 앱에서 확인해 주세요."
BUSY_RETRY: Final = timedelta(minutes=1)
BACKOFF_BASE: Final = timedelta(seconds=30)
BACKOFF_CAP: Final = timedelta(minutes=30)
BACKOFF_DOUBLINGS: Final = 6
type TickStatus = Literal[
    "raised", "idle", "locked", "missing", "off", "paused", "quiet", "capped", "busy", "stopped",
]


@dataclass(frozen=True, slots=True)
class TickResult:
    """What one tick did and how long to wait before the next."""

    status: TickStatus
    raised: int = 0
    interval: timedelta = DEFAULT_SETTINGS.interval


def gate(settings: AgentSettings, now: datetime) -> TickStatus | None:
    """Name the setting that keeps this tick from raising anything, or None when it may go on."""
    if settings.mode == "off":
        return "off"
    if not settings.proactive:
        return "paused"
    return "quiet" if settings.is_quiet(now) else None


async def raised_today(db: AsyncSession, today: date) -> int:
    """Count what proactive runs put in front of the owner on one Seoul day."""
    return await db.scalar(
        select(func.count()).select_from(AgentProposalRow)
        .join(AgentStepRow, AgentStepRow.id == AgentProposalRow.step_id)
        .join(AgentRunRow, AgentRunRow.id == AgentStepRow.run_id)
        .where(
            AgentRunRow.source == "proactive",
            AgentProposalRow.created_at >= day_start(today),
            AgentProposalRow.created_at < next_day_start(today),
        ),
    ) or 0


async def fresh_findings(db: AsyncSession, settings: AgentSettings, now: datetime) -> list[Finding]:
    """Run the rules and keep what is neither switched off, raised today, nor still open."""
    found = [finding for finding in await detect(db, now) if settings.tool_mode(finding.tool) != "off"]
    keys = [finding.dedupe_key for finding in found]
    seen = set(await db.scalars(
        select(AgentProposalRow.dedupe_key).where(AgentProposalRow.dedupe_key.in_(keys)),
    ))
    open_targets = set(
        (await db.execute(
            select(AgentProposalRow.tool, AgentProposalRow.target_kind, AgentProposalRow.target_id)
            .where(AgentProposalRow.state == "open", AgentProposalRow.expires_at > now),
        )).tuples().all(),
    )
    return [
        finding for finding in found
        if finding.dedupe_key not in seen
        and (finding.tool, finding.target.kind, finding.target.id) not in open_targets
    ]


async def raise_findings(db: AsyncSession, findings: Sequence[Finding], now: datetime) -> TickResult:
    """Turn findings into proposals one by one; the kill switch is read before each."""
    raised = 0
    try:
        async with agent_session("proactive", QUESTION, now) as session:
            for finding in findings:
                if await stop_requested(db):
                    return TickResult("stopped", raised)
                if await raise_proposal(session, finding.draft()) is not None:
                    raised += 1
    except AgentBusyError:
        return TickResult("busy", raised)
    return TickResult("raised", raised) if raised else TickResult("idle")


async def close_abandoned(now: datetime) -> None:
    """Close runs a dead process left running; a held owner lock means one may still be at work."""
    try:
        async with owner_lock(), transaction() as db:
            abandoned = await db.scalars(
                select(AgentRunRow.id)
                .where(AgentRunRow.status == "running", AgentRunRow.started_at < now - ABANDONED_AFTER)
                .with_for_update(skip_locked=True),
            )
            for run_id in abandoned.all():
                await finish(db, run_id, RunEnd("failed", ABANDONED_NOTE, "abandoned"), now)
    except AgentBusyError:
        return


async def run_tick(now: datetime) -> TickResult:
    """Check every rule once and raise fresh findings as proposals; nothing here calls a model."""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory.begin() as db:
        _ = await db.execute(text("SET LOCAL statement_timeout = '15s'"))
        if not await db.scalar(select(func.pg_try_advisory_xact_lock(*TICK_LOCK))):
            return TickResult("locked")
        await purge_old_undo(now)
        await close_abandoned(now)
        settings = await load_settings(db)
        if settings is None:
            return TickResult("missing")
        waiting = gate(settings, now)
        if waiting is not None:
            return TickResult(waiting, interval=settings.interval)
        budget = settings.daily_cap - await raised_today(db, local(now).date())
        if budget <= 0:
            return TickResult("capped", interval=settings.interval)
        fresh = await fresh_findings(db, settings, now)
        limit = min(budget, PER_TICK)
        result = await raise_findings(db, fresh[:limit], now) if fresh else TickResult("idle")
        return replace(result, interval=settings.interval)


def backoff(failures: int) -> timedelta:
    """Wait longer after each failure in a row, up to half an hour."""
    return min(BACKOFF_BASE * (1 << min(failures - 1, BACKOFF_DOUBLINGS)), BACKOFF_CAP)


async def killed() -> bool:
    """Read the kill switch in a short session of its own."""
    async with AsyncSession(get_engine()) as db:
        return await stop_requested(db)


async def run_one(now: datetime) -> bool:
    """Run one queued question; False when none waits or the owner is busy with another run."""
    run = await claim_run(now)
    if run is None:
        return False
    try:
        status = await run_claimed(run, now, hcx_tool_chat)
    except Exception as error:  # noqa: BLE001 - a failed run must not stop the worker; the type is logged.
        LOGGER.error("agent_run_failed", extra={"error_type": type(error).__name__})  # noqa: TRY400
        await finish_run(run.id, "failed", current_time(), error=type(error).__name__)
        return True
    return status != "queued"


async def run_queue(stop: anyio.Event) -> None:
    """Run the owner's queued questions until none is left or the kill switch is on."""
    while not stop.is_set() and not await killed() and await run_one(current_time()):
        pass


async def pass_once(stop: anyio.Event, next_tick: float) -> float:
    """Answer the queue, then tick when due; returns the loop time of the next tick."""
    await run_queue(stop)
    if anyio.current_time() < next_tick or stop.is_set():
        return next_tick
    result = await run_tick(current_time())
    LOGGER.info("agent_tick", extra={"status": result.status, "source": "proactive"})
    wait = min(result.interval, BUSY_RETRY) if result.status == "busy" else result.interval
    return anyio.current_time() + wait.total_seconds()


async def serve(stop: anyio.Event) -> None:
    """Poll until told to stop; an error waits longer each time and never ends the process."""
    failures = 0
    next_tick = anyio.current_time()
    while not stop.is_set():
        try:
            next_tick = await pass_once(stop, next_tick)
            failures, pause = 0, POLL
        except Exception as error:  # noqa: BLE001 - the worker outlives a failing pass; the type is logged.
            failures += 1
            pause = backoff(failures)
            LOGGER.error("agent_worker_error", extra={"error_type": type(error).__name__})  # noqa: TRY400
        with anyio.move_on_after(pause.total_seconds()):
            await stop.wait()


async def watch_signals(stop: anyio.Event) -> None:
    """Ask the loop to stop on SIGTERM or SIGINT; a run in progress finishes first."""
    with anyio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signals:
        async for _ in signals:
            stop.set()
            return


async def run_forever() -> None:
    """Serve until a stop signal."""
    stop = anyio.Event()
    async with anyio.create_task_group() as group:
        _ = group.start_soon(watch_signals, stop)
        await serve(stop)
        group.cancel_scope.cancel()


async def run_once() -> TickResult:
    """Run one tick by hand."""
    return await run_tick(current_time())


class Arguments(argparse.Namespace):
    """Parsed options."""

    once: bool = False


async def work(*, once: bool) -> None:
    """Run once or forever, then release the pool; a bad configuration ends it before anything starts."""
    engine = get_engine()
    try:
        if once:
            result = await run_once()
            summary = {"status": result.status, "raised": result.raised}
            _ = sys.stdout.write(json.dumps(summary) + "\n")
        else:
            await run_forever()
    finally:
        await engine.dispose()
        get_engine.cache_clear()


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(prog="python agent_worker.py")
    _ = parser.add_argument("--once", action="store_true", help="run one tick by hand and print its result")
    once = parser.parse_args(namespace=Arguments()).once
    configure_logging()
    try:
        anyio.run(lambda: work(once=once))
    except DatabaseConfigurationError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
