"""Grounded reply engine (K25): fact cards, checked drafts, owner judgments, and saved rules.

Every route here is additive. Build A never calls them, and the existing inquiry, draft, and
today routes are unchanged.
"""

import hashlib
import logging
from datetime import datetime
from typing import Annotated, Final, Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k25_claims import number_tokens
from b_k25_interview import is_unsure, number_value
from b_k25_prompts import (
    INTERVIEW_SAMPLING,
    FactField,
    interview_messages,
    mask_contacts,
    parse_interview,
)
from b_k25_tables import FactCardRow, OwnerRuleRow
from bookings import ExpectedRevision
from common import Now, Session, ShortText, require_revision
from contracts import ApiModel, ApiRequest
from models import ClassSessionRow
from providers import chat

LOGGER: Final = logging.getLogger("roundup.grounded")
router = APIRouter()
FACT_COLUMNS: Final[tuple[str, ...]] = (
    "duration_minutes", "capacity", "included_materials", "parking", "refund_policy",
)
MAX_FACT_TEXT: Final = 1000
MAX_PRICE: Final = 10_000_000
MAX_MINUTES: Final = 1440
MAX_PEOPLE: Final = 1000
MAX_VALUE_CHARS: Final = 200


class FactCardSummary(ApiModel):
    """One class on the fact-card list; revision 0 means nothing has been saved yet."""

    id: str
    class_name: str
    filled_count: int
    rule_count: int
    revision: int
    updated_at: datetime | None


class RuleView(ApiModel):
    """One saved rule and the class it belongs to; no class means the whole workshop."""

    id: str
    card_id: str | None
    class_name: str | None
    rule_text: str
    question_summary: str
    created_at: datetime


class FactCardDetail(ApiModel):
    """A fact card with the rules that apply to it."""

    id: str
    class_name: str
    duration_minutes: int | None
    capacity: int | None
    included_materials: str | None
    parking: str | None
    refund_policy: str | None
    price_won: int | None
    filled_count: int
    revision: int
    updated_at: datetime | None
    rules: list[RuleView]


class FactCardUpdate(ExpectedRevision):
    """The five interview columns and the price; revision 0 creates the card of the named class."""

    class_name: ShortText
    duration_minutes: Annotated[int, Field(gt=0, le=MAX_MINUTES)] | None = None
    capacity: Annotated[int, Field(gt=0, le=MAX_PEOPLE)] | None = None
    included_materials: Annotated[str, Field(max_length=MAX_FACT_TEXT)] | None = None
    parking: Annotated[str, Field(max_length=MAX_FACT_TEXT)] | None = None
    refund_policy: Annotated[str, Field(max_length=MAX_FACT_TEXT)] | None = None
    price_won: Annotated[int, Field(gt=0, le=MAX_PRICE)] | None = None


class InterviewRequest(ApiRequest):
    """One spoken or typed answer to a card question; nothing is stored."""

    field: FactField
    answer: Annotated[str, Field(min_length=1, max_length=MAX_FACT_TEXT)]


class InterviewResponse(ApiModel):
    """The answer as a card value; an unclear answer carries no value."""

    field: FactField
    value: str
    confidence: Literal["clear", "unclear"]


def card_id_for(class_name: str) -> str:
    """Derive a stable card id from the class name, so a class without a card has one too."""
    digest = hashlib.sha256(" ".join(class_name.split()).encode()).hexdigest()
    return f"card-{digest[:16]}"


def filled_count(row: FactCardRow) -> int:
    """Count the filled interview columns of a saved card."""
    return sum(getattr(row, name) is not None for name in FACT_COLUMNS)


async def class_names(db: AsyncSession, now: datetime) -> list[str]:
    """Class names of the calendar, with the ones still ahead first."""
    upcoming = func.min(ClassSessionRow.starts_at).filter(ClassSessionRow.starts_at > now)
    rows = await db.scalars(
        select(ClassSessionRow.title).where(ClassSessionRow.status != "cancelled")
        .group_by(ClassSessionRow.title).order_by(upcoming.nulls_last(), ClassSessionRow.title),
    )
    return list(rows)


async def rule_views(db: AsyncSession) -> list[RuleView]:
    """Every rule the owner still uses, newest first."""
    rows = await db.execute(
        select(OwnerRuleRow, FactCardRow.class_name)
        .outerjoin(FactCardRow, FactCardRow.id == OwnerRuleRow.card_id)
        .where(OwnerRuleRow.retired_at.is_(None)).order_by(OwnerRuleRow.created_at.desc()),
    )
    return [
        RuleView(
            id=rule.id, card_id=rule.card_id, class_name=name, rule_text=rule.rule_text,
            question_summary=rule.question_summary, created_at=rule.created_at,
        )
        for rule, name in rows.tuples()
    ]


