"""The today screen, composed from the same queries as the work areas."""

from datetime import date, datetime, timedelta
from typing import Final, Literal

from fastapi import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels import channel_cards
from common import Now, Session
from contracts import ApiModel, Card, CardDue, EventKind, Metric, Status
from display import clock, clock_or_all_day, count, day_start, due, local, masked, next_day_start, people
from metrics import (
    UNSHIPPED,
    Counts,
    channel_metric,
    counted,
    delivery_metrics,
    integers,
    load_counts,
    metric,
    to_send,
)
from models import BookingRow, ClassSessionRow, CustomerRow, RecommendationRow, ShipmentRow, TaskRow
from recommendations import recommendation_cards
from shipments import ShipmentPage, shipment_cards
from tasks import open_channel_tasks

router = APIRouter()
RECENT_WINDOW: Final = timedelta(days=7)
SECTION_LIMIT: Final = 50
type Area = Literal["bookings", "orders", "deliveries", "channels"]


class TaskItem(ApiModel):
    """One row in the today task list."""

    id: str
    target: Literal["session", "task", "shipment"]
    time: str | None
    title: str
    detail: str
    status: Status | None
    is_done: bool | None
    revision: int
    due: CardDue | None = None
    starts_at: datetime | None = None


class TaskGroup(ApiModel):
    """A titled group of today rows."""

    title: str
    kind: EventKind
    area: Area | None
    items: list[TaskItem]


class TasksSegment(ApiModel):
    """The default today segment."""

    metrics: list[Metric]
    groups: list[TaskGroup]


class ChannelsSegment(ApiModel):
    """Channel status and chores due now."""

    metrics: list[Metric]
    cards: list[Card]
    todos: list[Card]


class DeliverySegment(ApiModel):
    """Parcels to send today and parcels moving."""

    metrics: list[Metric]
    ship_today: list[Card]
    in_transit: list[Card]
    transit_summary: str
    transit_detail: str


class SuggestionsSegment(ApiModel):
    """Open recommendations."""

    metrics: list[Metric]
    items: list[Card]


class HeadlineSession(ApiModel):
    """A class today, for the headline's "N분 뒤 / 진행 중" rule."""

    title: str
    starts_at: str
    minutes: int
    is_done: bool


class HeadlineFacts(ApiModel):
    """Counts the app's headline rules read; the wording itself is chosen on the device."""

    overdue_shipments: int
    overdue_tasks: int
    sessions: list[HeadlineSession]
    pending_inquiries: int
    deposit_pending: int
    pending_drafts: int
    open_tasks_today: int
    tasks_today: int
    open_shipments_today: int
    shipments_today: int
    tomorrow_classes: int
    week_classes_left: int


class Today(ApiModel):
    """Everything shown on the today tab."""

    date: date
    generated_at: datetime
    attention_count: int
    tasks: TasksSegment
    channels: ChannelsSegment
    delivery: DeliverySegment
    suggestions: SuggestionsSegment
    headline: HeadlineFacts


async def session_group(db: AsyncSession, today: date) -> TaskGroup | None:
    """List today's classes with their booked people."""
    sessions = list(await db.scalars(
        select(ClassSessionRow)
        .where(
            ClassSessionRow.status != "cancelled", ClassSessionRow.starts_at >= day_start(today),
            ClassSessionRow.starts_at < next_day_start(today),
        ).order_by(ClassSessionRow.starts_at, ClassSessionRow.id),
    ))
    if not sessions:
        return None
    rows = await db.execute(
        select(BookingRow.session_id, BookingRow.party_size, CustomerRow.name)
        .join(CustomerRow, CustomerRow.id == BookingRow.customer_id)
        .where(BookingRow.session_id.in_([row.id for row in sessions]), BookingRow.status != "cancelled")
        .order_by(BookingRow.created_at, BookingRow.id),
    )
    parties: dict[str, list[tuple[int, str]]] = {}
    for session_id, party, name in rows.tuples():
        parties.setdefault(session_id, []).append((party, name))
    items: list[TaskItem] = []
    for session in sessions:
        booked = parties.get(session.id, [])
        total = sum(party for party, _ in booked)
        others = total - 1
        suffix = f" 외 {others}명" if others else ""
        who = f"{masked(booked[0][1])} 님{suffix}" if booked else "예약 없음"
        items.append(TaskItem(
            id=session.id, target="session", time=clock(session.starts_at), title=session.title,
            detail=f"{who} · {session.duration_minutes}분", status=None,
            is_done=session.status == "completed", revision=session.revision, starts_at=session.starts_at,
        ))
    return TaskGroup(title="예약", kind="booking", area="bookings", items=items)


