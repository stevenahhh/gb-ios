"""Assistant recommendations whose facts are computed when read."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

from fastapi import APIRouter
from sqlalchemy import ColumnElement, Nullable, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import ExpectedRevision, seats_taken
from common import Now, Session, invalid_transition, locked
from contracts import Card, CardAction, CardDraft, Status
from display import count, local, weekday
from draft_contracts import draft_reference
from metrics import Counts, load_counts
from models import ClassSessionRow, ContentDraftRow, RecommendationRow

router = APIRouter()
WEEKEND_WINDOW: Final = timedelta(days=14)
POSTGRES_SATURDAY: Final = 6
POSTGRES_SUNDAY: Final = 0


@dataclass(frozen=True, slots=True)
class SeatOpening:
    """The nearest weekend class with free seats."""

    title: str
    day: date
    remaining: int


async def weekend_opening(db: AsyncSession, now: datetime) -> SeatOpening | None:
    """Find the nearest weekend class that still has seats."""
    taken = seats_taken()
    row = (
        (
            await db.execute(
                select(ClassSessionRow, taken)
                .where(
                    ClassSessionRow.status == "scheduled",
                    ClassSessionRow.starts_at > now,
                    ClassSessionRow.starts_at < now + WEEKEND_WINDOW,
                    taken < ClassSessionRow.capacity,
                    extract("dow", func.timezone("Asia/Seoul", ClassSessionRow.starts_at)).in_(
                        [POSTGRES_SATURDAY, POSTGRES_SUNDAY],
                    ),
                )
                .order_by(ClassSessionRow.starts_at)
                .limit(1),
            )
        )
        .tuples()
        .one_or_none()
    )
    if row is None:
        return None
    session, seats = row
    return SeatOpening(session.title, local(session.starts_at).date(), session.capacity - seats)


def recommendation_lines(
    row: RecommendationRow,
    counts: Counts,
    opening: SeatOpening | None,
) -> list[str] | None:
    """Compute current facts; a recommendation with no current basis is hidden."""
    match row.kind:
        case "seat_promotion":
            if opening is None:
                return None
            fact = f"{weekday(opening.day)}요일 {opening.title}에 {opening.remaining}자리가 남아 있어요."
            return [fact, row.body]
        case "deposit_reminder":
            if counts.deposit_pending == 0:
                return None
            return [f"예약금을 기다리는 예약이 {count(counts.deposit_pending)} 있어요.", row.body]
        case _:
            return [line for line in (row.source_name, row.body) if line]


def recommendation_card(row: RecommendationRow, lines: list[str], draft: CardDraft | None = None) -> Card:
    """Present a recommendation and its acknowledgement state."""
    is_open = row.status == "open"
    return Card(
        id=row.id,
        kind="recommendation",
        title=row.title,
        lines=lines,
        revision=row.revision,
        status=None if is_open else Status(text="반려함", tone="neutral")
        if row.status == "rejected" else Status(text="확인함", tone="done"),
        action=CardAction(code="acknowledgeRecommendation", label="확인했어요") if is_open else None,
        draft=draft or draft_reference(row),
    )


async def recommendation_cards(
    db: AsyncSession, now: datetime, *conditions: ColumnElement[bool],
) -> list[Card]:
    """Load recommendations whose basis is currently true."""
    counts = await load_counts(db, now.date())
    opening = await weekend_opening(db, now)
    rows = await db.execute(
        select(RecommendationRow, Nullable(ContentDraftRow))
        .outerjoin(ContentDraftRow, ContentDraftRow.id == RecommendationRow.draft_id)
        .where(*conditions)
        .order_by(RecommendationRow.status.desc(), RecommendationRow.created_at, RecommendationRow.id)
        .limit(50),
    )
    cards: list[Card] = []
    for row, draft in rows.tuples():
        lines = recommendation_lines(row, counts, opening)
        if lines is None and row.status != "open":
            lines = [line for line in (row.source_name, row.body) if line]
        if lines is not None:
            cards.append(recommendation_card(row, lines, draft_reference(draft or row)))
    return cards


@router.get("/opportunities")
async def opportunities(db: Session, now: Now) -> list[Card]:
    """List stored market and program opportunities."""
    return await recommendation_cards(db, now, RecommendationRow.kind == "opportunity")


@router.post("/recommendations/{recommendation_id}/acknowledge")
async def acknowledge(recommendation_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Remove a recommendation from the open list."""
    row = await locked(db, RecommendationRow, recommendation_id, body.expected_revision)
    if row.status != "open":
        raise invalid_transition()
    row.status = "acknowledged"
    row.acknowledged_at = now
    row.revision += 1
    await db.flush()
    draft = await db.get(ContentDraftRow, row.draft_id) if row.draft_id else None
    return recommendation_card(
        row, [line for line in (row.source_name, row.body) if line], draft_reference(draft or row),
    )