def empty_card(class_name: str) -> FactCardDetail:
    """Describe a class that has no saved facts yet."""
    return FactCardDetail(
        id=card_id_for(class_name), class_name=class_name, duration_minutes=None, capacity=None,
        included_materials=None, parking=None, refund_policy=None, price_won=None, filled_count=0,
        revision=0, updated_at=None, rules=[],
    )


async def card_detail(db: AsyncSession, row: FactCardRow) -> FactCardDetail:
    """Serialize a saved card with its rules and the workshop-wide ones."""
    rules = [rule for rule in await rule_views(db) if rule.card_id in {None, row.id}]
    return FactCardDetail(
        id=row.id, class_name=row.class_name, duration_minutes=row.duration_minutes,
        capacity=row.capacity, included_materials=row.included_materials, parking=row.parking,
        refund_policy=row.refund_policy, price_won=row.price_won, filled_count=filled_count(row),
        revision=row.revision, updated_at=row.updated_at, rules=rules,
    )


@router.get("/fact-cards")
async def list_fact_cards(db: Session, now: Now) -> list[FactCardSummary]:
    """List every class of the calendar with how much of its card is filled."""
    cards = {row.class_name: row for row in await db.scalars(select(FactCardRow))}
    counts = dict((await db.execute(
        select(OwnerRuleRow.card_id, func.count()).where(OwnerRuleRow.retired_at.is_(None))
        .group_by(OwnerRuleRow.card_id),
    )).tuples().all())
    names = await class_names(db, now)
    names += sorted(name for name in cards if name not in names)
    summaries: list[FactCardSummary] = []
    for name in names:
        row = cards.get(name)
        summaries.append(FactCardSummary(
            id=card_id_for(name) if row is None else row.id, class_name=name,
            filled_count=0 if row is None else filled_count(row),
            rule_count=0 if row is None else counts.get(row.id, 0),
            revision=0 if row is None else row.revision, updated_at=None if row is None else row.updated_at,
        ))
    return summaries


@router.get("/fact-cards/{card_id}")
async def fact_card(card_id: str, db: Session, now: Now) -> FactCardDetail:
    """Return one card; a class without a saved card is returned empty."""
    row = await db.get(FactCardRow, card_id)
    if row is not None:
        return await card_detail(db, row)
    name = next((name for name in await class_names(db, now) if card_id_for(name) == card_id), None)
    if name is None:
        raise HTTPException(404, "resource not found")
    return empty_card(name)


def cleaned(value: str | None) -> str | None:
    """Store blank text as a missing fact."""
    text = " ".join(value.split()) if value is not None else ""
    return text or None


@router.put("/fact-cards/{card_id}")
async def save_fact_card(card_id: str, body: FactCardUpdate, db: Session) -> FactCardDetail:
    """Create or replace a card under optimistic concurrency; revision 0 creates it."""
    class_name = " ".join(body.class_name.split())
    if card_id_for(class_name) != card_id:
        raise HTTPException(422, "card does not belong to that class")
    values = {
        "duration_minutes": body.duration_minutes, "capacity": body.capacity,
        "included_materials": cleaned(body.included_materials), "parking": cleaned(body.parking),
        "refund_policy": cleaned(body.refund_policy), "price_won": body.price_won,
    }
    row = await db.get(FactCardRow, card_id, with_for_update=True)
    if row is None:
        if body.expected_revision != 0:
            raise HTTPException(409, "revision is stale")
        row = FactCardRow(id=card_id, class_name=class_name, revision=1, **values)
        db.add(row)
        await db.flush()
        return await card_detail(db, row)
    require_revision(row.revision, body.expected_revision)
    for name, value in values.items():
        setattr(row, name, value)
    row.revision += 1
    await db.flush()
    return await card_detail(db, row)


@router.post("/fact-cards/{card_id}/interview")
async def interview(card_id: str, body: InterviewRequest) -> InterviewResponse:
    """Read one spoken answer as a card value; nothing is stored and the words are not logged.

    Numbers come from the answer alone. Free text is tidied by the model, which may not change a
    number; a malformed or failed answer falls back to the owner's own words.
    """
    _ = card_id
    unclear = InterviewResponse(field=body.field, value="", confidence="unclear")
    if is_unsure(body.answer):
        return unclear
    if body.field in {"durationMinutes", "capacity"}:
        value = number_value(body.field, body.answer)
        if value is None:
            return unclear
        return InterviewResponse(field=body.field, value=value, confidence="clear")
    fallback = " ".join(body.answer.split())
    value = fallback
    try:
        answered = await chat(interview_messages(body.field, body.answer), INTERVIEW_SAMPLING)
        cleaned_value = parse_interview(answered)
    except HTTPException as error:
        LOGGER.warning("interview_fallback", extra={"error_type": type(error).__name__})
        cleaned_value = None
    if cleaned_value and len(cleaned_value) <= MAX_VALUE_CHARS and (
        number_tokens(cleaned_value) <= number_tokens(mask_contacts(body.answer))
    ):
        value = cleaned_value
    return InterviewResponse(field=body.field, value=value[:MAX_FACT_TEXT], confidence="clear")
