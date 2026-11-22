"""Persist sources, runs, and items; repeated collection never duplicates a row."""

from datetime import datetime, timedelta
from typing import Final
from uuid import uuid4

from sqlalchemy import Boolean, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from collectors.base import CollectedItem, SourceId
from collectors.text import MAX_TITLE, clean_raw, plain_text
from models import CollectedItemRow, CollectorRunRow, CollectorSourceRow

STALE: Final = timedelta(minutes=15)


async def locked_source(db: AsyncSession, source: SourceId) -> CollectorSourceRow:
    """Create the source row when it is first used, then lock it."""
    _ = await db.execute(
        insert(CollectorSourceRow).values(id=source, state="idle").on_conflict_do_nothing(),
    )
    return (await db.scalars(
        select(CollectorSourceRow).where(CollectorSourceRow.id == source).with_for_update(),
    )).one()


def is_running(row: CollectorSourceRow, now: datetime) -> bool:
    """Tell a live run from one whose process died."""
    return row.state == "collecting" and row.last_run_at is not None and row.last_run_at > now - STALE


async def open_run(db: AsyncSession, row: CollectorSourceRow, now: datetime) -> str:
    """Close abandoned runs and record the new one."""
    _ = await db.execute(
        update(CollectorRunRow)
        .where(CollectorRunRow.source_id == row.id, CollectorRunRow.status == "running")
        .values(status="failed", finished_at=now, error="interrupted"),
    )
    run_id = uuid4().hex
    db.add(CollectorRunRow(id=run_id, source_id=row.id, status="running", started_at=now))
    row.state, row.message, row.last_run_at = "collecting", None, now
    return run_id


async def save_item(db: AsyncSession, source: SourceId, item: CollectedItem, now: datetime) -> bool:
    """Insert or refresh one item; only changed content is mapped again."""
    statement = insert(CollectedItemRow).values(
        id=uuid4().hex, source_id=source, external_id=item.external_id, kind=item.kind, title=item.title,
        body=item.body, author=plain_text(item.author, MAX_TITLE) if item.author else None, url=item.url,
        published_at=item.published_at, raw=clean_raw(item.raw), mapped=False, collected_at=now,
        updated_at=now,
    )
    fresh = statement.excluded
    changed = or_(
        CollectedItemRow.title != fresh.title, CollectedItemRow.body != fresh.body,
        CollectedItemRow.raw != fresh.raw, CollectedItemRow.url.is_distinct_from(fresh.url),
        CollectedItemRow.author.is_distinct_from(fresh.author),
    )
    result = await db.execute(
        statement.on_conflict_do_update(
            index_elements=[CollectedItemRow.source_id, CollectedItemRow.external_id],
            set_={
                "title": fresh.title, "body": fresh.body, "author": fresh.author, "url": fresh.url,
                "published_at": fresh.published_at, "raw": fresh.raw, "mapped": False, "updated_at": now,
            },
            where=changed,
        ).returning(literal_column("(xmax = 0)", Boolean)),
    )
    return result.scalar_one_or_none() is True
