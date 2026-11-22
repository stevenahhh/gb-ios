"""Pasted cancellation messages: match a booking, calculate, record the decision, and word a reply."""

import hashlib
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, Field, TypeAdapter
from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k06_ai import Source, read_message, write_reply
from b_k06_logic import (
    Category,
    Decision,
    Kind,
    Payment,
    Quote,
    ReplyFacts,
    Rule,
    category_of,
    compute,
    edited_characters,
    fallback_reply,
    mentions,
    rule_label,
    when_text,
)
from b_k06_models import (
    WORKSHOP_ID,
    BookingMarkRow,
    CancellationCaseRow,
    PolicyVersionRow,
    SessionPlanRow,
)
from b_k06_policy import iso, latest_policy, noticed_policy, policy_of
from bookings import seats_taken
from common import MAX_TEXT, Now, Revision, Session, invalid_transition, required_text
from contracts import ApiModel, ApiRequest
from database import transaction
from display import day_start, local, next_day_start
from models import BookingRow, ChannelRow, ClassSessionRow, CustomerRow

router = APIRouter()
DECISION: TypeAdapter[Decision] = TypeAdapter(Decision)
RECENT = timedelta(days=7)
PRECEDENTS = 2
CASES = 100
type Arm = Literal["card", "control"]
type Warn = Literal["no_notice", "no_policy", "undecided_rule", "material_unknown", "naver_booking"]
type BookingParts = tuple[BookingRow, ClassSessionRow, CustomerRow]


class IntakeRequest(ApiRequest):
    """A pasted customer message; it is read and then forgotten."""

    message: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]


class Candidate(ApiModel):
    """A booking the message may be about."""

    booking_id: str
    customer_name: str
    class_title: str
    session_starts_at: str
    seats: int
    paid: int
    arm: Arm


class Intake(ApiModel):
    """What the message asks and which bookings match."""

    kind: Kind
    reason_category: Category | None
    candidates: list[Candidate]
    recent: list[Candidate]


class QuoteRequest(ApiRequest):
    """The booking to calculate for."""

    booking_id: Annotated[str, Field(min_length=1, max_length=200)]
    reason_category: Category | None = None


class Precedent(ApiModel):
    """An earlier exception the owner made."""

    case_id: str
    decided_at: str
    reason: str
    decision: Decision


class QuoteView(ApiModel):
    """A reference calculation with its basis."""

    booking_id: str
    revision: int
    customer_name: str
    class_title: str
    session_starts_at: str
    seats: int
    policy_version: int | None
    noticed_at: str | None
    days_left: int
    paid: int
    refund: int | None
    matched_rule: Rule | None
    matched_label: str | None
    precedents: list[Precedent]
    warnings: list[Warn]


class DecisionRequest(ApiRequest):
    """The owner's choice; an exception needs a reason and a custom one an amount."""

    decision: Decision
    reason: Annotated[str, Field(max_length=200)] = ""
    reason_category: Category | None = None
    refund_won: Annotated[int, Field(ge=0)] | None = None
    expected_revision: Revision
    pasted_at: Annotated[AwareDatetime, Field(strict=False)] | None = None
    card_shown_at: Annotated[AwareDatetime, Field(strict=False)] | None = None


class DecisionView(ApiModel):
    """The recorded decision and a fixed reply, ready before any model answers."""

    case_id: str
    draft: str
    refund: int
    seat_opened: bool
    session_id: str


class DraftView(ApiModel):
    """A reply draft and whether the model wrote it."""

    draft: str
    source: Source


class ApproveRequest(ApiRequest):
    """The reply the owner copied."""

    draft: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]


class Approval(ApiModel):
    """When the reply was approved."""

    approved_at: str
    edit_chars: int


class Removed(ApiModel):
    """How many records were removed."""

    removed: int


class CaseView(ApiModel):
    """One recorded decision."""

    case_id: str
    booking_id: str | None
    customer_name: str | None
    kind: str
    decision: str | None
    reason: str
    decided_at: str


class Computed(ApiModel):
    """The calculation stored with a decision."""

    days_left: int
    paid: int
    refund: int | None
    version: int | None
    noticed_on: date | None
    prior_status: str


def booking_parts() -> Select[BookingParts]:
    """Join everything a cancellation reads."""
    return (
        select(BookingRow, ClassSessionRow, CustomerRow)
        .join(ClassSessionRow, ClassSessionRow.id == BookingRow.session_id)
        .join(CustomerRow, CustomerRow.id == BookingRow.customer_id)
    )


