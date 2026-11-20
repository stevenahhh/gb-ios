"""Calendar days derived from business rows plus owner-added events."""

from collections import defaultdict
from datetime import date, datetime
from typing import Annotated, Final
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import ExpectedRevision, seats_taken
from common import LongText, Now, Session, ShortText, locked, required_text
from contracts import ApiModel, ApiRequest, EventKind, Moved
from display import clock, clock_or_all_day, count, day_start, local, masked, next_day_start, people, won
from metrics import UNSHIPPED
from models import BookingRow, CalendarEventRow, ClassSessionRow, CustomerRow, OrderRow, ShipmentRow, TaskRow

router = APIRouter()
MAX_RANGE_DAYS: Final = 62
KIND_ORDER: Final[tuple[EventKind, ...]] = ("booking", "order", "delivery", "todo")
type Dated = tuple[date, "AgendaItem"]


class AgendaItem(ApiModel):
    """One calendar row."""

    id: str
    time: str
    title: str
    kind: EventKind
    detail: str
    is_done: bool | None = None
    minutes: int | None = None
    subject: str | None = None
    amount_won: int | None = None
    revision: int | None = None


class DayEvent(ApiModel):
    """How many rows of a kind a day has."""

    kind: EventKind
    count: int
    display: str


class CalendarDay(ApiModel):
    """A day that has at least one row."""

    date: date
    events: list[DayEvent]
    items: list[AgendaItem]


class CalendarRange(ApiModel):
    """Calendar data for the requested inclusive range."""

    today: date
    start: date
    end: date
    days: list[CalendarDay]
    overdue_shipments: list[AgendaItem] = Field(default_factory=list)


class EventCreate(ApiRequest):
    """A schedule entry added by the owner."""

    title: ShortText
    kind: EventKind = "todo"
    detail: LongText = ""
    starts_at: Annotated[AwareDatetime, Field(strict=False)]


def booker_text(name: str | None, seats: int) -> str:
    """Name the first booker and how many other people come."""
    if name is None:
        return "아직 예약 없음"
    others = f" 외 {seats - 1}명" if seats > 1 else ""
    return f"{masked(name)} 님{others}"


async def session_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Add one booking row per scheduled class, named after its first booker."""
    first_booker = (
        select(CustomerRow.name)
        .join(BookingRow, BookingRow.customer_id == CustomerRow.id)
        .where(BookingRow.session_id == ClassSessionRow.id, BookingRow.status != "cancelled")
        .order_by(BookingRow.created_at, BookingRow.id)
        .limit(1)
        .correlate(ClassSessionRow)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(ClassSessionRow, seats_taken(), first_booker).where(
            ClassSessionRow.status != "cancelled",
            ClassSessionRow.starts_at >= begin,
            ClassSessionRow.starts_at < end,
        ),
    )
    return [
        (
            local(row.starts_at).date(),
            AgendaItem(
                id=f"session:{row.id}",
                time=clock(row.starts_at),
                title=row.title,
                kind="booking",
                detail=f"예약 {people(seats)} · {row.duration_minutes}분",
                is_done=row.status == "completed",
                minutes=row.duration_minutes,
                subject=booker_text(name, seats),
            ),
        )
        for row, seats, name in rows.tuples()
    ]


async def order_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Add customer orders placed in the range."""
    orders = await db.execute(
        select(OrderRow, CustomerRow)
        .join(CustomerRow, CustomerRow.id == OrderRow.customer_id)
        .where(
            OrderRow.status != "cancelled",
            OrderRow.ordered_at >= begin,
            OrderRow.ordered_at < end,
        ),
    )
    return [
        (
            local(order.ordered_at).date(),
            AgendaItem(
                id=f"order:{order.id}",
                time=clock(order.ordered_at),
                title=order.product_name,
                kind="order",
                detail=f"#{order.order_number} · {masked(customer.name)} · {won(order.amount_won)}",
                subject=masked(customer.name),
                amount_won=order.amount_won,
            ),
        )
        for order, customer in orders.tuples()
    ]


