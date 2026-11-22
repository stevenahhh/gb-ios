"""Outreach quote judge (K14): cost cards, extraction, quotes, and recorded outcomes."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Final, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, Field, TypeAdapter, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k14_calc import (
    Calculation,
    CostCard,
    Inputs,
    Rates,
    Scenario,
    SeatHistory,
    TravelMode,
    calculate,
    missing_costs,
)
from b_k14_extract import (
    SIGNAL_CODES,
    ContactKind,
    Extraction,
    OrgType,
    SignalCode,
    extract,
    is_locked,
    parse_date,
    scrub,
    with_server_signals,
)
from b_k14_models import ClassCostRow, OutreachDefaultsRow, OutreachQuoteRow
from common import Now, Session
from contracts import ApiModel, ApiRequest, CardDue
from display import SEOUL, day_start, due, local, month_day_weekday, next_day_start, won
from models import BookingRow, ClassSessionRow, TaskRow, WorkshopRow

MAX_INQUIRY: Final = 2000
SEAT_WINDOW: Final = timedelta(days=90)
UPCOMING_WINDOW: Final = timedelta(days=30)
CHANGE_NOTICE: Final = timedelta(days=7)
FOLLOW_UP_DAYS: Final = 3
FRIDAY: Final = 4
MAX_WON: Final = 1_000_000_000
router = APIRouter()
type Won = Annotated[int, Field(ge=0, le=MAX_WON)]
type Minutes = Annotated[int, Field(ge=0, le=1440)]
type Outcome = Literal["accepted", "accepted_adjusted", "declined", "no_reply"]
type QuoteStatus = Literal[
    "draft", "sent", "follow_up", "accepted", "accepted_adjusted", "declined", "no_reply",
]
OUTCOMES: Final[TypeAdapter[Outcome]] = TypeAdapter(Outcome)
STATUSES: Final[TypeAdapter[QuoteStatus]] = TypeAdapter(QuoteStatus)
type QuoteVat = Literal["included", "excluded", "exempt", "unknown"]


class ClassCost(ApiModel):
    """One class and its cost card; null costs mean the owner has not entered them."""

    class_id: str
    title: str
    class_minutes: int
    material_per_person_krw: int | None
    oneday_price_krw: int | None
    prep_minutes: int
    cleanup_minutes: int
    max_headcount: int


class OutreachDefaults(ApiModel):
    """The workshop's own outreach rates."""

    instructor_hourly_krw: int
    assistant_daily_krw: int
    travel_mode: TravelMode
    travel_per_km_krw: int
    travel_flat_krw: int
    minimum_fee_krw: int


class CostSettings(ApiModel):
    """The cost settings screen: every registered class plus the outreach rates."""

    classes: list[ClassCost]
    defaults: OutreachDefaults | None


class ClassCostUpdate(ApiRequest):
    """A cost card entered by the owner."""

    material_per_person_krw: Won
    oneday_price_krw: Annotated[int, Field(gt=0, le=MAX_WON)]
    prep_minutes: Minutes
    cleanup_minutes: Minutes
    max_headcount: Annotated[int, Field(ge=1, le=1000)]


class DefaultsUpdate(ApiRequest):
    """The outreach rates entered by the owner."""

    instructor_hourly_krw: Won
    assistant_daily_krw: Won
    travel_mode: TravelMode
    travel_per_km_krw: Won
    travel_flat_krw: Won
    minimum_fee_krw: Won


class ExtractRequest(ApiRequest):
    """The pasted inquiry; it is read once and never stored."""

    text: Annotated[str, Field(min_length=1, max_length=MAX_INQUIRY)]


type TimeRange = Annotated[
    str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$"),
]
type Label = Annotated[str, Field(max_length=200)]


