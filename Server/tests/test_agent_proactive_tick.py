"""One proactive tick: what it raises, what it never does, and what stops it."""

import json
import os
import signal
import socket
import sys
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Final

import anyio
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

import agent_worker
from agent_run import agent_session
from agent_store import UNDO_KEPT_FOR
from agent_tables import AgentRunRow, AgentStepRow
from agent_worker import PER_TICK, TICK_LOCK, TickResult, backoff, run_tick, serve
from tests.agent_proactive_support import (
    HOUR,
    MINUTE,
    NOW,
    customer,
    inquiry,
    order,
    seoul,
    set_settings,
    store,
)

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
SERVER: Final = Path(__file__).resolve().parent.parent
QUARTER: Final = timedelta(minutes=15)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = socket.socket.connect

    def local_only(self: socket.socket, address: tuple[str, int] | str) -> None:
        host = address[0] if isinstance(address, tuple) else ""
        if host not in {"127.0.0.1", "::1", ""}:
            message = f"network use: {host}"
            raise AssertionError(message)
        connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)


@pytest.fixture
async def switched_on(migrated: AsyncEngine) -> AsyncEngine:
    await set_settings(mode="auto")
    return migrated


async def keys(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT dedupe_key FROM agent_proposals ORDER BY dedupe_key"))
        return [str(row[0]) for row in rows]


async def paid_orders(engine: AsyncEngine, count: int, at: datetime = NOW) -> None:
    await store(engine, customer(), *(
        order(f"o{number}", 1000 + number, ordered_at=at - 4 * HOUR) for number in range(count)
    ))


async def undoable_steps(engine: AsyncEngine) -> None:
    """Store one step just past the time undo text is kept and one just inside it."""
    for key, age in (("old", UNDO_KEPT_FOR + MINUTE), ("recent", UNDO_KEPT_FOR - MINUTE)):
        run = AgentRunRow(id=f"run-{key}", source="chat", question="", status="done", created_at=NOW - age)
        step = AgentStepRow(
            id=f"step-{key}", run_id=run.id, seq=1, tool="save_reply_draft", tier="T1",
            title="답장 초안 저장", args={}, decision="auto", reason="", undo_path="/inquiries/a/draft",
            undo_data={"draft": "이전 초안"}, undo_until=NOW - age + UNDO_KEPT_FOR, created_at=NOW - age,
        )
        await store(engine, run, step)


async def steps_with_undo_text(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text(
            "SELECT id FROM agent_steps WHERE undo_data ->> 'draft' IS NOT NULL ORDER BY id",
        ))
        return [str(row[0]) for row in rows]


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"mode": "off"}, "off"), ({"proactive": False}, "paused"),
        ({"quietHours": {"start": "10:00", "end": "12:00"}}, "quiet"), ({}, "idle"),
    ],
)
async def test_every_tick_drops_old_undo_text_once_whatever_the_settings_say(
    switched_on: AsyncEngine, monkeypatch: pytest.MonkeyPatch, fields: dict[str, object], status: str,
) -> None:
    await undoable_steps(switched_on)
    await set_settings(**fields)
    purge, moments = agent_worker.purge_old_undo, list[datetime]()

    async def counted(now: datetime) -> None:
        moments.append(now)
        _ = await purge(now)

    monkeypatch.setattr(agent_worker, "purge_old_undo", counted)

    result = await run_tick(NOW)

    assert (result.status, moments) == (status, [NOW])
    assert await steps_with_undo_text(switched_on) == ["step-recent"]


async def test_old_undo_text_is_dropped_without_a_settings_row(migrated: AsyncEngine) -> None:
    await undoable_steps(migrated)
    async with migrated.begin() as connection:
        _ = await connection.execute(text("DELETE FROM agent_settings"))

    result = await run_tick(NOW)

    assert (result.status, await steps_with_undo_text(migrated)) == ("missing", ["step-recent"])