def shipment_group(cards: list[Card]) -> TaskGroup | None:
    """Reuse the delivery cards as compact rows."""
    if not cards:
        return None
    items = [
        TaskItem(
            id=card.id, target="shipment", time=None, title=card.title,
            detail=card.lines[0], status=card.status, is_done=None, revision=card.revision, due=card.due,
        )
        for card in cards
    ]
    return TaskGroup(title="배송", kind="delivery", area="deliveries", items=items)


async def task_group(db: AsyncSession, today: date, *, material: bool) -> TaskGroup | None:
    """List tasks due by today plus those finished today."""
    end = next_day_start(today)
    rows = await db.scalars(
        select(TaskRow)
        .where(
            TaskRow.kind == ("material" if material else "general"),
            or_(
                (TaskRow.status == "open") & (TaskRow.due_at < end),
                TaskRow.completed_at >= day_start(today),
            ),
        ).order_by(TaskRow.due_at, TaskRow.id).limit(SECTION_LIMIT),
    )
    items = [
        TaskItem(
            id=row.id, target="task", title=row.title,
            time=None if material else clock_or_all_day(row.due_at),
            detail=" · ".join(part for part in (row.vendor, row.detail) if part), status=None,
            is_done=row.status == "done", revision=row.revision,
            due=None if row.status == "done" else due(row.due_at, suffix="까지"),
        )
        for row in rows
    ]
    if not items:
        return None
    if material:
        return TaskGroup(title="재료 주문", kind="order", area=None, items=items)
    return TaskGroup(title="할 일", kind="todo", area=None, items=items)


def transit_text(counts: Counts) -> tuple[str, str]:
    """Summarize moving parcels from their estimated arrival dates."""
    summary = f"배송 중 {count(counts.in_transit)} · 오늘 도착 {count(counts.arriving_today)}"
    if counts.late_in_transit:
        return summary, f"도착 예정일이 지난 배송이 {count(counts.late_in_transit)} 있어요."
    return summary, "도착 예정일이 지난 배송은 없어요."