class QuoteFields(ApiRequest):
    """Inquiry fields after the owner checked them."""

    org_type: OrgType = "unknown"
    org_name: Annotated[str, Field(max_length=80)] | None = None
    budget_krw: Annotated[int, Field(gt=0, le=MAX_WON)] | None = None
    budget_vat: QuoteVat = "unknown"
    date: str | None = None
    date_text: Label | None = None
    time_range: TimeRange | None = None
    location_text: Label | None = None
    class_hint: Label | None = None
    contact_kind: ContactKind = "unknown"

    @field_validator("date")
    @classmethod
    def real_date(cls, value: str | None) -> str | None:
        """Refuse text that is not a calendar date."""
        if value is not None and parse_date(value) is None:
            message = "date must be YYYY-MM-DD"
            raise ValueError(message)
        return value


class QuoteInputs(ApiRequest):
    """Numbers the calculation uses; the owner can change each of them later."""

    headcount: Annotated[int, Field(ge=1, le=1000)]
    per_person_krw: Annotated[int, Field(gt=0, le=MAX_WON)] | None = None
    assistants: Annotated[int, Field(ge=0, le=20)] = 0
    travel_minutes: Minutes | None = None
    distance_km: Annotated[int, Field(ge=0, le=1000)] | None = None


class QuoteCreate(QuoteInputs):
    """Confirmed fields, the chosen class, and the trial measurement."""

    fields: QuoteFields
    class_id: Annotated[str, Field(min_length=1, max_length=200)]
    signals: list[SignalCode] = Field(default=[], max_length=10)
    ab_arm: Literal["A", "B"] = "B"


class Recalculate(ApiRequest):
    """Only the values that changed; a value left out of the body keeps its stored number."""

    headcount: Annotated[int, Field(ge=1, le=1000)] = 1
    per_person_krw: Annotated[int, Field(gt=0, le=MAX_WON)] | None = None
    assistants: Annotated[int, Field(ge=0, le=20)] = 0
    travel_minutes: Minutes | None = None
    distance_km: Annotated[int, Field(ge=0, le=1000)] | None = None
    class_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class SentRequest(ApiRequest):
    """The owner shared the quote; an optional moment puts a reminder on 오늘."""

    elapsed_seconds: Annotated[int, Field(ge=0, le=86_400)] | None = None
    follow_up_at: Annotated[AwareDatetime, Field(strict=False)] | None = None


class OutcomeRequest(ApiRequest):
    """How the institution answered."""

    outcome: Outcome
    final_total_krw: Annotated[int, Field(gt=0, le=MAX_WON)] | None = None


class Conflict(ApiModel):
    """A class that day which the outreach would push out."""

    session_id: str
    title: str
    starts_at: str
    booked_count: int
    lost_krw: int | None


class QuoteView(ApiModel):
    """One quote as the detail screen shows it."""

    id: str
    status: QuoteStatus
    class_id: str
    fields: QuoteFields
    inputs: QuoteInputs
    signals: list[SignalCode]
    locked: bool
    org_verified_at: str | None
    calculation: Calculation
    missing_costs: list[str]
    conflicts: list[Conflict]
    summary: str
    reply_draft: str
    change_deadline: str | None
    follow_up_at: str
    follow_up_due: CardDue | None
    outcome: Outcome | None
    final_total_krw: int | None


class QuoteRowView(ApiModel):
    """One quote as the list shows it."""

    id: str
    status: QuoteStatus
    title: str
    detail: str
    total_krw: int
    follow_up_due: CardDue | None


class Verified(ApiModel):
    """The moment the owner confirmed the institution by its main number."""

    org_verified_at: str
    locked: bool


ORG_LABELS: Final[dict[str, str]] = {
    "school": "학교", "public": "공공기관", "company": "회사", "welfare": "복지기관", "other": "기관",
    "unknown": "기관",
}


async def known_classes(db: AsyncSession) -> dict[str, tuple[int, int]]:
    """Map each registered class title to its newest duration and capacity."""
    rows = await db.execute(
        select(ClassSessionRow.title, ClassSessionRow.duration_minutes, ClassSessionRow.capacity)
        .where(ClassSessionRow.status != "cancelled").order_by(ClassSessionRow.starts_at.desc()),
    )
    found: dict[str, tuple[int, int]] = {}
    for title, duration, capacity in rows.tuples():
        _ = found.setdefault(title, (duration, capacity))
    return found