async def one_booking(db: AsyncSession, booking_id: str, *, lock: bool = False) -> BookingParts:
    """Read one booking; a write locks its row first."""
    query = booking_parts().where(BookingRow.id == booking_id)
    if lock:
        query = query.with_for_update(of=BookingRow)
    row = (await db.execute(query)).tuples().one_or_none()
    if row is None:
        raise HTTPException(404, "resource not found")
    return row


def paid_won(booking: BookingRow) -> int:
    """Count only a deposit the owner confirmed."""
    return booking.deposit_won if booking.deposit_confirmed_at is not None else 0


def arm_of(booking_id: str) -> Arm:
    """Assign a stable half of bookings to each arm."""
    return "card" if hashlib.sha256(booking_id.encode()).digest()[0] % 2 == 0 else "control"


def candidate(parts: BookingParts) -> Candidate:
    """Present one matching booking."""
    booking, session, customer = parts
    return Candidate(
        booking_id=booking.id, customer_name=customer.name, class_title=session.title,
        session_starts_at=iso(session.starts_at), seats=booking.party_size, paid=paid_won(booking),
        arm=arm_of(booking.id),
    )


async def open_bookings(db: AsyncSession, now: datetime) -> list[BookingParts]:
    """Read bookings a customer can still cancel, today's classes included."""
    rows = await db.execute(
        booking_parts().where(
            BookingRow.status != "cancelled", ClassSessionRow.status == "scheduled",
            ClassSessionRow.starts_at >= day_start(now.date()),
        ).order_by(ClassSessionRow.starts_at, BookingRow.id),
    )
    return list(rows.tuples())


def matching(found: list[BookingParts], text: str, day: date | None) -> list[BookingParts]:
    """Match by the customer's name first, then narrow by the class date."""
    named = [parts for parts in found if mentions(text, parts[2].name)]
    dated = [parts for parts in named or found if local(parts[1].starts_at).date() == day]
    return dated or named


@router.post("/cancellations/intake")
async def intake(body: IntakeRequest, now: Now) -> Intake:
    """Read a message and find its booking; the database is not held while the model reads."""
    message = required_text(body.message)
    async with transaction() as db:
        found = await open_bookings(db, now)
        names = list(await db.scalars(select(CustomerRow.name)))
    reading = await read_message(message, now.date(), names)
    matches = matching(found, message, reading.day)
    limit = next_day_start(now.date() + RECENT)
    recent = [] if matches else [parts for parts in found if parts[1].starts_at < limit]
    return Intake(
        kind=reading.kind, reason_category=category_of(message),
        candidates=[candidate(parts) for parts in matches], recent=[candidate(parts) for parts in recent],
    )


async def precedents(db: AsyncSession, category: Category | None) -> list[Precedent]:
    """Find the latest exceptions for the same kind of reason."""
    query = select(CancellationCaseRow).where(
        CancellationCaseRow.workshop_id == WORKSHOP_ID, CancellationCaseRow.kind == "cancel",
        CancellationCaseRow.decision.in_(("carry_over", "full_refund", "custom")),
    )
    if category is not None:
        query = query.where(CancellationCaseRow.reason_category == category)
    rows = await db.scalars(query.order_by(CancellationCaseRow.decided_at.desc()).limit(PRECEDENTS))
    return [
        Precedent(
            case_id=row.id, decided_at=iso(row.decided_at), reason=row.reason,
            decision=DECISION.validate_python(row.decision),
        )
        for row in rows
    ]


class Basis(ApiModel):
    """The calculation behind a card, before it is shown or recorded."""

    version_id: str | None
    version: int | None
    noticed_on: date | None
    warnings: list[Warn]


