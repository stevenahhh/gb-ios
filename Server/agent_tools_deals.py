"""Deposit, booking, cancellation, and quote tools (T2); each needs the owner's current words."""

import re
import unicodedata
from datetime import datetime
from typing import Annotated, Final

from pydantic import Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_policy import numbers_in
from agent_text import compact, dates_named, mentions, sentences
from agent_toolkit import (
    Definition,
    Located,
    RevisionConflictError,
    ToolArgs,
    build,
    local_clock,
    local_date,
    lock_row,
    name_confidence,
)
from agent_tools_orders import Match, claims_for, found_one
from agent_types import (
    BY_FULL_NAME,
    BY_IDENTIFIER,
    Check,
    Claim,
    Outcome,
    Resolution,
    TargetRef,
    Tool,
    ToolEnv,
    UndoInput,
    UndoTicket,
)
from b_k06_models import BookingMarkRow, CancellationCaseRow, PolicyNoticeRow, WaitlistEntryRow
from bookings import BookingCreate, booking_records, confirm_paid, reserve_seats, schedule_text
from display import local, masked, won
from models import BookingRow, ClassSessionRow, CustomerRow, InquiryRow, OrderRow
from undo import reopen_deposit

type Reference = Annotated[str, Field(min_length=1, max_length=200)]


DEPOSIT_WORDS: Final = (
    "입금됐|입금했|입금하셨|입금되었|입금 완료|입금 확인됐|입금 확인했|"
    "들어왔|송금했|송금됐|송금하셨|보냈|받았|넣었"
)


BOOK_WORDS: Final = "예약|등록|잡아|신청|추가"
PAID_WORDS: Final = re.compile(DEPOSIT_WORDS.replace(" ", r"\s*"))
NOT_PAID: Final = re.compile(
    (
        r"안내|문구|문자|환불|돌려|되돌|미입금|취소|절반|일부|반만|확인\s*중|[왔했냈됐었갔렸]대(?:요)?(?=[\s,.!?~]|$)|"
        r"(?<![나저])(?:한테|에게|께)(?!서)[^.!?\n]*(?:보냈|송금|입금|드렸)"
    ),
)
NOT_NEW: Final = re.compile(
    r"취소|변경|바꿔|바꾸|옮겨|옮기|미뤄|빼|(?:예약|등록|신청)[가-힣]?\s*(?:돼|되어)?\s*있",
)
SMALLEST_BARE_WON: Final = 10_000


class DepositArgs(ToolArgs):
    """A deposit that arrived."""

    booking: Reference = Field(description="예약한 손님 이름이나 수업 이름")


def booking_label(record_customer: str, session: ClassSessionRow, party_size: int) -> str:
    """Describe a booking with the name masked."""
    return f"{masked(record_customer)} {party_size}명 · {session.title} · {schedule_text(session)}"


def deposit_amounts(env: ToolEnv) -> set[int]:
    """Read the amounts the owner stated this turn, in won; a large number without a unit is one too."""
    turn = unicodedata.normalize("NFKC", env.turn or "")
    return {found.value for found in mentions(turn) if found.unit == "money"} | {
        found.value
        for found in numbers_in(turn, local(env.now).date())
        if not found.unit and found.value >= SMALLEST_BARE_WON
    }


def deposit_checks(env: ToolEnv, name: str, expected: int) -> tuple[Check, ...]:
    """Require the stated amount to be the deposit, and the payment to be this customer's and complete."""
    turn = env.turn or ""
    paid = any(
        compact(name) in compact(sentence) and PAID_WORDS.search(sentence) is not None
        for sentence in sentences(turn)
    )
    return (
        Check(f"예약금 {won(expected)} 금액", passed=deposit_amounts(env) <= {expected}),
        Check("입금 여부", passed=paid and NOT_PAID.search(turn) is None),
    )