async def cost_settings(db: AsyncSession) -> CostSettings:
    """Read the cost screen."""
    costs = {row.class_id: row for row in await db.scalars(select(ClassCostRow))}
    classes = [
        ClassCost(
            class_id=title, title=title, class_minutes=duration,
            material_per_person_krw=cost.material_per_person_krw if cost else None,
            oneday_price_krw=cost.oneday_price_krw if cost else None,
            prep_minutes=cost.prep_minutes if cost else 0,
            cleanup_minutes=cost.cleanup_minutes if cost else 0,
            max_headcount=cost.max_headcount if cost else capacity,
        )
        for title, (duration, capacity) in sorted((await known_classes(db)).items())
        for cost in (costs.get(title),)
    ]
    row = await db.get(OutreachDefaultsRow, 1)
    return CostSettings(
        classes=classes,
        defaults=OutreachDefaults.model_validate(row, from_attributes=True) if row else None,
    )


@router.get("/settings/class-costs")
async def list_class_costs(db: Session) -> CostSettings:
    """List registered classes with their cost cards, and the outreach rates."""
    return await cost_settings(db)


@router.put("/settings/class-costs/{class_id}")
async def save_class_cost(class_id: str, body: ClassCostUpdate, db: Session) -> CostSettings:
    """Save one class's cost card."""
    if class_id not in await known_classes(db):
        raise HTTPException(404, "class not found")
    row = await db.get(ClassCostRow, class_id, with_for_update=True)
    if row is None:
        row = ClassCostRow(class_id=class_id, revision=0)
        db.add(row)
    else:
        row.revision += 1
    row.material_per_person_krw = body.material_per_person_krw
    row.oneday_price_krw = body.oneday_price_krw
    row.prep_minutes = body.prep_minutes
    row.cleanup_minutes = body.cleanup_minutes
    row.max_headcount = body.max_headcount
    await db.flush()
    return await cost_settings(db)


@router.put("/settings/outreach-defaults")
async def save_outreach_defaults(body: DefaultsUpdate, db: Session) -> CostSettings:
    """Save the workshop's outreach rates."""
    row = await db.get(OutreachDefaultsRow, 1, with_for_update=True)
    if row is None:
        row = OutreachDefaultsRow(id=1, revision=0)
        db.add(row)
    else:
        row.revision += 1
    row.instructor_hourly_krw = body.instructor_hourly_krw
    row.assistant_daily_krw = body.assistant_daily_krw
    row.travel_mode = body.travel_mode
    row.travel_per_km_krw = body.travel_per_km_krw
    row.travel_flat_krw = body.travel_flat_krw
    row.minimum_fee_krw = body.minimum_fee_krw
    await db.flush()
    return await cost_settings(db)


@router.post("/outreach/extract")
async def extract_inquiry(body: ExtractRequest) -> Extraction:
    """Read the inquiry text; nothing is stored and a model failure still answers 200."""
    return await extract(body.text)


async def scenario_for(
    db: AsyncSession, class_id: str, inputs: QuoteInputs, fields: QuoteFields, now: datetime,
) -> tuple[Scenario, list[Conflict]]:
    """Read cost, rates, real bookings, and conflicts for one judgement."""
    classes = await known_classes(db)
    if class_id not in classes:
        raise HTTPException(404, "class not found")
    cost = await db.get(ClassCostRow, class_id)
    rates = await db.get(OutreachDefaultsRow, 1)
    card = CostCard(
        material_krw=cost.material_per_person_krw if cost else None,
        oneday_price_krw=cost.oneday_price_krw if cost else None,
        prep_minutes=cost.prep_minutes if cost else 0, cleanup_minutes=cost.cleanup_minutes if cost else 0,
        class_minutes=classes[class_id][0],
    )
    conflicts = await conflicts_on(db, fields, card, inputs.travel_minutes or 0)
    lost = sum(conflict.lost_krw or 0 for conflict in conflicts)
    return Scenario(
        inputs=Inputs(
            headcount=inputs.headcount, budget_krw=fields.budget_krw, per_person_krw=inputs.per_person_krw,
            assistants=inputs.assistants, travel_minutes=inputs.travel_minutes,
            distance_km=inputs.distance_km, lesson_minutes=span_minutes(fields.time_range),
        ),
        card=card,
        rates=Rates(
            instructor_hourly_krw=rates.instructor_hourly_krw if rates else None,
            assistant_daily_krw=rates.assistant_daily_krw if rates else 0,
            travel_mode="per_km" if rates and rates.travel_mode == "per_km" else "flat",
            travel_per_km_krw=rates.travel_per_km_krw if rates else 0,
            travel_flat_krw=rates.travel_flat_krw if rates else 0,
            minimum_fee_krw=rates.minimum_fee_krw if rates else 0,
        ),
        seats=await seat_history(db, class_id, now),
        lost_to_conflicts_krw=lost,
    ), conflicts


