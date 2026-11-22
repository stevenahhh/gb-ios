"""Attendance, late guests, freed seats, and under-filled classes; every text is fixed wording."""

from datetime import datetime, time, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, Field, TypeAdapter
from sqlalchemy import case as sql_case
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k06_cancel import (
    BookingParts,
    Computed,
    Removed,
    booking_parts,
    mark_for,
    one_booking,
    paid_won,
)
from b_k06_logic import DEFAULT_LATE_MINUTES, LateRule, days_left, when_text
from b_k06_models import (
    WORKSHOP_ID,
    BookingMarkRow,
    CancellationCaseRow,
    PolicyNoticeRow,
    SessionPlanRow,
    WaitlistEntryRow,
)
from b_k06_policy import iso, latest_policy, policy_of
from bookings import customer_for, seats_taken
from common import Now, Session, ShortText, invalid_transition, required_text
from contracts import ApiModel, ApiRequest
from display import SEOUL, clock, day_start, local, next_day_start, won
from models import BookingRow, ClassSessionRow, CustomerRow

router = APIRouter()
HORIZON = timedelta(days=14)
EVENING = time(18)
type Attendance = Literal["arrived", "no_show"]
type Waiting = Literal["waitlist", "makeup"]
type SessionDecision = Literal["run", "merge", "cancel"]
WAITING: TypeAdapter[Waiting] = TypeAdapter(Waiting)
type SessionSeats = tuple[ClassSessionRow, int]


class AttendanceRequest(ApiRequest):
    """Whether the guest came."""

    status: Attendance


class AttendanceView(ApiModel):
    """The recorded mark, and wording for a no-show."""

    attended_at: str | None
    no_show_at: str | None
    card_id: str
    draft: str | None = None


class LateCard(ApiModel):
    """A guest without an attendance mark after the grace time."""

    booking_id: str
    customer_name: str
    phone: str | None
    class_title: str
    starts_at: str
    minutes_late: int
    draft: str


class Reminder(ApiModel):
    """A local notification the app schedules."""

    booking_id: str
    customer_name: str
    fire_at: str


class RefillCard(ApiModel):
    """A class with seats a cancellation freed."""

    session_id: str
    class_title: str
    starts_at: str
    open_seats: int
    target_count: int
    expired: bool


class MergeOption(ApiModel):
    """Another class of the same week that can take every guest."""

    session_id: str
    class_title: str
    starts_at: str
    open_seats: int


class UnderMinCard(ApiModel):
    """A class below its smallest size before its material deadline."""

    session_id: str
    class_name: str
    starts_at: str
    revision: int
    booked: int
    min_seats: int
    order_deadline: str
    material_won: int | None
    merge_candidates: list[MergeOption]


class SessionLine(ApiModel):
    """A coming class whose guests can be checked."""

    session_id: str
    class_title: str
    starts_at: str
    schedule: str
    booked: int
    capacity: int


class Cards(ApiModel):
    """Everything the 오늘 tab shows for this feature."""

    policy_version: int | None
    late: list[LateCard]
    refill: list[RefillCard]
    under_min: list[UnderMinCard]
    reminders: list[Reminder]
    sessions: list[SessionLine]


class Guest(ApiModel):
    """One booking inside a class."""

    booking_id: str
    customer_name: str
    people: int
    attended_at: str | None
    no_show_at: str | None
    noticed: bool


class RefillTarget(ApiModel):
    """A person the owner may offer a seat to, in order."""

    entry_id: str
    customer_id: str
    name: str
    source: Waiting
    rank: int
    last_contact_at: str | None
    draft: str


class Refill(ApiModel):
    """Free seats of a class and who to offer them to."""

    session_id: str
    class_title: str
    starts_at: str
    starts_in_minutes: int
    open_seats: int
    targets: list[RefillTarget]


class SessionDetail(ApiModel):
    """A class with its guests, waiting people, and plan."""

    session_id: str
    class_title: str
    starts_at: str
    schedule: str
    capacity: int
    booked: int
    min_seats: int | None
    material_order_deadline: str | None
    material_won: int | None
    guests: list[Guest]
    targets: list[RefillTarget]