async def shipment_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Place parcels on their next meaningful date."""
    rows = await db.execute(
        select(ShipmentRow, OrderRow)
        .join(OrderRow, OrderRow.id == ShipmentRow.order_id)
        .where(
            or_(
                and_(
                    ShipmentRow.status.in_(UNSHIPPED),
                    ShipmentRow.ship_by_at >= begin,
                    ShipmentRow.ship_by_at < end,
                ),
                and_(
                    ShipmentRow.status == "in_transit",
                    ShipmentRow.expected_arrival_on >= local(begin).date(),
                    ShipmentRow.expected_arrival_on < local(end).date(),
                ),
                and_(ShipmentRow.delivered_at >= begin, ShipmentRow.delivered_at < end),
            ),
        ),
    )
    items: list[Dated] = []
    for shipment, order in rows.tuples():
        done: bool | None
        if shipment.delivered_at is not None:
            day, time, detail = local(shipment.delivered_at).date(), clock(shipment.delivered_at), "배송 완료"
            done = True
        elif shipment.expected_arrival_on is not None:
            day, time, detail = shipment.expected_arrival_on, "종일", "도착 예정"
            done = None
        else:
            day, time, detail = local(shipment.ship_by_at).date(), clock(shipment.ship_by_at), "택배 수거"
            done = False
        items.append(
            (
                day,
                AgendaItem(
                    id=f"shipment:{shipment.id}",
                    time=time,
                    title=order.product_name,
                    kind="delivery",
                    detail=f"#{order.order_number} · {detail}",
                    is_done=done,
                ),
            ),
        )
    return items


async def owner_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Add tasks and owner-created events."""
    tasks = await db.scalars(select(TaskRow).where(TaskRow.due_at >= begin, TaskRow.due_at < end))
    events = await db.scalars(
        select(CalendarEventRow).where(CalendarEventRow.starts_at >= begin, CalendarEventRow.starts_at < end),
    )
    items: list[Dated] = [
        (
            local(task.due_at).date(),
            AgendaItem(
                id=f"task:{task.id}",
                time=clock_or_all_day(task.due_at),
                title=task.title,
                kind="todo",
                detail=" · ".join(part for part in (task.vendor, task.detail) if part),
                is_done=task.status == "done",
                subject=task.vendor or task.detail or None,
                revision=task.revision,
            ),
        )
        for task in tasks
    ]
    items += [(local(event.starts_at).date(), event_item(event)) for event in events]
    return items


def event_item(event: CalendarEventRow) -> AgendaItem:
    """Present an owner-created event."""
    return AgendaItem.model_validate(
        {
            "id": f"event:{event.id}",
            "time": clock_or_all_day(event.starts_at),
            "title": event.title,
            "kind": event.kind,
            "detail": event.detail,
            "revision": event.revision,
        },
    )


@router.get("/calendar")
async def calendar_range(
    db: Session,
    now: Now,
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
) -> CalendarRange:
    """Return days with rows; all-day rows lead, and each marker count equals that day's rows."""
    if end < start or (end - start).days >= MAX_RANGE_DAYS:
        raise HTTPException(422, "date range must be ascending and at most 62 days")
    begin, stop = day_start(start), next_day_start(end)
    grouped: defaultdict[date, list[AgendaItem]] = defaultdict(list)
    loaders = (session_items, order_items, shipment_items, owner_items)
    for loader in loaders:
        for day, item in await loader(db, begin, stop):
            grouped[day].append(item)
    days: list[CalendarDay] = []
    for day in sorted(grouped):
        items = sorted(grouped[day], key=lambda item: (item.time != "종일", item.time, item.id))
        kinds: list[tuple[EventKind, int]] = [
            (kind, sum(item.kind == kind for item in items)) for kind in KIND_ORDER
        ]
        days.append(
            CalendarDay(
                date=day,
                items=items,
                events=[
                    DayEvent(kind=kind, count=total, display=count(total)) for kind, total in kinds if total
                ],
            ),
        )
    overdue = await db.execute(
        select(ShipmentRow, OrderRow)
        .join(OrderRow, OrderRow.id == ShipmentRow.order_id)
        .where(ShipmentRow.status.in_(UNSHIPPED), ShipmentRow.ship_by_at < day_start(now.date()))
        .order_by(ShipmentRow.ship_by_at, ShipmentRow.id),
    )
    return CalendarRange(
        today=now.date(), start=start, end=end, days=days,
        overdue_shipments=[
            AgendaItem(
                id=f"shipment:{shipment.id}", time=clock(shipment.ship_by_at), title=order.product_name,
                kind="delivery", detail=f"#{order.order_number} · 택배 수거", is_done=False,
            )
            for shipment, order in overdue.tuples()
        ],
    )


@router.post("/calendar/events", status_code=201)
async def create_event(body: EventCreate, db: Session) -> AgendaItem:
    """Persist an owner-added schedule entry."""
    event = CalendarEventRow(
        id=f"event-{uuid4().hex}",
        kind=body.kind,
        title=required_text(body.title),
        detail=body.detail.strip(),
        starts_at=body.starts_at,
    )
    db.add(event)
    await db.flush()
    return event_item(event)


class EventMove(ExpectedRevision):
    """Move an owner-added entry to a new moment."""

    starts_at: Annotated[AwareDatetime, Field(strict=False)]


@router.post("/calendar/events/{event_id}/move")
async def move_event(event_id: str, body: EventMove, db: Session) -> Moved:
    """Reschedule an owner-added entry, keeping everything else."""
    event = await locked(db, CalendarEventRow, event_id, body.expected_revision)
    event.starts_at = body.starts_at
    event.revision += 1
    await db.flush()
    return Moved(revision=event.revision)