async def headline_facts(db: AsyncSession, now: datetime, counts: Counts) -> HeadlineFacts:
    """Collect what the device needs to pick today's headline."""
    today = now.date()
    begin, end = day_start(today), next_day_start(today)
    tomorrow_end = next_day_start(today + timedelta(days=1))
    week_end = day_start(today + timedelta(days=7 - today.weekday()))
    sessions = await db.scalars(
        select(ClassSessionRow)
        .where(ClassSessionRow.status != "cancelled", ClassSessionRow.starts_at >= begin,
               ClassSessionRow.starts_at < end)
        .order_by(ClassSessionRow.starts_at, ClassSessionRow.id),
    )
    unshipped, open_task = ShipmentRow.status.in_(UNSHIPPED), TaskRow.status == "open"
    later_class = (ClassSessionRow.status != "cancelled", ClassSessionRow.starts_at >= end)
    values = await integers(db, [
        counted(ShipmentRow, unshipped, ShipmentRow.ship_by_at < now),
        counted(TaskRow, open_task, TaskRow.due_at < now),
        counted(TaskRow, open_task, TaskRow.due_at >= now, TaskRow.due_at < end),
        counted(TaskRow, TaskRow.due_at >= begin, TaskRow.due_at < end),
        counted(ShipmentRow, unshipped, ShipmentRow.ship_by_at >= now, ShipmentRow.ship_by_at < end),
        counted(ShipmentRow, ShipmentRow.ship_by_at >= begin, ShipmentRow.ship_by_at < end),
        counted(ClassSessionRow, *later_class, ClassSessionRow.starts_at < tomorrow_end),
        counted(ClassSessionRow, *later_class, ClassSessionRow.starts_at < week_end),
    ])
    overdue_shipments, overdue_tasks, open_tasks, tasks, open_shipments, shipments, tomorrow, week = values
    return HeadlineFacts(
        overdue_shipments=overdue_shipments, overdue_tasks=overdue_tasks,
        sessions=[
            HeadlineSession(
                title=row.title, starts_at=local(row.starts_at).isoformat(timespec="seconds"),
                minutes=row.duration_minutes, is_done=row.status == "completed",
            )
            for row in sessions
        ],
        pending_inquiries=counts.pending_inquiries, deposit_pending=counts.deposit_pending,
        pending_drafts=counts.drafts, open_tasks_today=open_tasks, tasks_today=tasks,
        open_shipments_today=open_shipments, shipments_today=shipments,
        tomorrow_classes=tomorrow, week_classes_left=week,
    )


@router.get("/today")
async def today_screen(db: Session, now: Now) -> Today:
    """Build the whole today tab in one transaction."""
    today = now.date()
    counts = await load_counts(db, today)
    page = ShipmentPage("soonest", SECTION_LIMIT, 0)
    ship_today = await shipment_cards(db, list(to_send(today)), page, today)
    in_transit = await shipment_cards(db, [ShipmentRow.status == "in_transit"], page, today)
    groups = [
        await session_group(db, today), shipment_group(ship_today),
        await task_group(db, today, material=True), await task_group(db, today, material=False),
    ]
    suggestions = await recommendation_cards(db, now, or_(
        RecommendationRow.status == "open", RecommendationRow.acknowledged_at >= now - RECENT_WINDOW,
    ))
    acknowledged = await db.scalar(select(counted(
        RecommendationRow, RecommendationRow.acknowledged_at >= now - RECENT_WINDOW,
    ))) or 0
    summary, detail = transit_text(counts)
    new_orders = metric("newOrders", "오늘 새 주문", counts.orders_today)
    return Today(
        date=today, generated_at=now, attention_count=counts.attention,
        tasks=TasksSegment(
            metrics=[
                Metric(
                    key="bookedPeople", label="오늘 예약", value=counts.booked_people_today,
                    display=people(counts.booked_people_today),
                ),
                new_orders, metric("shipToday", "오늘 발송", counts.ship_due_today),
            ],
            groups=[group for group in groups if group is not None],
        ),
        channels=ChannelsSegment(
            metrics=[
                channel_metric(counts.channels), new_orders,
                metric("pendingInquiries", "답변 기다리는 문의", counts.pending_inquiries),
            ],
            cards=await channel_cards(db, today), todos=await open_channel_tasks(db, today),
        ),
        delivery=DeliverySegment(
            metrics=delivery_metrics(counts), ship_today=ship_today, in_transit=in_transit,
            transit_summary=summary, transit_detail=detail,
        ),
        suggestions=SuggestionsSegment(
            metrics=[
                metric(
                    "openRecommendations", "오늘의 추천",
                    sum(card.action is not None for card in suggestions),
                ),
                metric("drafts", "준비된 초안", counts.drafts),
                metric("acknowledgedThisWeek", "이번 주 확인", acknowledged),
            ],
            items=suggestions,
        ),
        headline=await headline_facts(db, now, counts),
    )
