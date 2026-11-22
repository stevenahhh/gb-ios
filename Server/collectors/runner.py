"""Run one source or all of them; a failing source never stops or changes another."""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

import anyio

from collectors.base import CollectedItem, NeedsConnectionError, SourceId, Window
from collectors.http import Gateway, SourceError
from collectors.mapping import connect_channel, disconnect_channel, map_items
from collectors.registry import build
from collectors.store import is_running, locked_source, open_run, save_item
from database import transaction
from models import CollectorRunRow

LOGGER: Final = logging.getLogger("roundup.collectors")
FIRST_WINDOW: Final = timedelta(days=7)
OVERLAP: Final = timedelta(hours=1)
DEADLINE: Final = 120.0
type SourceState = Literal["collecting", "idle", "needs_connection", "error"]
type Clock = Callable[[], datetime]
type Collect = Callable[[], Awaitable[list[CollectedItem]]]


class AlreadyRunningError(Exception):
    """Another process is collecting this source."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one run did; the error is a short code."""

    source: SourceId
    state: SourceState
    message: str | None = None
    collected: int = 0
    inserted: int = 0
    mapped: int = 0
    error: str | None = None


def failure_message(name: str) -> str:
    """Tell the owner a run failed without upstream detail."""
    return f"{name} 자료를 가져오지 못했어요. 다음 수집 때 다시 시도해요."


async def store_items(
    source: SourceId, items: Sequence[CollectedItem], clock: Clock,
) -> Outcome:
    """Keep the items first, then map them, so a mapping failure loses nothing."""
    async with transaction() as db:
        saved = [await save_item(db, source, item, clock()) for item in items]
    async with transaction() as db:
        mapped = await map_items(db, source, clock())
        if items:
            await connect_channel(db, source)
    return Outcome(source, "idle", collected=len(items), inserted=sum(saved), mapped=mapped)


async def attempt(source: SourceId, name: str, collect: Collect, clock: Clock) -> Outcome:
    """Collect and store, turning every failure into an outcome."""
    try:
        with anyio.fail_after(DEADLINE):
            items = await collect()
        return await store_items(source, items, clock)
    except NeedsConnectionError as error:
        return Outcome(source, "needs_connection", error.message, error="needs_connection")
    except SourceError as error:
        return Outcome(source, "error", failure_message(name), error=error.code)
    except TimeoutError:
        return Outcome(source, "error", failure_message(name), error="timeout")
    except Exception as error:  # noqa: BLE001 - isolate one source; keep only the type.
        code = f"internal:{type(error).__name__}"
        return Outcome(source, "error", failure_message(name), error=code)


async def finish(run_id: str, outcome: Outcome, now: datetime) -> None:
    """Record the result on the run and its source."""
    async with transaction() as db:
        row = await locked_source(db, outcome.source)
        row.state, row.message = outcome.state, outcome.message
        if outcome.error is None:
            row.last_collected_at = now
        if outcome.state == "needs_connection":
            await disconnect_channel(db, outcome.source)
        run = await db.get_one(CollectorRunRow, run_id)
        run.status = "succeeded" if outcome.error is None else "failed"
        run.finished_at, run.error = now, outcome.error
        run.collected, run.inserted, run.mapped = outcome.collected, outcome.inserted, outcome.mapped


async def run_source(source: SourceId, gateway: Gateway, clock: Clock) -> Outcome:
    """Run one source; a source that is not set up makes no request."""
    started = clock()
    async with transaction() as db:
        row = await locked_source(db, source)
        if is_running(row, started):
            raise AlreadyRunningError
        collector = build(source, gateway, row.config)
        problem = collector.connection_problem()
        if problem is not None:
            return Outcome(source, "needs_connection", problem, error="needs_connection")
        earliest = started - FIRST_WINDOW
        since = max(row.last_collected_at - OVERLAP, earliest) if row.last_collected_at else earliest
        run_id = await open_run(db, row, started)
    window = Window(since=since, now=started)
    outcome = await attempt(source, collector.display_name, lambda: collector.collect(window), clock)
    await finish(run_id, outcome, clock())
    LOGGER.info("collector_run", extra={
        "source": source, "error_type": outcome.error, "collected": outcome.collected,
        "inserted": outcome.inserted, "mapped": outcome.mapped,
    })
    return outcome


async def run_all(sources: Sequence[SourceId], gateway: Gateway, clock: Clock) -> list[Outcome]:
    """Run sources one after another; each failure stays with its own source."""
    outcomes: list[Outcome] = []
    for source in sources:
        try:
            outcomes.append(await run_source(source, gateway, clock))
        except AlreadyRunningError:
            outcomes.append(Outcome(source, "collecting", error="already_running"))
        except Exception as error:  # noqa: BLE001 - storage failed for this source; report it and go on.
            outcomes.append(Outcome(source, "error", error=f"internal:{type(error).__name__}"))
    return outcomes