async def calculate(
    db: AsyncSession, parts: BookingParts, now: datetime,
) -> tuple[Quote, Basis]:
    """Calculate with the version this customer was told about, or the current one with a warning."""
    booking, session, _ = parts
    warnings: list[Warn] = []
    noticed = await noticed_policy(db, booking.id, now)
    row: PolicyVersionRow | None = noticed[0] if noticed else await latest_policy(db)
    if row is None:
        warnings.append("no_policy")
    elif noticed is None:
        warnings.append("no_notice")
    plan = await db.get(SessionPlanRow, session.id)
    material = plan.material_won * booking.party_size if plan and plan.material_won is not None else None
    quote = compute(
        policy_of(row).rules if row else (), session.starts_at, now, Payment(paid_won(booking), material),
    )
    if row is not None and quote.refund is None:
        unknown = quote.rule is not None and quote.rule.refund_percent is not None
        warnings.append("material_unknown" if unknown else "undecided_rule")
    channel = await db.get(ChannelRow, booking.channel_id) if booking.channel_id else None
    if channel is not None and channel.kind == "naver_booking":
        warnings.append("naver_booking")
    return quote, Basis(
        version_id=row.id if row else None, version=row.version if row else None,
        noticed_on=noticed[1] if noticed else None, warnings=warnings,
    )


@router.post("/cancellations/quote")
async def quote(body: QuoteRequest, db: Session, now: Now) -> QuoteView:
    """Calculate a refund without a model."""
    parts = await one_booking(db, body.booking_id)
    booking, session, customer = parts
    result, basis = await calculate(db, parts, now)
    return QuoteView(
        booking_id=booking.id, revision=booking.revision, customer_name=customer.name,
        class_title=session.title, session_starts_at=iso(session.starts_at), seats=booking.party_size,
        policy_version=basis.version,
        noticed_at=basis.noticed_on.isoformat() if basis.noticed_on else None,
        days_left=result.days_left, paid=paid_won(booking), refund=result.refund, matched_rule=result.rule,
        matched_label=rule_label(result.rule) if result.rule else None,
        precedents=await precedents(db, body.reason_category), warnings=basis.warnings,
    )


def decided_amount(body: DecisionRequest, result: Quote, paid: int) -> int:
    """Turn the owner's choice into an amount, refusing one the rules or payment cannot support."""
    match body.decision:
        case "by_rule":
            if result.refund is None:
                raise HTTPException(422, "the rules leave this to the owner")
            return result.refund
        case "carry_over":
            return 0
        case "full_refund":
            return paid
        case "custom":
            if body.refund_won is None or body.refund_won > paid:
                raise HTTPException(422, "refund must be between zero and the paid amount")
            return body.refund_won


def reply_facts(case: CancellationCaseRow, parts: BookingParts) -> ReplyFacts:
    """Rebuild a reply's facts from the recorded decision."""
    _, session, customer = parts
    computed = Computed.model_validate(case.computed)
    return ReplyFacts(
        customer=customer.name, class_title=session.title, class_when=when_text(session.starts_at),
        decision=DECISION.validate_python(case.decision), reason=case.reason, paid=computed.paid,
        refund=case.decided_won or 0,
        days=computed.days_left, version=computed.version, noticed=computed.noticed_on,
    )


async def mark_for(db: AsyncSession, booking_id: str) -> BookingMarkRow:
    """Read or create a booking's marks; the caller holds the booking lock."""
    mark = await db.get(BookingMarkRow, booking_id)
    if mark is None:
        mark = BookingMarkRow(booking_id=booking_id)
        db.add(mark)
    return mark


@router.post("/cancellations/{booking_id}/decision")
async def decide(booking_id: str, body: DecisionRequest, db: Session, now: Now) -> DecisionView:
    """Record the owner's decision and free the seats; no money moves and nothing is sent."""
    parts = await one_booking(db, booking_id, lock=True)
    booking, session, _ = parts
    if booking.revision != body.expected_revision:
        raise HTTPException(409, "revision is stale")
    if booking.status == "cancelled" or session.status != "scheduled":
        raise invalid_transition()
    reason = body.reason.strip()
    if body.decision != "by_rule" and not reason:
        raise HTTPException(422, "an exception needs a reason")
    result, basis = await calculate(db, parts, now)
    paid = paid_won(booking)
    amount = decided_amount(body, result, paid)
    computed = Computed(
        days_left=result.days_left, paid=paid, refund=result.refund, version=basis.version,
        noticed_on=basis.noticed_on, prior_status=booking.status,
    )
    case = CancellationCaseRow(
        id=f"case-{uuid4().hex}", workshop_id=WORKSHOP_ID, booking_id=booking.id, session_id=session.id,
        kind="cancel", policy_version_id=basis.version_id, computed=computed.model_dump(mode="json"),
        decision=body.decision, reason=reason, reason_category=body.reason_category, draft="",
        arm=arm_of(booking.id), decided_won=amount, pasted_at=body.pasted_at,
        card_shown_at=body.card_shown_at, decided_at=now,
    )
    case.draft = fallback_reply(reply_facts(case, parts))
    db.add(case)
    booking.status = "cancelled"
    booking.revision += 1
    (await mark_for(db, booking.id)).cancelled_at = now
    await db.flush()
    return DecisionView(
        case_id=case.id, draft=case.draft, refund=amount, seat_opened=session.starts_at > now,
        session_id=session.id,
    )