async def locate_deposit(db: AsyncSession, args: DepositArgs, env: ToolEnv) -> Located:
    """Find the booking that waits for its deposit; an amount the owner stated must be its deposit."""
    records = (
        await db.execute(
            booking_records()
            .where(BookingRow.status == "deposit_pending")
            .order_by(BookingRow.deposit_due_at),
        )
    ).tuples()
    matches: list[Match] = []
    deposits: dict[str, int] = {}
    for booking, session, customer, _ in records:
        for label, value in (("손님", customer.name), ("수업", session.title)):
            score = name_confidence(args.booking, value)
            if score is not None:
                claim = Claim(label, value if score >= BY_FULL_NAME else args.booking, "text")
                matches.append(
                    Match(
                        TargetRef(
                            "booking",
                            booking.id,
                            booking_label(customer.name, session, booking.party_size),
                            booking.revision,
                        ),
                        score,
                        claim,
                    ),
                )
                deposits[booking.id] = booking.deposit_won
                break
    preview: tuple[tuple[str, str], ...] = ()
    checks: tuple[Check, ...] = ()
    if len(matches) == 1:
        expected = deposits[matches[0].target.id]
        other = sorted(deposit_amounts(env) - {expected})
        checks = deposit_checks(env, matches[0].claim.value, expected)
        preview = (
            ("할 일", "예약금 입금 확인"),
            ("예약", matches[0].target.label),
            ("예약금", won(expected)),
            *((("말씀하신 금액", ", ".join(won(amount) for amount in other)),) if other else ()),
        )
    located = found_one(matches, "예약금을 기다리는 예약에서 찾지 못했어요.")
    return Located(
        located.resolution,
        claims_for(matches, Claim("입금", DEPOSIT_WORDS, "words")),
        checks,
        preview,
    )


async def confirm_one_deposit(
    db: AsyncSession,
    args: DepositArgs,
    target: TargetRef,
    env: ToolEnv,
) -> Outcome:
    """Confirm one pending booking."""
    del args
    booking = await lock_row(db, BookingRow, target.id, target.revision)
    confirm_paid(booking, env.now)
    await db.flush()
    return Outcome(
        f"예약금을 확인했어요: {target.label}",
        TargetRef("booking", booking.id, target.label, booking.revision),
        UndoTicket(f"/bookings/{booking.id}/undo-deposit"),
    )