class PlanRequest(ApiRequest):
    """The smallest class size and its material deadline and cost per person."""

    min_seats: Annotated[int, Field(ge=1, le=100)] | None
    material_order_deadline: Annotated[AwareDatetime, Field(strict=False)] | None
    material_won: Annotated[int, Field(ge=0, le=10_000_000)] | None


class WaitlistRequest(ApiRequest):
    """A person who asked for a seat or is owed a make-up class."""

    customer_name: ShortText
    phone: Annotated[str, Field(max_length=40)] = ""
    source: Waiting


class UnderMinRequest(ApiRequest):
    """The owner's choice for an under-filled class."""

    decision: SessionDecision
    merge_into: ShortText | None = None
    expected_revision: Annotated[int, Field(ge=0)]


class GuestDraft(ApiModel):
    """A message for one guest."""

    booking_id: str
    customer_name: str
    draft: str


class UnderMinResult(ApiModel):
    """Messages the owner may copy, one per guest."""

    drafts: list[GuestDraft]


async def scheduled(db: AsyncSession, begin: datetime, end: datetime) -> list[SessionSeats]:
    """Read scheduled classes of a window with their taken seats."""
    rows = await db.execute(
        select(ClassSessionRow, seats_taken())
        .where(
            ClassSessionRow.status == "scheduled", ClassSessionRow.starts_at >= begin,
            ClassSessionRow.starts_at < end,
        ).order_by(ClassSessionRow.starts_at, ClassSessionRow.id),
    )
    return list(rows.tuples())


def alert_at(deadline: datetime) -> datetime:
    """Show an under-filled class from the evening before its material deadline."""
    eve = local(deadline).date() - timedelta(days=1)
    return datetime.combine(eve, EVENING, SEOUL)


async def merge_options(
    db: AsyncSession, session: ClassSessionRow, booked: int, now: datetime,
) -> list[MergeOption]:
    """Find other classes of the same title and week with room for every guest."""
    day = local(session.starts_at).date()
    monday = day - timedelta(days=day.weekday())
    week = await scheduled(db, max(day_start(monday), now), day_start(monday + timedelta(days=7)))
    return [
        MergeOption(
            session_id=other.id, class_title=other.title, starts_at=iso(other.starts_at),
            open_seats=other.capacity - taken,
        )
        for other, taken in week
        if other.id != session.id and other.title == session.title and other.capacity - taken >= booked
    ]


async def under_min_cards(db: AsyncSession, now: datetime) -> list[UnderMinCard]:
    """List undecided classes below their smallest size whose deadline is near."""
    decided = select(CancellationCaseRow.session_id).where(
        CancellationCaseRow.kind == "under_min", CancellationCaseRow.decision == "run",
    )
    rows = await db.execute(
        select(ClassSessionRow, seats_taken(), SessionPlanRow)
        .join(SessionPlanRow, SessionPlanRow.session_id == ClassSessionRow.id)
        .where(
            ClassSessionRow.status == "scheduled", ClassSessionRow.starts_at > now,
            SessionPlanRow.material_order_deadline > now, ClassSessionRow.id.not_in(decided),
        ).order_by(SessionPlanRow.material_order_deadline),
    )
    return [
        UnderMinCard(
            session_id=session.id, class_name=session.title, starts_at=iso(session.starts_at),
            revision=session.revision, booked=booked, min_seats=plan.min_seats,
            order_deadline=iso(plan.material_order_deadline),
            material_won=plan.material_won * booked if plan.material_won is not None else None,
            merge_candidates=await merge_options(db, session, booked, now),
        )
        for session, booked, plan in rows.tuples().all()
        if plan.min_seats is not None and plan.material_order_deadline is not None
        and booked < plan.min_seats and now >= alert_at(plan.material_order_deadline)
    ]


async def refill_cards(db: AsyncSession, now: datetime) -> list[RefillCard]:
    """List classes of this fortnight where a cancellation left a free seat."""
    freed = (
        select(BookingRow.session_id).join(BookingMarkRow, BookingMarkRow.booking_id == BookingRow.id)
        .where(BookingMarkRow.cancelled_at.is_not(None))
    )
    counts = dict(
        (await db.execute(
            select(WaitlistEntryRow.class_session_id, func.count())
            .group_by(WaitlistEntryRow.class_session_id),
        )).tuples().all(),
    )
    sessions = await scheduled(db, day_start(now.date()), now + HORIZON)
    freed_ids = set(await db.scalars(freed))
    return [
        RefillCard(
            session_id=session.id, class_title=session.title, starts_at=iso(session.starts_at),
            open_seats=session.capacity - taken, target_count=counts.get(session.id, 0),
            expired=session.starts_at <= now,
        )
        for session, taken in sessions if session.id in freed_ids and taken < session.capacity
    ]