def span_minutes(time_range: str | None) -> int | None:
    """Length of a same-day time range, or None when there is none."""
    if time_range is None:
        return None
    start, end = (time.fromisoformat(part) for part in time_range.split("-"))
    minutes = (end.hour - start.hour) * 60 + end.minute - start.minute
    return minutes if minutes > 0 else None


async def seat_history(db: AsyncSession, class_id: str, now: datetime) -> SeatHistory:
    """Count really booked seats: the last 90 days, or the next 30 when there were none."""
    for begin, end in ((now - SEAT_WINDOW, now), (now, now + UPCOMING_WINDOW)):
        ids = (
            select(ClassSessionRow.id)
            .where(
                ClassSessionRow.title == class_id, ClassSessionRow.status != "cancelled",
                ClassSessionRow.starts_at >= begin, ClassSessionRow.starts_at < end,
            )
        )
        sessions = await db.scalar(select(func.count()).select_from(ids.subquery())) or 0
        if sessions:
            booked = await db.scalar(
                select(func.coalesce(func.sum(BookingRow.party_size), 0))
                .where(BookingRow.session_id.in_(ids), BookingRow.status != "cancelled"),
            )
            return SeatHistory(sessions=sessions, booked=int(booked or 0))
    return SeatHistory(sessions=0, booked=0)


async def conflicts_on(
    db: AsyncSession, fields: QuoteFields, card: CostCard, travel_minutes: int,
) -> list[Conflict]:
    """List scheduled classes the outreach would push out, with their real bookings."""
    if fields.date is None:
        return []
    day = date.fromisoformat(fields.date)
    begin, end = day_start(day), next_day_start(day)
    if fields.time_range is not None:
        start, finish = (
            datetime.combine(day, time.fromisoformat(part), SEOUL) for part in fields.time_range.split("-")
        )
        margin = timedelta(minutes=travel_minutes)
        begin = start - margin - timedelta(minutes=card.prep_minutes)
        end = finish + margin + timedelta(minutes=card.cleanup_minutes)
    length = func.make_interval(0, 0, 0, 0, 0, ClassSessionRow.duration_minutes)
    rows = await db.scalars(
        select(ClassSessionRow)
        .where(
            ClassSessionRow.status == "scheduled", ClassSessionRow.starts_at < end,
            ClassSessionRow.starts_at + length > begin,
        )
        .order_by(ClassSessionRow.starts_at, ClassSessionRow.id),
    )
    costs = {row.class_id: row for row in await db.scalars(select(ClassCostRow))}
    return [
        Conflict(
            session_id=session.id, title=session.title,
            starts_at=local(session.starts_at).isoformat(timespec="seconds"),
            booked_count=booked,
            lost_krw=(
                booked * (cost.oneday_price_krw - cost.material_per_person_krw) if cost is not None else None
            ),
        )
        for session in rows
        for booked in (await booked_seats(db, session.id),)
        for cost in (costs.get(session.title),)
    ]


async def booked_seats(db: AsyncSession, session_id: str) -> int:
    """Count people actually booked into one class."""
    booked = await db.scalar(
        select(func.coalesce(func.sum(BookingRow.party_size), 0))
        .where(BookingRow.session_id == session_id, BookingRow.status != "cancelled"),
    )
    return int(booked or 0)