async def undo_deposit(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Return a booking to waiting for its deposit."""
    booking = await lock_row(db, BookingRow, undo.target.id, undo.target.revision)
    await reopen_deposit(db, booking, undo.now)
    await db.flush()
    return Outcome("예약금 확인을 되돌렸어요.")


class BookArgs(ToolArgs):
    """A booking to make."""

    session: Reference = Field(description="수업 이름")
    day: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="수업 날짜 YYYY-MM-DD")] = (
        None
    )
    time: Annotated[str | None, Field(pattern=r"^\d{2}:\d{2}$", description="수업 시작 시각 HH:MM")] = None
    customer_name: Reference = Field(description="예약하는 손님 이름")
    party_size: Annotated[int, Field(ge=1, le=50, description="인원")]


async def open_sessions(db: AsyncSession, now: datetime) -> list[ClassSessionRow]:
    """Read future classes that can still take a booking."""
    rows = await db.scalars(
        select(ClassSessionRow)
        .where(
            ClassSessionRow.status == "scheduled",
            ClassSessionRow.starts_at > now,
        )
        .order_by(ClassSessionRow.starts_at),
    )
    return list(rows)


def session_fits(session: ClassSessionRow, args: BookArgs) -> bool:
    """Tell whether a class matches the day and time the call gave."""
    moment = local(session.starts_at)
    day = local_date(args.day) if args.day else None
    clock = local_clock(args.time) if args.time else None
    return (day is None or moment.date() == day.date()) and (clock is None or moment.time() == clock)


async def locate_session(db: AsyncSession, args: BookArgs, env: ToolEnv) -> Located:
    """Find the one class the booking is for."""
    matches = [
        (session, score)
        for session in await open_sessions(db, env.now)
        if (score := name_confidence(args.session, session.title)) is not None and session_fits(session, args)
    ]
    candidates = tuple(
        TargetRef("session", session.id, f"{session.title} · {schedule_text(session)}", session.revision)
        for session, _ in matches
    )
    claims: list[Claim] = []
    if len(matches) == 1:
        session, score = matches[0]
        claims.append(Claim("수업", session.title if score >= BY_FULL_NAME else args.session, "text"))
        preview = (
            ("할 일", "예약 만들기"),
            ("수업", candidates[0].label),
            ("손님", masked(args.customer_name)),
            ("인원", f"{args.party_size}명"),
        )
        named = {day for day, *_ in dates_named(env.turn or "", local(env.now).date())}
        people = {found.value for found in mentions(env.turn or "") if found.unit == "people"}
        checks = (
            Check("수업 날짜", passed=not named or local(session.starts_at).date() in named),
            Check("인원", passed=people <= {args.party_size}),
            Check("새 예약 여부", passed=NOT_NEW.search(env.turn or "") is None),
        )
    else:
        preview = ()
        checks = ()
    if args.day:
        claims.append(Claim("날짜", args.day, "date"))
    if args.time:
        claims.append(Claim("시간", args.time, "time"))
    claims += [
        Claim("손님", args.customer_name, "text"),
        Claim("인원", str(args.party_size), "number"),
        Claim("예약", BOOK_WORDS, "words"),
    ]
    confidence = max((score for _, score in matches), default=BY_IDENTIFIER)
    return Located(
        Resolution(candidates, confidence, "앞으로 열리는 수업 중에서 찾지 못했어요."),
        tuple(claims),
        checks,
        preview,
    )


async def book(db: AsyncSession, args: BookArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Reserve seats for the customer the owner named."""
    session = await lock_row(db, ClassSessionRow, target.id, target.revision)
    known = await db.scalar(
        select(CustomerRow.id)
        .where(CustomerRow.name == args.customer_name, CustomerRow.phone.is_(None))
        .limit(1),
    )
    booking = await reserve_seats(
        db,
        BookingCreate(
            session_id=session.id,
            customer_name=args.customer_name,
            party_size=args.party_size,
        ),
        env.now,
    )
    label = booking_label(args.customer_name, session, booking.party_size)
    return Outcome(
        f"예약을 만들었어요: {label}",
        TargetRef("booking", booking.id, label, booking.revision),
        UndoTicket("/agent/undo/create_booking", {"customer_id": None if known else booking.customer_id}),
    )


async def has_later_records(db: AsyncSession, booking_id: str) -> bool:
    """Tell whether the owner recorded something on a booking; its revision does not move for these."""
    marked = or_(BookingMarkRow.attended_at.is_not(None), BookingMarkRow.no_show_at.is_not(None))
    return bool(
        await db.scalar(
            select(
                or_(
                    select(PolicyNoticeRow.id).where(PolicyNoticeRow.booking_id == booking_id).exists(),
                    select(CancellationCaseRow.id)
                    .where(CancellationCaseRow.booking_id == booking_id)
                    .exists(),
                    select(BookingMarkRow.booking_id)
                    .where(BookingMarkRow.booking_id == booking_id, marked)
                    .exists(),
                ),
            ),
        ),
    )


async def remove_booking(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Take back a booking the assistant made, and the customer row made for it when nothing else uses it."""
    booking = await lock_row(db, BookingRow, undo.target.id, undo.target.revision)
    if await has_later_records(db, booking.id):
        raise RevisionConflictError
    await db.delete(booking)
    await db.flush()
    _ = await db.execute(
        delete(CustomerRow).where(
            CustomerRow.id == undo.data.get("customer_id"),
            *(
                ~select(row.id).where(row.customer_id == CustomerRow.id).exists()
                for row in (BookingRow, OrderRow, InquiryRow, WaitlistEntryRow)
            ),
        ),
    )
    return Outcome("만든 예약을 지웠어요.")


DEALS: Final[tuple[Tool, ...]] = (
    build(
        Definition(
            "confirm_deposit",
            "T2",
            "propose",
            "예약금 확인",
            "입금된 예약금을 확인해 예약을 확정합니다.",
            DepositArgs,
            locate_deposit,
            confirm_one_deposit,
            undo_deposit,
        ),
    ),
    build(
        Definition(
            "create_booking",
            "T2",
            "propose",
            "예약 만들기",
            "수업 자리를 손님 이름으로 예약합니다.",
            BookArgs,
            locate_session,
            book,
            remove_booking,
        ),
    ),
)