async def unmarked(db: AsyncSession, begin: datetime, end: datetime) -> list[BookingParts]:
    """Read active bookings of a window without an attendance mark."""
    rows = await db.execute(
        booking_parts().outerjoin(BookingMarkRow, BookingMarkRow.booking_id == BookingRow.id).where(
            BookingRow.status != "cancelled", ClassSessionRow.status == "scheduled",
            ClassSessionRow.starts_at >= begin, ClassSessionRow.starts_at < end,
            BookingMarkRow.attended_at.is_(None), BookingMarkRow.no_show_at.is_(None),
        ).order_by(ClassSessionRow.starts_at, BookingRow.id),
    )
    return list(rows.tuples())


def late_draft(name: str, session: ClassSessionRow) -> str:
    """Ask a late guest whether they are coming."""
    return (
        f"{name} 님, {clock(session.starts_at)} {session.title} 수업을 시작했어요. "
        "오고 계시면 도착 시간을 알려 주세요."
    )


def no_show_draft(name: str, session: ClassSessionRow, late: LateRule | None) -> str:
    """Tell an absent guest how the owner's rule reads; without a rule nothing about the deposit is said."""
    opening = f"{name} 님, 오늘 {clock(session.starts_at)} {session.title} 수업에서 뵙지 못했어요."
    if late is None:
        return f"{opening} 다시 오고 싶으시면 편한 날짜를 알려 주세요."
    quoted = f"공방 규정에는 '{late.note}'라고 안내하고 있어요." if late.note else (
        f"공방 규정에는 {late.late_minutes}분 넘게 늦으면 노쇼로 본다고 안내하고 있어요."
    )
    return f"{opening} {quoted} 예약금은 이 규정대로 처리할게요. 다시 오고 싶으시면 편한 날짜를 알려 주세요."