def summary_text(result: Calculation) -> str:
    """Say the comparison in one sentence made only of computed numbers."""
    if result.net_per_person_outreach is None or result.net_per_person_oneday is None:
        return "원가가 비어 있어 판단하지 못했어요."
    outreach, oneday = won(result.net_per_person_outreach), won(result.net_per_person_oneday)
    text = f"1인 순수익 {outreach}, 원데이는 {oneday}이에요."
    if result.net_per_hour_outreach is not None and result.net_per_hour_oneday is not None:
        text += (
            f" 시간당으로는 {won(result.net_per_hour_outreach)}, "
            f"원데이는 {won(result.net_per_hour_oneday)}이에요."
        )
    return text


DECLINE: Final = (
    "아쉽지만 이번 일정과 조건으로는 진행이 어렵습니다.\n"
    "다른 날짜나 인원으로 다시 문의해 주시면 안내해 드리겠습니다."
)


def reply_body(result: Calculation, inputs: QuoteInputs, fields: QuoteFields) -> str:
    """Pick the paragraph for the suggested answer and fill it with computed values."""
    when = f" {month_day_weekday(date.fromisoformat(fields.date))}요일" if fields.date else ""
    total = f"총 {won(result.total_krw)}(1인 {won(result.per_person_krw)})"
    if result.suggestion == "accept":
        return (
            f"{inputs.headcount}명 기준{when} 출강 견적은 {total}입니다.\n"
            "품목별 내역은 첨부한 견적표에 적었습니다."
        )
    if result.suggestion == "raise" and result.break_even_headcount is not None:
        needed = won(result.needed_total_krw or result.total_krw)
        return (
            f"{inputs.headcount}명 기준{when} 견적은 {total}입니다.\n"
            f"이 1인 단가로는 {result.break_even_headcount}명부터 진행합니다.\n"
            f"인원을 늘리기 어려우시면 {inputs.headcount}명 기준 총 {needed}부터 가능합니다."
        )
    if result.suggestion == "decline":
        return DECLINE
    return "견적을 확인한 뒤 다시 안내해 드리겠습니다."


def reply_text(shop: str, result: Calculation, inputs: QuoteInputs, fields: QuoteFields) -> str:
    """Draft a reply from computed values; the owner edits it before sending anything."""
    greeting = f"안녕하세요, {shop}입니다. 출강 문의 주셔서 감사합니다."
    return f"{greeting}\n\n{reply_body(result, inputs, fields)}\n\n궁금하신 점은 편하게 말씀해 주세요."


def next_follow_up(now: datetime) -> datetime:
    """Three business days later at 15:00 Seoul time."""
    day, left = local(now).date(), FOLLOW_UP_DAYS
    while left:
        day += timedelta(days=1)
        if day.weekday() <= FRIDAY:
            left -= 1
    return datetime.combine(day, time(15), SEOUL)


def effective_status(row: OutreachQuoteRow, now: datetime) -> QuoteStatus:
    """Turn a sent quote into follow_up once its moment passed; nothing runs in the background."""
    if row.status == "sent" and row.follow_up_at is not None and row.follow_up_at <= now:
        return "follow_up"
    return STATUSES.validate_python(row.status)


def deadline_for(row: OutreachQuoteRow, now: datetime) -> CardDue | None:
    """Show the follow-up moment of a quote still waiting for an answer."""
    if row.follow_up_at is None or effective_status(row, now) not in {"sent", "follow_up"}:
        return None
    return due(row.follow_up_at, suffix=" 다시 연락", missed="기한 지남")


async def view(db: AsyncSession, row: OutreachQuoteRow, now: datetime) -> QuoteView:
    """Rebuild the detail from the stored snapshot plus today's calendar."""
    fields = QuoteFields.model_validate(row.fields)
    inputs = QuoteInputs.model_validate(row.inputs)
    calculation = Calculation.model_validate(row.snapshot)
    _, conflicts = await scenario_for(db, row.class_id, inputs, fields, now)
    shop = await db.scalar(select(WorkshopRow.name).where(WorkshopRow.id == 1)) or "공방"
    change = None
    if fields.date is not None:
        change = (date.fromisoformat(fields.date) - CHANGE_NOTICE).isoformat()
    return QuoteView(
        id=row.id, status=effective_status(row, now), class_id=row.class_id, fields=fields, inputs=inputs,
        signals=[code for code in SIGNAL_CODES if code in row.signals],
        locked=is_effective_lock(row), org_verified_at=stamp(row.org_verified_at),
        calculation=calculation, missing_costs=row.missing_costs, conflicts=conflicts,
        summary=summary_text(calculation),
        reply_draft=reply_text(shop, calculation, inputs, fields), change_deadline=change,
        follow_up_at=next_follow_up(now).isoformat(timespec="seconds"), follow_up_due=deadline_for(row, now),
        outcome=None if row.outcome is None else OUTCOMES.validate_python(row.outcome),
        final_total_krw=row.final_total_krw,
    )