async def test_old_undo_text_is_dropped_even_when_the_rest_of_the_tick_fails(
    switched_on: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await undoable_steps(switched_on)

    async def broken(_db: object, _now: datetime) -> None:
        raise OSError

    monkeypatch.setattr(agent_worker, "detect", broken)
    with pytest.raises(OSError):  # noqa: PT011 - any failure after the purge will do.
        _ = await run_tick(NOW)

    assert await steps_with_undo_text(switched_on) == ["step-recent"]


async def test_a_fresh_deployment_raises_nothing_until_the_owner_switches_it_on(
    migrated: AsyncEngine,
) -> None:
    await paid_orders(migrated, 1)

    before, untouched = await run_tick(NOW), await keys(migrated)
    await set_settings(mode="ask")
    after = await run_tick(NOW)

    assert (before.status, untouched, after.status) == ("off", [], "raised")


async def test_an_empty_workshop_keeps_the_tick_idle(switched_on: AsyncEngine) -> None:
    result = await run_tick(NOW)

    assert (result.status, result.raised, await keys(switched_on)) == ("idle", 0, [])


async def test_each_finding_is_raised_once_on_a_seoul_day(switched_on: AsyncEngine) -> None:
    await paid_orders(switched_on, 2)

    first, again = await run_tick(NOW), await run_tick(NOW + QUARTER)

    assert (first.status, first.raised, again.status, again.raised) == ("raised", 2, "idle", 0)
    assert await keys(switched_on) == [
        "confirm_order:order:order-o0:2026-11-22", "confirm_order:order:order-o1:2026-11-22",
    ]


async def test_a_tick_raises_a_bounded_batch_and_the_next_one_continues(switched_on: AsyncEngine) -> None:
    await paid_orders(switched_on, PER_TICK + 2)

    first, second = await run_tick(NOW), await run_tick(NOW + QUARTER)

    assert (first.raised, second.raised) == (PER_TICK, 2)


async def test_a_raised_proposal_carries_the_target_and_the_revision_it_was_found_with(
    switched_on: AsyncEngine,
) -> None:
    await paid_orders(switched_on, 1)

    _ = await run_tick(NOW)

    async with switched_on.connect() as connection:
        row = (await connection.execute(text(
            "SELECT p.tool, p.target_kind, p.target_id, p.expected_revision, p.state, r.source"
            " FROM agent_proposals p JOIN agent_steps s ON s.id = p.step_id"
            " JOIN agent_runs r ON r.id = s.run_id",
        ))).one()
    assert tuple(row) == ("confirm_order", "order", "order-o0", 0, "open", "proactive")


async def test_an_expired_proposal_is_raised_again_the_next_day(switched_on: AsyncEngine) -> None:
    await paid_orders(switched_on, 1)

    _ = await run_tick(NOW)
    again = await run_tick(NOW + timedelta(hours=25))

    assert again.raised == 1
    assert await keys(switched_on) == [
        "confirm_order:order:order-o0:2026-11-22", "confirm_order:order:order-o0:2026-11-23",
    ]


async def test_the_daily_cap_is_shared_by_every_kind_and_resets_at_seoul_midnight(
    switched_on: AsyncEngine,
) -> None:
    await set_settings(dailyCap=2, quietHours=None)
    await paid_orders(switched_on, 4)
    await store(switched_on, inquiry("late", received_at=NOW - 3 * HOUR))
    midnight = datetime.combine(NOW.date() + timedelta(days=1), time(0, 30), NOW.tzinfo)

    results = [await run_tick(NOW), await run_tick(NOW + QUARTER), await run_tick(midnight)]

    assert [(result.status, result.raised) for result in results] == [
        ("raised", 2), ("capped", 0), ("raised", 2),
    ]
    assert await keys(switched_on) == [
        "confirm_order:order:order-o0:2026-11-22", "confirm_order:order:order-o1:2026-11-22",
        "confirm_order:order:order-o2:2026-11-23", "confirm_order:order:order-o3:2026-11-23",
    ]


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"mode": "off"}, "off"), ({"proactive": False}, "paused"),
        ({"perTool": {"confirm_order": "off"}}, "idle"),
    ],
)
async def test_a_switch_the_owner_turned_off_keeps_the_tick_from_raising(
    switched_on: AsyncEngine, fields: dict[str, object], status: str,
) -> None:
    await paid_orders(switched_on, 1)
    await set_settings(**fields)

    result = await run_tick(NOW)

    assert (result.status, await keys(switched_on)) == (status, [])


async def test_a_missing_settings_row_keeps_the_tick_idle(migrated: AsyncEngine) -> None:
    await paid_orders(migrated, 1)
    async with migrated.begin() as connection:
        _ = await connection.execute(text("DELETE FROM agent_settings"))

    result = await run_tick(NOW)

    assert (result.status, await keys(migrated)) == ("missing", [])


@pytest.mark.parametrize("moment", [seoul(22), seoul(7, 59)])
async def test_quiet_hours_stop_the_tick_until_they_end(switched_on: AsyncEngine, moment: datetime) -> None:
    await paid_orders(switched_on, 1, at=NOW - timedelta(hours=24))

    quiet = await run_tick(moment)
    after = await run_tick(seoul(8))

    assert (quiet.status, after.status) == ("quiet", "raised")


async def test_a_suggested_draft_is_raised_for_approval_and_never_written_by_the_worker(
    switched_on: AsyncEngine,
) -> None:
    await store(switched_on, customer(), inquiry("a", received_at=NOW - 3 * HOUR))

    result = await run_tick(NOW)

    async with switched_on.connect() as connection:
        drafts = (await connection.execute(text("SELECT draft FROM inquiries"))).scalars().all()
        grounded = await connection.scalar(text("SELECT count(*) FROM inquiry_grounding"))
        steps = await connection.execute(text("SELECT DISTINCT decision FROM agent_steps"))
        decisions = steps.scalars().all()
    assert (result.raised, list(drafts), grounded, list(decisions)) == (1, [""], 0, ["proposed"])