@router.get("/k06/cards")
async def cards(
    db: Session, now: Now, at: Annotated[AwareDatetime | None, Query()] = None,
) -> Cards:
    """Build the 오늘 cards; `at` moves only this read-only view's clock, for demos and screenshots."""
    moment = local(at) if at is not None else now
    policy = await latest_policy(db)
    late = policy_of(policy).late if policy else None
    grace = timedelta(minutes=late.late_minutes if late else DEFAULT_LATE_MINUTES)
    today = await unmarked(db, day_start(moment.date()), next_day_start(moment.date()))
    soon = await unmarked(db, moment - grace, moment + HORIZON)
    sessions = await scheduled(db, day_start(moment.date()), moment + HORIZON)
    return Cards(
        policy_version=policy.version if policy else None,
        late=[
            LateCard(
                booking_id=booking.id, customer_name=customer.name, phone=customer.phone,
                class_title=session.title, starts_at=iso(session.starts_at),
                minutes_late=int((moment - session.starts_at).total_seconds() // 60),
                draft=late_draft(customer.name, session),
            )
            for booking, session, customer in today if session.starts_at + grace <= moment
        ],
        refill=await refill_cards(db, moment), under_min=await under_min_cards(db, moment),
        reminders=[
            Reminder(
                booking_id=booking.id, customer_name=customer.name, fire_at=iso(session.starts_at + grace),
            )
            for booking, session, customer in soon if session.starts_at + grace > moment
        ],
        sessions=[
            SessionLine(
                session_id=session.id, class_title=session.title, starts_at=iso(session.starts_at),
                schedule=when_text(session.starts_at), booked=taken, capacity=session.capacity,
            )
            for session, taken in sessions
        ],
    )


async def no_show_case(db: AsyncSession, booking_id: str) -> CancellationCaseRow | None:
    """Read a booking's no-show record."""
    return await db.scalar(
        select(CancellationCaseRow).where(
            CancellationCaseRow.booking_id == booking_id, CancellationCaseRow.kind == "no_show",
        ),
    )


@router.post("/bookings/{booking_id}/attendance")
async def set_attendance(
    booking_id: str, body: AttendanceRequest, db: Session, now: Now,
) -> AttendanceView:
    """Mark a guest as arrived or absent; an absence also becomes a record of this workshop only."""
    booking, session, customer = await one_booking(db, booking_id, lock=True)
    mark = await mark_for(db, booking.id)
    if booking.status == "cancelled" or mark.attended_at is not None or mark.no_show_at is not None:
        raise invalid_transition()
    if body.status == "arrived":
        mark.attended_at = now
        await db.flush()
        return AttendanceView(attended_at=iso(now), no_show_at=None, card_id=booking.id)
    if session.starts_at > now:
        raise invalid_transition()
    policy = await latest_policy(db)
    late = policy_of(policy).late if policy else None
    draft = no_show_draft(customer.name, session, late)
    mark.no_show_at = now
    record = CancellationCaseRow(
        id=f"case-{uuid4().hex}", workshop_id=WORKSHOP_ID, booking_id=booking.id, session_id=session.id,
        kind="no_show", policy_version_id=policy.id if policy else None,
        computed=Computed(
            days_left=0, paid=paid_won(booking), refund=None, version=policy.version if policy else None,
            noticed_on=None, prior_status=booking.status,
        ).model_dump(mode="json"),
        decision=None, reason="", draft=draft, decided_at=now,
    )
    db.add(record)
    await db.flush()
    return AttendanceView(attended_at=None, no_show_at=iso(now), card_id=record.id, draft=draft)


@router.post("/bookings/{booking_id}/undo-attendance")
async def undo_attendance(booking_id: str, db: Session) -> AttendanceView:
    """Clear a mark and the absence it recorded."""
    booking, _, _ = await one_booking(db, booking_id, lock=True)
    mark = await mark_for(db, booking.id)
    if mark.attended_at is None and mark.no_show_at is None:
        raise invalid_transition()
    mark.attended_at = None
    mark.no_show_at = None
    record = await no_show_case(db, booking.id)
    if record is not None:
        await db.delete(record)
    await db.flush()
    return AttendanceView(attended_at=None, no_show_at=None, card_id=booking.id)


async def session_seats(db: AsyncSession, session_id: str) -> SessionSeats:
    """Read one class and its taken seats."""
    row = (
        await db.execute(select(ClassSessionRow, seats_taken()).where(ClassSessionRow.id == session_id))
    ).tuples().one_or_none()
    if row is None:
        raise HTTPException(404, "resource not found")
    return row


async def waiting(db: AsyncSession, session: ClassSessionRow) -> list[RefillTarget]:
    """List who to offer a seat to: requests first, then make-up classes, each by rank."""
    last = (
        select(func.max(BookingRow.created_at)).where(BookingRow.customer_id == CustomerRow.id)
        .correlate(CustomerRow).scalar_subquery()
    )
    rows = await db.execute(
        select(WaitlistEntryRow, CustomerRow.name, last)
        .join(CustomerRow, CustomerRow.id == WaitlistEntryRow.customer_id)
        .where(WaitlistEntryRow.class_session_id == session.id)
        .order_by(sql_case((WaitlistEntryRow.source == "waitlist", 0), else_=1), WaitlistEntryRow.rank),
    )
    return [
        RefillTarget(
            entry_id=entry.id, customer_id=entry.customer_id, name=name,
            source=WAITING.validate_python(entry.source), rank=entry.rank,
            last_contact_at=iso(at) if at else None,
            draft=(
                f"{name} 님, {when_text(session.starts_at)} {session.title} 수업에 자리가 났어요. "
                "오실 수 있으면 답장 주세요. 자리를 잡아 둘게요."
            ),
        )
        for entry, name, at in rows.tuples()
    ]


@router.get("/class-sessions/under-min")
async def under_min(db: Session, now: Now) -> list[UnderMinCard]:
    """List under-filled classes whose material deadline is near."""
    return await under_min_cards(db, now)


@router.get("/class-sessions/{session_id}/refill")
async def refill(session_id: str, db: Session, now: Now) -> Refill:
    """Read free seats and who asked for one."""
    session, taken = await session_seats(db, session_id)
    return Refill(
        session_id=session.id, class_title=session.title, starts_at=iso(session.starts_at),
        starts_in_minutes=int((session.starts_at - now).total_seconds() // 60),
        open_seats=max(session.capacity - taken, 0), targets=await waiting(db, session),
    )


@router.get("/class-sessions/{session_id}/k06")
async def session_detail(session_id: str, db: Session) -> SessionDetail:
    """Read a class's guests, waiting people, and plan."""
    session, taken = await session_seats(db, session_id)
    plan = await db.get(SessionPlanRow, session_id)
    noticed = set(await db.scalars(select(PolicyNoticeRow.booking_id)))
    rows = await db.execute(
        select(BookingRow, CustomerRow.name, BookingMarkRow)
        .join(CustomerRow, CustomerRow.id == BookingRow.customer_id)
        .outerjoin(BookingMarkRow, BookingMarkRow.booking_id == BookingRow.id)
        .where(BookingRow.session_id == session_id, BookingRow.status != "cancelled")
        .order_by(BookingRow.created_at, BookingRow.id),
    )
    guests = [
        Guest(
            booking_id=booking.id, customer_name=name, people=booking.party_size,
            attended_at=iso(mark.attended_at) if mark and mark.attended_at else None,
            no_show_at=iso(mark.no_show_at) if mark and mark.no_show_at else None,
            noticed=booking.id in noticed,
        )
        for booking, name, mark in rows.tuples()
    ]
    deadline = plan.material_order_deadline if plan else None
    return SessionDetail(
        session_id=session.id, class_title=session.title, starts_at=iso(session.starts_at),
        schedule=when_text(session.starts_at), capacity=session.capacity, booked=taken,
        min_seats=plan.min_seats if plan else None,
        material_order_deadline=iso(deadline) if deadline else None,
        material_won=plan.material_won if plan else None, guests=guests,
        targets=await waiting(db, session),
    )


@router.put("/class-sessions/{session_id}/plan")
async def save_plan(session_id: str, body: PlanRequest, db: Session) -> SessionDetail:
    """Save the smallest class size and the material deadline and cost."""
    _ = await session_seats(db, session_id)
    plan = await db.get(SessionPlanRow, session_id)
    if plan is None:
        plan = SessionPlanRow(session_id=session_id)
        db.add(plan)
    plan.min_seats = body.min_seats
    plan.material_order_deadline = body.material_order_deadline
    plan.material_won = body.material_won
    await db.flush()
    return await session_detail(session_id, db)


@router.post("/class-sessions/{session_id}/waitlist", status_code=201)
async def add_waiting(session_id: str, body: WaitlistRequest, db: Session) -> SessionDetail:
    """Add a person who asked, after everyone already waiting."""
    session = await db.scalar(
        select(ClassSessionRow).where(ClassSessionRow.id == session_id).with_for_update(),
    )
    if session is None:
        raise HTTPException(404, "resource not found")
    customer_id = await customer_for(db, required_text(body.customer_name), body.phone.strip() or None)
    last = await db.scalar(
        select(func.max(WaitlistEntryRow.rank)).where(WaitlistEntryRow.class_session_id == session_id),
    ) or 0
    db.add(WaitlistEntryRow(
        id=f"waitlist-{uuid4().hex}", class_session_id=session_id, customer_id=customer_id,
        source=body.source, rank=last + 1,
    ))
    await db.flush()
    return await session_detail(session_id, db)


@router.delete("/class-sessions/{session_id}/waitlist/{entry_id}")
async def remove_waiting(session_id: str, entry_id: str, db: Session) -> Removed:
    """Remove a waiting person."""
    entry = await db.get(WaitlistEntryRow, entry_id)
    if entry is None or entry.class_session_id != session_id:
        raise HTTPException(404, "resource not found")
    await db.delete(entry)
    return Removed(removed=1)


def guest_message(
    name: str, session: ClassSessionRow, decision: SessionDecision, detail: str,
) -> str:
    """Word the message for one guest of an under-filled class."""
    when = f"{when_text(session.starts_at)} {session.title}"
    match decision:
        case "run":
            return f"{name} 님, {when} 수업은 예정대로 진행해요. 그날 뵐게요."
        case "merge":
            return (
                f"{name} 님, {when} 수업은 신청 인원이 적어 {detail} 수업과 합치려고 해요. "
                "이 시간도 괜찮으신지 알려 주세요. 어려우시면 예약금을 모두 돌려드릴게요."
            )
        case "cancel":
            return (
                f"{name} 님, {when} 수업은 신청 인원이 적어 열지 못하게 됐어요. 죄송해요. {detail}"
            )


async def lock_sessions(db: AsyncSession, ids: list[str]) -> dict[str, ClassSessionRow]:
    """Lock classes in one order so two decisions cannot wait on each other."""
    rows = await db.scalars(
        select(ClassSessionRow).where(ClassSessionRow.id.in_(ids)).order_by(ClassSessionRow.id)
        .with_for_update(),
    )
    return {row.id: row for row in rows}


async def merge_target(
    db: AsyncSession, session: ClassSessionRow, target: ClassSessionRow | None, booked: int, now: datetime,
) -> ClassSessionRow:
    """Count the target's free seats again under its lock."""
    options = {option.session_id for option in await merge_options(db, session, booked, now)}
    if target is None or target.id not in options:
        raise HTTPException(409, "class does not have enough seats")
    return target


def settle_guest(
    db: AsyncSession, parts: BookingParts, decision: SessionDecision, target: ClassSessionRow | None,
    now: datetime,
) -> GuestDraft:
    """Move or cancel one guest's booking, record it, and word the message."""
    booking, session, customer = parts
    paid = paid_won(booking)
    detail = when_text(target.starts_at) if target else (
        f"예약금 {won(paid)}은 모두 돌려드릴게요. 계좌를 알려 주세요." if paid else ""
    )
    text = guest_message(customer.name, session, decision, detail).strip()
    db.add(CancellationCaseRow(
        id=f"case-{uuid4().hex}", workshop_id=WORKSHOP_ID, booking_id=booking.id,
        session_id=session.id, kind="under_min",
        computed=Computed(
            days_left=days_left(session.starts_at, now), paid=paid, refund=None,
            version=None, noticed_on=None, prior_status=booking.status,
        ).model_dump(mode="json"),
        decision=decision, reason="", draft=text, decided_at=now,
        decided_won=paid if decision == "cancel" else None,
    ))
    if target is not None:
        booking.session_id = target.id
    elif decision == "cancel":
        booking.status = "cancelled"
    if decision != "run":
        booking.revision += 1
    return GuestDraft(booking_id=booking.id, customer_name=customer.name, draft=text)


@router.post("/class-sessions/{session_id}/under-min-decision")
async def decide_under_min(
    session_id: str, body: UnderMinRequest, db: Session, now: Now,
) -> UnderMinResult:
    """Run, merge, or cancel an under-filled class and word one message per guest."""
    if (body.decision == "merge") != (body.merge_into is not None):
        raise HTTPException(422, "merge_into goes with merge")
    locked = await lock_sessions(db, [session_id, *([body.merge_into] if body.merge_into else [])])
    session = locked.get(session_id)
    if session is None:
        raise HTTPException(404, "resource not found")
    if session.revision != body.expected_revision:
        raise HTTPException(409, "revision is stale")
    if session.status != "scheduled" or session.starts_at <= now:
        raise invalid_transition()
    rows = (await db.execute(
        booking_parts().where(BookingRow.session_id == session_id, BookingRow.status != "cancelled")
        .order_by(BookingRow.id).with_for_update(of=BookingRow),
    )).tuples().all()
    booked = sum(booking.party_size for booking, _, _ in rows)
    target = (
        await merge_target(db, session, locked.get(body.merge_into), booked, now) if body.merge_into else None
    )
    drafts = [settle_guest(db, parts, body.decision, target, now) for parts in rows]
    if not rows:
        db.add(CancellationCaseRow(
            id=f"case-{uuid4().hex}", workshop_id=WORKSHOP_ID, booking_id=None, session_id=session.id,
            kind="under_min", computed={}, decision=body.decision, reason="", draft="", decided_at=now,
        ))
    if body.decision != "run":
        session.status = "cancelled"
    session.revision += 1
    await db.flush()
    return UnderMinResult(drafts=drafts)