def is_effective_lock(row: OutreachQuoteRow) -> bool:
    """Keep the export locked until the owner confirmed the institution."""
    return row.locked and row.org_verified_at is None


def stamp(moment: datetime | None) -> str | None:
    """Format a stored moment for the client."""
    return local(moment).isoformat(timespec="seconds") if moment is not None else None


async def locked_quote(db: AsyncSession, quote_id: str) -> OutreachQuoteRow:
    """Lock one quote row."""
    row = await db.scalar(
        select(OutreachQuoteRow).where(OutreachQuoteRow.id == quote_id).with_for_update(),
    )
    if row is None:
        raise HTTPException(404, "quote not found")
    return row


async def store(
    db: AsyncSession, row: OutreachQuoteRow, inputs: QuoteInputs, fields: QuoteFields, now: datetime,
) -> QuoteView:
    """Recompute and overwrite the snapshot, then return the fresh detail."""
    scenario, _ = await scenario_for(db, row.class_id, inputs, fields, now)
    result = calculate(scenario)
    row.inputs = inputs.model_dump(mode="json")
    row.snapshot = result.model_dump(mode="json")
    row.missing_costs = missing_costs(scenario.card, scenario.rates)
    row.revision += 1
    await db.flush()
    return await view(db, row, now)


@router.post("/outreach/quotes")
async def create_quote(body: QuoteCreate, db: Session, now: Now) -> QuoteView:
    """Calculate and store one quote from confirmed fields."""
    fields = body.fields.model_copy(update={
        "org_name": scrub(body.fields.org_name, 80), "date_text": scrub(body.fields.date_text),
        "location_text": scrub(body.fields.location_text), "class_hint": scrub(body.fields.class_hint),
    })
    signals = with_server_signals(list(body.signals), fields.org_type, fields.contact_kind)
    inputs = QuoteInputs(
        headcount=body.headcount, per_person_krw=body.per_person_krw, assistants=body.assistants,
        travel_minutes=body.travel_minutes, distance_km=body.distance_km,
    )
    row = OutreachQuoteRow(
        id=f"outreach-{uuid4().hex}", status="draft", class_id=body.class_id,
        fields=fields.model_dump(mode="json"), inputs={}, signals=list(signals), locked=is_locked(signals),
        snapshot={}, missing_costs=[], ab_arm=body.ab_arm, revision=0,
    )
    db.add(row)
    return await store(db, row, inputs, fields, now)


@router.post("/outreach/quotes/{quote_id}/recalculate")
async def recalculate(quote_id: str, body: Recalculate, db: Session, now: Now) -> QuoteView:
    """Change only the given values and overwrite the snapshot."""
    row = await locked_quote(db, quote_id)
    current = QuoteInputs.model_validate(row.inputs)
    inputs = current.model_copy(update=body.model_dump(exclude_unset=True, exclude={"class_id"}))
    if body.class_id is not None:
        row.class_id = body.class_id
    return await store(db, row, inputs, QuoteFields.model_validate(row.fields), now)


@router.get("/outreach/quotes")
async def list_quotes(db: Session, now: Now) -> list[QuoteRowView]:
    """List the newest quotes with their derived status."""
    rows = await db.scalars(
        select(OutreachQuoteRow).order_by(OutreachQuoteRow.created_at.desc(), OutreachQuoteRow.id).limit(100),
    )
    return [row_view(row, now) for row in rows]


