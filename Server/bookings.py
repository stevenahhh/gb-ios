"""Class bookings: list, create, deposit confirmation, and session completion."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Final, Literal, assert_never
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
from sqlalchemy import ColumnElement, Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from common import (
    Now,
    PageQuery,
    Revision,
    Session,
    ShortText,
    invalid_transition,
    locked,
    matches,
    required_text,
)
from contracts import ApiModel, ApiRequest, Card, CardAction, CardBooking, CardUndo, Page, Status
from display import clock, day_start, due, local, masked, month_day_weekday, relative_moment, won
from metrics import load_counts, metric
from models import BookingRow, ClassSessionRow, CustomerRow

router = APIRouter()
DEPOSIT_WINDOW: Final = timedelta(hours=24)
type BookingFilter = Literal["all", "confirmed", "deposit_pending"]
type BookingRecord = tuple[BookingRow, ClassSessionRow, CustomerRow, int]


class BookingCreate(ApiRequest):
    """A booking entered by the owner."""

    session_id: ShortText
    customer_name: ShortText
    phone: Annotated[str, Field(max_length=40)] = ""
    party_size: Annotated[int, Field(ge=1, le=50)]


class ExpectedRevision(ApiRequest):
    """A state change based on the revision the client observed."""

    expected_revision: Revision


class SessionCompletion(ExpectedRevision):
    """Mark a class finished or reopen it."""

    done: bool


class SessionOption(ApiModel):
    """A class that can still accept a booking."""

    id: str
    title: str
    schedule: str
    remaining_seats: int
    deposit: str


class SessionState(ApiModel):
    """Persisted completion state of a class."""

    id: str
    is_done: bool
    revision: int
    starts_at: str | None = None


@dataclass(frozen=True, slots=True)
class BookingQuery:
    """Validated list parameters."""

    status: BookingFilter
    text: str


def seats_taken() -> ColumnElement[int]:
    """Count seats held by active bookings in the outer session."""
    held = aliased(BookingRow)
    return (
        select(func.coalesce(func.sum(held.party_size), 0))
        .where(held.session_id == ClassSessionRow.id, held.status != "cancelled")
        .correlate(ClassSessionRow)
        .scalar_subquery()
    )


def booking_records() -> Select[BookingRecord]:
    """Join everything a booking card displays."""
    return (
        select(BookingRow, ClassSessionRow, CustomerRow, seats_taken())
        .join(ClassSessionRow, ClassSessionRow.id == BookingRow.session_id)
        .join(CustomerRow, CustomerRow.id == BookingRow.customer_id)
    )


def schedule_text(session: ClassSessionRow) -> str:
    """Format a class date and time range."""
    end = session.starts_at + timedelta(minutes=session.duration_minutes)
    day = month_day_weekday(local(session.starts_at).date())
    return f"{day} · {clock(session.starts_at)}–{clock(end)}"  # noqa: RUF001


def booking_card(record: BookingRecord, now: datetime) -> Card:
    """Present one booking and the action its state allows."""
    booking, session, customer, taken = record
    who = f"{masked(customer.name)} · {booking.party_size}명"
    lines = [schedule_text(session)]
    info = CardBooking(
        day=local(session.starts_at).date(),
        day_title=f"{month_day_weekday(local(session.starts_at).date())}요일",
        time=clock(session.starts_at), customer=masked(customer.name), people=booking.party_size,
    )
    match booking.status:
        case "confirmed":
            remaining = max(session.capacity - taken, 0)
            lines.append(f"{who} · 예약금 확인 완료 · 남은 자리 {remaining}개")
            return Card(
                id=booking.id, kind="booking", title=session.title, lines=lines, tag="확정",
                status=Status(text="수업 완료" if session.status == "completed" else "확정", tone="done"),
                revision=booking.revision, booking=info,
                undo=CardUndo(path=f"/bookings/{booking.id}/undo-deposit")
                if booking.deposit_won > 0 else None,
            )
        case "deposit_pending":
            lines.append(f"{who} · 예약금 {won(booking.deposit_won)}")
            deposit_due = booking.deposit_due_at or now
            phrase = relative_moment(deposit_due, now.date())
            return Card(
                id=booking.id, kind="booking", title=session.title, lines=lines, tag="예약금 대기",
                status=Status(text="예약금 대기", tone="attention"), revision=booking.revision,
                deadline=f"입금 기한 {phrase}" if deposit_due >= now else f"입금 기한 지남 · {phrase}",
                due=due(deposit_due, prefix="입금 기한"),
                action=CardAction(code="confirmDeposit", label="입금 확인하기"),
                booking=info,
            )
        case _:
            lines.append(who)
            return Card(
                id=booking.id, kind="booking", title=session.title, lines=lines, tag="취소",
                status=Status(text="취소", tone="neutral"), revision=booking.revision,
                booking=info,
            )


def list_conditions(query: BookingQuery) -> list[ColumnElement[bool]]:
    """Translate a filter and search into SQL."""
    conditions: list[ColumnElement[bool]] = []
    match query.status:
        case "all":
            conditions.append(BookingRow.status != "cancelled")
        case "confirmed" | "deposit_pending":
            conditions.append(BookingRow.status == query.status)
        case _:
            assert_never(query.status)
    if query.text:
        conditions.append(or_(
            matches(ClassSessionRow.title, query.text), matches(CustomerRow.name, query.text),
        ))
    return conditions


def upcoming_first(today: date) -> tuple[ColumnElement[int], ColumnElement[datetime]]:
    """Sort future classes before history, nearest first."""
    return (
        case((ClassSessionRow.starts_at >= day_start(today), 0), else_=1),
        ClassSessionRow.starts_at.asc(),
    )


@router.get("/bookings")
async def list_bookings(
    db: Session, now: Now, paging: PageQuery, status: BookingFilter = "all",
    session: Annotated[str | None, Query()] = None,
) -> Page:
    """Return one filtered page of bookings with screen totals."""
    conditions = list_conditions(BookingQuery(status, paging.text))
    if session is not None:
        conditions.append(BookingRow.session_id == session)
    records = await db.execute(
        booking_records().where(*conditions)
        .order_by(*upcoming_first(now.date()), BookingRow.id).limit(paging.limit).offset(paging.offset),
    )
    total = await db.scalar(
        select(func.count()).select_from(BookingRow)
        .join(ClassSessionRow, ClassSessionRow.id == BookingRow.session_id)
        .join(CustomerRow, CustomerRow.id == BookingRow.customer_id).where(*conditions),
    ) or 0
    counts = await load_counts(db, now.date())
    return Page(
        metrics=[
            metric("bookings", "전체", counts.bookings),
            metric("confirmed", "확정", counts.confirmed_bookings),
            metric("depositPending", "예약금 대기", counts.deposit_pending),
        ],
        items=[booking_card(record, now) for record in records.tuples()],
        total=total, limit=paging.limit, offset=paging.offset, has_more=paging.has_more(total),
    )


async def card_for(db: AsyncSession, booking_id: str, now: datetime) -> Card:
    """Reload a booking after a write."""
    record = (await db.execute(booking_records().where(BookingRow.id == booking_id))).tuples().one()
    return booking_card(record, now)


@router.get("/class-sessions")
async def bookable_sessions(db: Session, now: Now) -> list[SessionOption]:
    """List future classes with free seats for the booking form."""
    taken = seats_taken()
    rows = await db.execute(
        select(ClassSessionRow, taken)
        .where(
            ClassSessionRow.status == "scheduled", ClassSessionRow.starts_at > now,
            taken < ClassSessionRow.capacity,
        )
        .order_by(ClassSessionRow.starts_at).limit(50),
    )
    return [
        SessionOption(
            id=session.id, title=session.title, schedule=schedule_text(session),
            remaining_seats=session.capacity - seats, deposit=won(session.deposit_won),
        )
        for session, seats in rows.tuples()
    ]


async def customer_for(db: AsyncSession, name: str, phone: str | None) -> str:
    """Reuse an exact customer match or create the customer."""
    existing = await db.scalar(
        select(CustomerRow.id)
        .where(CustomerRow.name == name, CustomerRow.phone.is_not_distinct_from(phone))
        .order_by(CustomerRow.id).limit(1),
    )
    if existing is not None:
        return existing
    customer_id = f"customer-{uuid4().hex}"
    db.add(CustomerRow(id=customer_id, name=name, phone=phone))
    await db.flush()
    return customer_id


@router.post("/bookings", status_code=201)
async def create_booking(body: BookingCreate, db: Session, now: Now) -> Card:
    """Reserve seats while holding the class lock, so capacity cannot be oversold."""
    session = await db.scalar(
        select(ClassSessionRow).where(ClassSessionRow.id == body.session_id).with_for_update(),
    )
    if session is None:
        raise HTTPException(404, "resource not found")
    if session.status != "scheduled" or session.starts_at <= now:
        raise invalid_transition()
    taken = await db.scalar(select(seats_taken()).where(ClassSessionRow.id == session.id)) or 0
    if taken + body.party_size > session.capacity:
        raise HTTPException(409, "class does not have enough seats")
    customer_id = await customer_for(db, required_text(body.customer_name), body.phone.strip() or None)
    needs_deposit = session.deposit_won > 0
    booking = BookingRow(
        id=f"booking-{uuid4().hex}", session_id=session.id, customer_id=customer_id, channel_id=None,
        party_size=body.party_size, deposit_won=session.deposit_won,
        status="deposit_pending" if needs_deposit else "confirmed",
        deposit_due_at=min(now + DEPOSIT_WINDOW, session.starts_at) if needs_deposit else None,
    )
    db.add(booking)
    await db.flush()
    return await card_for(db, booking.id, now)


@router.post("/bookings/{booking_id}/confirm-deposit")
async def confirm_deposit(booking_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Confirm a pending booking after the owner sees the deposit."""
    booking = await locked(db, BookingRow, booking_id, body.expected_revision)
    if booking.status != "deposit_pending":
        raise invalid_transition()
    booking.status = "confirmed"
    booking.deposit_confirmed_at = now
    booking.revision += 1
    await db.flush()
    return await card_for(db, booking.id, now)


@router.post("/class-sessions/{session_id}/completion")
async def set_session_completion(session_id: str, body: SessionCompletion, db: Session) -> SessionState:
    """Mark today's class finished, or undo that mark."""
    session = await locked(db, ClassSessionRow, session_id, body.expected_revision)
    current, target = ("scheduled", "completed") if body.done else ("completed", "scheduled")
    if session.status != current:
        raise invalid_transition()
    session.status = target
    session.revision += 1
    await db.flush()
    return SessionState(id=session.id, is_done=body.done, revision=session.revision)