async def test_a_tick_already_running_elsewhere_is_left_to_finish(switched_on: AsyncEngine) -> None:
    await paid_orders(switched_on, 1)

    async with async_sessionmaker(switched_on)() as holder, holder.begin():
        _ = await holder.execute(select(func.pg_advisory_xact_lock(*TICK_LOCK)))
        locked = await run_tick(NOW)
    released = await run_tick(NOW)

    assert (locked.status, released.status) == ("locked", "raised")


async def test_a_tick_waits_while_the_owner_is_talking_to_the_assistant(switched_on: AsyncEngine) -> None:
    await paid_orders(switched_on, 1)

    async with agent_session("chat", "주문 있어?", NOW):
        busy = await run_tick(NOW)
    after = await run_tick(NOW)

    assert (busy.status, busy.raised, after.status) == ("busy", 0, "raised")


async def test_the_kill_switch_stops_a_tick_before_its_next_proposal(
    switched_on: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await paid_orders(switched_on, 3)
    propose = agent_worker.raise_proposal

    async def propose_then_switch_off(*args: object, **kwargs: object) -> object:
        view = await propose(*args, **kwargs)
        await set_settings(mode="off")
        return view

    monkeypatch.setattr(agent_worker, "raise_proposal", propose_then_switch_off)

    result = await run_tick(NOW)

    assert (result.status, result.raised, len(await keys(switched_on))) == ("stopped", 1, 1)


def test_backoff_doubles_after_each_failure_and_stays_below_half_an_hour() -> None:
    delays = [backoff(failures) for failures in range(1, 8)]

    assert delays == [timedelta(seconds=seconds) for seconds in (30, 60, 120, 240, 480, 960, 1800)]
    assert backoff(10_000) == timedelta(minutes=30)


async def test_a_failing_pass_is_retried_and_never_ends_the_loop(
    migrated: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = anyio.Event()
    calls: list[int] = []

    async def broken_then_stopping(_stop: anyio.Event, _next: float) -> float:
        calls.append(len(calls))
        if len(calls) == 3:
            _stop.set()
            return 0.0
        message = "database is down"
        raise OSError(message)

    monkeypatch.setattr(agent_worker, "pass_once", broken_then_stopping)
    monkeypatch.setattr(agent_worker, "backoff", lambda _failures: timedelta(0))
    with anyio.fail_after(10):
        await serve(stop)

    assert calls == [0, 1, 2]


async def test_a_busy_tick_is_retried_within_a_minute(
    migrated: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def busy(_now: datetime) -> TickResult:
        return TickResult("busy", 0, timedelta(minutes=15))

    monkeypatch.setattr(agent_worker, "run_tick", busy)
    stop = anyio.Event()

    before = anyio.current_time()
    next_tick = await agent_worker.pass_once(stop, before)

    assert 0 < next_tick - before <= 61


@pytest.fixture
async def worker_process(migrated: AsyncEngine) -> AsyncIterator[anyio.abc.Process]:
    process = await anyio.open_process([sys.executable, str(SERVER / "agent_worker.py")], cwd=SERVER)
    try:
        yield process
    finally:
        if process.returncode is None:
            process.kill()
        _ = await process.aclose()


async def test_sigterm_ends_the_worker_cleanly_after_its_first_tick(
    worker_process: anyio.abc.Process,
) -> None:
    assert worker_process.stdout is not None
    output = b""
    with anyio.fail_after(30):
        async for chunk in worker_process.stdout:
            output += chunk
            if b"agent_tick" in output:
                break
        worker_process.send_signal(signal.SIGTERM)
        code = await worker_process.wait()

    assert code == 0


async def test_a_misconfigured_worker_exits_without_showing_the_credentials() -> None:
    environment = {**os.environ, "DATABASE_URL": "mysql://user:not-for-logs@host/database"}

    with anyio.fail_after(30):
        finished = await anyio.run_process(
            [sys.executable, str(SERVER / "agent_worker.py")], cwd=SERVER, env=environment, check=False,
        )

    assert finished.returncode == 1
    assert b"DATABASE_URL" in finished.stderr
    assert b"not-for-logs" not in finished.stderr + finished.stdout


async def test_once_prints_the_result_of_one_tick(switched_on: AsyncEngine) -> None:
    await set_settings(quietHours=None)
    await paid_orders(switched_on, 1)

    with anyio.fail_after(30):
        finished = await anyio.run_process(
            [sys.executable, str(SERVER / "agent_worker.py"), "--once"], cwd=SERVER,
        )

    assert json.loads(finished.stdout.decode().strip().splitlines()[-1])["status"] == "raised"