def row_view(row: OutreachQuoteRow, now: datetime) -> QuoteRowView:
    """Shorten a quote to one list row."""
    fields = QuoteFields.model_validate(row.fields)
    inputs = QuoteInputs.model_validate(row.inputs)
    calculation = Calculation.model_validate(row.snapshot)
    day = fields.date and month_day_weekday(date.fromisoformat(fields.date))
    parts = [part for part in (day or fields.date_text, f"{inputs.headcount}명", row.class_id) if part]
    return QuoteRowView(
        id=row.id, status=effective_status(row, now),
        title=fields.org_name or f"{ORG_LABELS[fields.org_type]} 출강",
        detail=" · ".join(parts), total_krw=calculation.total_krw, follow_up_due=deadline_for(row, now),
    )


@router.get("/outreach/quotes/{quote_id}")
async def read_quote(quote_id: str, db: Session, now: Now) -> QuoteView:
    """Return one quote with formulas and today's conflicts."""
    row = await db.get(OutreachQuoteRow, quote_id)
    if row is None:
        raise HTTPException(404, "quote not found")
    return await view(db, row, now)


@router.post("/outreach/quotes/{quote_id}/verify-org")
async def verify_org(quote_id: str, db: Session, now: Now) -> Verified:
    """Record that the owner called the institution's main number; a repeat keeps the first time."""
    row = await locked_quote(db, quote_id)
    if row.org_verified_at is None:
        row.org_verified_at = now
        row.revision += 1
        await db.flush()
    return Verified(org_verified_at=stamp(row.org_verified_at) or "", locked=False)


@router.post("/outreach/quotes/{quote_id}/sent")
async def mark_sent(quote_id: str, body: SentRequest, db: Session, now: Now) -> QuoteView:
    """Record a shared quote and, when asked, put one reminder on 오늘."""
    row = await locked_quote(db, quote_id)
    if is_effective_lock(row):
        raise HTTPException(409, "verify the institution first")
    if row.outcome is not None:
        raise HTTPException(409, "action is not valid for the current state")
    row.status = "sent"
    if body.elapsed_seconds is not None and row.elapsed_seconds is None:
        row.elapsed_seconds = body.elapsed_seconds
    if body.follow_up_at is not None:
        row.follow_up_at = body.follow_up_at
        await remind(db, row, body.follow_up_at)
    row.revision += 1
    await db.flush()
    return await view(db, row, now)


async def remind(db: AsyncSession, row: OutreachQuoteRow, at: datetime) -> None:
    """Create the reminder once; a later call moves it while it is still open."""
    task = await db.get(TaskRow, row.follow_up_task_id) if row.follow_up_task_id else None
    if task is not None and task.status == "open":
        task.due_at = at
        task.revision += 1
        return
    fields = QuoteFields.model_validate(row.fields)
    label = fields.org_name or ORG_LABELS[fields.org_type]
    task = TaskRow(
        id=f"task-{uuid4().hex}", kind="general", title=f"{label} 출강 견적 다시 연락",
        detail="답이 없으면 다시 연락해 주세요", due_at=at, status="open",
    )
    db.add(task)
    await db.flush()
    row.follow_up_task_id = task.id


async def save_outcome(
    db: AsyncSession, quote_id: str, body: OutcomeRequest, now: datetime,
) -> OutreachQuoteRow:
    """Record the institution's answer and close the reminder."""
    if body.outcome == "accepted_adjusted" and body.final_total_krw is None:
        raise HTTPException(422, "final_total_krw is required")
    row = await locked_quote(db, quote_id)
    row.status = row.outcome = body.outcome
    row.outcome_at = now
    row.final_total_krw = body.final_total_krw
    row.revision += 1
    task = await db.get(TaskRow, row.follow_up_task_id) if row.follow_up_task_id else None
    if task is not None and task.status == "open":
        task.status, task.completed_at = "done", now
        task.revision += 1
    await db.flush()
    return row


@router.post("/outreach/quotes/{quote_id}/outcome")
async def record_outcome(quote_id: str, body: OutcomeRequest, db: Session, now: Now) -> QuoteView:
    """Record the institution's answer and close the reminder."""
    return await view(db, await save_outcome(db, quote_id, body, now), now)
