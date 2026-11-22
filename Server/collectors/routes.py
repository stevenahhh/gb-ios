"""Collector status, items, manual runs, and owner-visible setup; these routes use snake_case keys."""

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from collectors.base import JsonObject, SourceId
from collectors.http import Gateway
from collectors.registry import COLLECTORS, STATUS_SOURCES, build
from collectors.runner import AlreadyRunningError, SourceState, failure_message, run_source
from collectors.store import is_running, locked_source
from common import Limit, Now, Offset, Session
from database import transaction
from display import day_start, local, next_day_start
from models import CollectedItemRow, CollectorSourceRow

router = APIRouter(prefix="/collectors")
ERROR_ONLY: Final = frozenset({"error", "needs_connection"})


class SourceStatus(BaseModel):
    """One source as the app shows it."""

    id: SourceId
    name: str
    state: SourceState
    last_collected_at: str | None
    collected_today: int
    message: str | None


class CollectorStatus(BaseModel):
    """Every source the app shows."""

    sources: list[SourceStatus]
    updated_at: str


class Item(BaseModel):
    """A stored item without its raw source JSON."""

    id: str
    source: str
    external_id: str
    kind: str
    title: str
    body: str
    author: str | None
    url: str | None
    published_at: str | None
    collected_at: str
    mapped: bool


class ItemPage(BaseModel):
    """One page of stored items, newest first."""

    items: list[Item]
    total: int
    limit: int
    offset: int
    has_more: bool


class RunResult(BaseModel):
    """The source after a run and what the run did."""

    source: SourceStatus
    collected: int
    inserted: int
    mapped: int
    error: str | None


class SavedConfig(BaseModel):
    """The setup values now stored."""

    source: SourceId
    config: JsonObject


def collector_gateway() -> Gateway:
    """Provide the network to collectors."""
    return Gateway()


Network = Annotated[Gateway, Depends(collector_gateway)]


def iso(moment: datetime | None) -> str | None:
    """Format a moment in workshop time."""
    return local(moment).isoformat(timespec="seconds") if moment else None


def status_of(
    source: SourceId, row: CollectorSourceRow | None, today: int, now: datetime,
) -> SourceStatus:
    """Combine live setup with the last recorded result."""
    collector = build(source, Gateway(), row.config if row else {})
    state: SourceState = "idle"
    message = collector.connection_problem()
    if message is not None:
        state = "needs_connection"
    elif row is not None:
        match row.state:
            case "collecting" if is_running(row, now):
                state = "collecting"
            case "collecting" | "error":
                state, message = "error", row.message or failure_message(collector.display_name)
            case "needs_connection":
                state, message = "needs_connection", row.message
            case _:
                pass
    return SourceStatus(
        id=source, name=collector.display_name, state=state,
        last_collected_at=iso(row.last_collected_at) if row else None,
        collected_today=today, message=message,
    )


async def statuses(db: Session, sources: tuple[SourceId, ...], now: datetime) -> list[SourceStatus]:
    """Load sources with the items first seen today."""
    rows = {row.id: row for row in await db.scalars(select(CollectorSourceRow))}
    counted = await db.execute(
        select(CollectedItemRow.source_id, func.count())
        .where(
            CollectedItemRow.collected_at >= day_start(now.date()),
            CollectedItemRow.collected_at < next_day_start(now.date()),
        )
        .group_by(CollectedItemRow.source_id),
    )
    today = dict(counted.tuples().all())
    return [status_of(source, rows.get(source), today.get(source, 0), now) for source in sources]


@router.get("/status")
async def status(db: Session, now: Now) -> CollectorStatus:
    """Report every source the app shows."""
    return CollectorStatus(
        sources=await statuses(db, STATUS_SOURCES, now), updated_at=now.isoformat(timespec="seconds"),
    )


@router.get("/items")
async def items(
    db: Session, source: SourceId | None = None, limit: Limit = 30, offset: Offset = 0,
) -> ItemPage:
    """List stored items, newest first."""
    conditions = [CollectedItemRow.source_id == source] if source else []
    newest = func.coalesce(CollectedItemRow.published_at, CollectedItemRow.collected_at).desc()
    rows = await db.scalars(
        select(CollectedItemRow).where(*conditions).order_by(newest, CollectedItemRow.id)
        .limit(limit).offset(offset),
    )
    total = await db.scalar(select(func.count()).select_from(CollectedItemRow).where(*conditions)) or 0
    return ItemPage(
        items=[
            Item(
                id=row.id, source=row.source_id, external_id=row.external_id, kind=row.kind, title=row.title,
                body=row.body, author=row.author, url=row.url, published_at=iso(row.published_at),
                collected_at=local(row.collected_at).isoformat(timespec="seconds"), mapped=row.mapped,
            )
            for row in rows
        ],
        total=total, limit=limit, offset=offset, has_more=offset + limit < total,
    )


@router.post("/{source}/run")
async def run(source: SourceId, gateway: Network, now: Now) -> RunResult:
    """Collect one source now; a source already collecting is refused."""
    try:
        outcome = await run_source(source, gateway, lambda: now)
    except AlreadyRunningError:
        raise HTTPException(409, "collector is already running") from None
    async with transaction() as db:
        current = (await statuses(db, (source,), now))[0]
    return RunResult(
        source=current, collected=outcome.collected, inserted=outcome.inserted, mapped=outcome.mapped,
        error=outcome.error,
    )


@router.put("/{source}/config")
async def configure(source: SourceId, body: Annotated[JsonObject, Body()], db: Session) -> SavedConfig:
    """Store owner-visible setup values; unknown fields, including secrets, are refused unread."""
    try:
        config = COLLECTORS[source].config_model().model_validate(body)
    except ValidationError:
        raise HTTPException(422, "config is not valid for this source") from None
    row = await locked_source(db, source)
    row.config = config.model_dump(mode="json")
    if row.state in ERROR_ONLY:
        row.state, row.message = "idle", None
    return SavedConfig(source=source, config=row.config)
