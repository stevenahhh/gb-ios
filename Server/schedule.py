"""Calendar days derived from business rows plus owner-added events."""

from collections import defaultdict
from datetime import date, datetime
from typing import Annotated, Final, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import SessionCompletion, seats_taken
from common import LongText, Now, Session, ShortText, invalid_transition, locked, required_text
from contracts import ApiModel, ApiRequest, EventKind, Status
from display import clock, count, day_start, local, masked, next_day_start, people, won
from metrics import UNSHIPPED
from models import CalendarEventRow, ClassSessionRow, OrderRow, ShipmentRow, TaskRow
from orders import OrderRecord, order_card, order_records
from shipments import ShipmentRecord, shipment_card, shipment_records

router = APIRouter()
MAX_RANGE_DAYS: Final = 62
KIND_ORDER: Final[tuple[EventKind, ...]] = ("booking", "order", "delivery", "todo")
type Dated = tuple[date, "AgendaItem"]
type AgendaTarget = Literal["session", "order", "shipment", "task", "event"]


class AgendaItem(ApiModel):
    """One calendar row; `is_done` is set only for rows the owner can check off."""

    id: str
    target: AgendaTarget
    target_id: str
    time: str
    title: str
    kind: EventKind
    detail: str
    status: Status | None = None
    is_done: bool | None = None
    revision: int


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


class EventCreate(ApiRequest):
    """A schedule entry added by the owner."""

    title: ShortText
    kind: EventKind = "todo"
    detail: LongText = ""
    starts_at: Annotated[AwareDatetime, Field(strict=False)]


def session_item(session: ClassSessionRow, seats: int) -> Dated:
    """Present a class with its completion state."""
    return (
        local(session.starts_at).date(),
        AgendaItem(
            id=f"session:{session.id}",
            target="session",
            target_id=session.id,
            time=clock(session.starts_at),
            title=session.title,
            kind="booking",
            detail=f"예약 {people(seats)} · {session.duration_minutes}분",
            is_done=session.status == "completed",
            revision=session.revision,
        ),
    )


def order_item(record: OrderRecord) -> Dated:
    """Present an order with the status its card shows."""
    order, customer, *_ = record
    return (
        local(order.ordered_at).date(),
        AgendaItem(
            id=f"order:{order.id}",
            target="order",
            target_id=order.id,
            time=clock(order.ordered_at),
            title=order.product_name,
            kind="order",
            detail=f"#{order.order_number} · {masked(customer.name)} · {won(order.amount_won)}",
            status=order_card(record).status,
            revision=order.revision,
        ),
    )


def shipment_item(record: ShipmentRecord, today: date) -> Dated:
    """Place a parcel on its next meaningful date."""
    shipment, order, _ = record
    if shipment.delivered_at is not None:
        day, time, detail = local(shipment.delivered_at).date(), clock(shipment.delivered_at), "배송 완료"
    elif shipment.expected_arrival_on is not None:
        day, time, detail = shipment.expected_arrival_on, "종일", "도착 예정"
    else:
        day, time, detail = local(shipment.ship_by_at).date(), clock(shipment.ship_by_at), "택배 수거"
    return (
        day,
        AgendaItem(
            id=f"shipment:{shipment.id}",
            target="shipment",
            target_id=shipment.id,
            time=time,
            title=order.product_name,
            kind="delivery",
            detail=f"#{order.order_number} · {detail}",
            status=shipment_card(record, today).status,
            revision=shipment.revision,
        ),
    )


def task_item(task: TaskRow) -> Dated:
    """Present a task with its completion state."""
    return (
        local(task.due_at).date(),
        AgendaItem(
            id=f"task:{task.id}",
            target="task",
            target_id=task.id,
            time=clock(task.due_at),
            title=task.title,
            kind="order" if task.kind == "material" else "todo",
            detail=" · ".join(part for part in (task.vendor, task.detail) if part),
            is_done=task.status == "done",
            revision=task.revision,
        ),
    )


def event_item(event: CalendarEventRow) -> AgendaItem:
    """Present an owner-created event."""
    return AgendaItem.model_validate(
        {
            "id": f"event:{event.id}",
            "target": "event",
            "target_id": event.id,
            "time": clock(event.starts_at),
            "title": event.title,
            "kind": event.kind,
            "detail": event.detail,
            "is_done": event.completed_at is not None,
            "revision": event.revision,
        },
    )


async def session_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Add one booking row per scheduled class."""
    rows = await db.execute(
        select(ClassSessionRow, seats_taken()).where(
            ClassSessionRow.status != "cancelled",
            ClassSessionRow.starts_at >= begin,
            ClassSessionRow.starts_at < end,
        ),
    )
    return [session_item(row, seats) for row, seats in rows.tuples()]


async def order_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Add customer orders placed in the range."""
    records = await db.execute(
        order_records().where(
            OrderRow.status != "cancelled",
            OrderRow.ordered_at >= begin,
            OrderRow.ordered_at < end,
        ),
    )
    return [order_item(record) for record in records.tuples()]


async def shipment_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Add parcels whose next meaningful date falls in the range."""
    records = await db.execute(
        shipment_records().where(
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
    return [shipment_item(record, local(begin).date()) for record in records.tuples()]


async def owner_items(db: AsyncSession, begin: datetime, end: datetime) -> list[Dated]:
    """Add tasks and owner-created events."""
    tasks = await db.scalars(select(TaskRow).where(TaskRow.due_at >= begin, TaskRow.due_at < end))
    events = await db.scalars(
        select(CalendarEventRow).where(CalendarEventRow.starts_at >= begin, CalendarEventRow.starts_at < end),
    )
    items = [task_item(task) for task in tasks]
    items += [(local(event.starts_at).date(), event_item(event)) for event in events]
    return items


@router.get("/calendar")
async def calendar_range(
    db: Session,
    now: Now,
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
) -> CalendarRange:
    """Return days with rows; each marker count equals that day's agenda rows."""
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
        items = sorted(grouped[day], key=lambda item: (item.time == "종일", item.time, item.id))
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
    return CalendarRange(today=now.date(), start=start, end=end, days=days)


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


@router.post("/calendar/events/{event_id}/completion")
async def set_event_completion(event_id: str, body: SessionCompletion, db: Session, now: Now) -> AgendaItem:
    """Check off an owner-added event, or undo that mark."""
    event = await locked(db, CalendarEventRow, event_id, body.expected_revision)
    if (event.completed_at is not None) == body.done:
        raise invalid_transition()
    event.completed_at = now if body.done else None
    event.revision += 1
    await db.flush()
    return event_item(event)