async def cancel_case(
    db: AsyncSession, case_id: str, *, lock: bool = True,
) -> tuple[CancellationCaseRow, str]:
    """Read one cancellation decision and its booking."""
    query = select(CancellationCaseRow).where(
        CancellationCaseRow.id == case_id, CancellationCaseRow.kind == "cancel",
    )
    case = await db.scalar(query.with_for_update() if lock else query)
    if case is None or case.booking_id is None:
        raise HTTPException(404, "resource not found")
    return case, case.booking_id


@router.post("/cancellations/cases/{case_id}/draft")
async def draft_reply(case_id: str) -> DraftView:
    """Word the reply with the model while no transaction is open."""
    async with transaction() as db:
        case, booking_id = await cancel_case(db, case_id, lock=False)
        if case.approved_at is not None:
            raise invalid_transition()
        facts = reply_facts(case, await one_booking(db, booking_id))
    text, source = await write_reply(facts)
    async with transaction() as db:
        case, _ = await cancel_case(db, case_id)
        if case.approved_at is not None:
            raise invalid_transition()
        case.draft = text
    return DraftView(draft=text, source=source)


@router.post("/cancellations/cases/{case_id}/approve")
async def approve_reply(case_id: str, body: ApproveRequest, db: Session, now: Now) -> Approval:
    """Record that the owner approved and copied the reply."""
    case, _ = await cancel_case(db, case_id)
    if case.approved_at is not None:
        raise invalid_transition()
    final = required_text(body.draft)
    edits = edited_characters(case.draft, final)
    case.edit_chars = edits
    case.draft = final
    case.approved_at = now
    await db.flush()
    return Approval(approved_at=iso(now), edit_chars=edits)


@router.post("/cancellations/cases/{case_id}/undo")
async def undo_decision(case_id: str, db: Session) -> Removed:
    """Give the booking its seats back when they are still free."""
    case, booking_id = await cancel_case(db, case_id)
    booking, session, _ = await one_booking(db, booking_id, lock=True)
    locked = await db.scalar(
        select(ClassSessionRow).where(ClassSessionRow.id == session.id).with_for_update(),
    )
    taken = await db.scalar(select(seats_taken()).where(ClassSessionRow.id == session.id)) or 0
    if locked is None or locked.status != "scheduled" or booking.status != "cancelled":
        raise invalid_transition()
    if taken + booking.party_size > session.capacity:
        raise HTTPException(409, "class does not have enough seats")
    booking.status = Computed.model_validate(case.computed).prior_status
    booking.revision += 1
    (await mark_for(db, booking.id)).cancelled_at = None
    await db.delete(case)
    await db.flush()
    return Removed(removed=1)


@router.get("/cancellations/cases")
async def list_cases(db: Session) -> list[CaseView]:
    """List recorded decisions, newest first."""
    rows = await db.execute(
        select(CancellationCaseRow, CustomerRow.name)
        .outerjoin(BookingRow, BookingRow.id == CancellationCaseRow.booking_id)
        .outerjoin(CustomerRow, CustomerRow.id == BookingRow.customer_id)
        .where(CancellationCaseRow.workshop_id == WORKSHOP_ID)
        .order_by(CancellationCaseRow.decided_at.desc(), CancellationCaseRow.id).limit(CASES),
    )
    return [
        CaseView(
            case_id=case.id, booking_id=case.booking_id, customer_name=name, kind=case.kind,
            decision=case.decision, reason=case.reason, decided_at=iso(case.decided_at),
        )
        for case, name in rows.tuples()
    ]


@router.delete("/bookings/{booking_id}/cancellation-cases")
async def remove_cases(booking_id: str, db: Session) -> Removed:
    """Delete every record of one booking when its customer asks."""
    total = await db.scalar(
        select(func.count()).select_from(CancellationCaseRow)
        .where(CancellationCaseRow.booking_id == booking_id),
    ) or 0
    _ = await db.execute(delete(CancellationCaseRow).where(CancellationCaseRow.booking_id == booking_id))
    return Removed(removed=total)
