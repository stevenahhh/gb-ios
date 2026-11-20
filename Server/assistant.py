"""Assistant facts are read from PostgreSQL, never accepted from clients."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import booking_card, booking_records, seats_taken
from contracts import Card
from database import transaction
from display import clock, day_start, local, month_day_weekday, next_day_start, won
from metrics import load_counts, to_send
from models import (
    BookingRow,
    ClassSessionRow,
    ContentDraftRow,
    InquiryRow,
    OrderRow,
    SettingItemRow,
    TaskRow,
    WorkshopRow,
)
from orders import order_card, order_records
from prompts import Policy, ShopFacts, Workshop
from shipments import ShipmentPage, shipment_cards

SECTION_LIMIT: Final = 20
UPCOMING_DAYS: Final = 7
ASK_ITEM_LIMIT: Final = 3


async def workload_lines(db: AsyncSession, now: datetime) -> list[str]:
    """Describe current totals."""
    counts = await load_counts(db, now.date())
    lines = [
        f"오늘 날짜: {now:%Y-%m-%d}, 현재 시각: {clock(now)}",
        f"답변 기다리는 문의 {counts.pending_inquiries}건",
        f"예약금 대기 {counts.deposit_pending}건, 확정 예약 {counts.confirmed_bookings}건",
        f"오늘 새 주문 {counts.orders_today}건, 오늘 결제금액 {won(counts.revenue_today)}",
        f"이번 달 매출 {won(counts.revenue_this_month)}, 처리 대기 주문 {counts.paid_orders}건",
        f"발송 대기 {counts.unshipped}건, 배송 중 {counts.in_transit}건, 배송 완료 {counts.delivered}건",
    ]
    workshop = await db.get(WorkshopRow, 1)
    if workshop is not None:
        lines.append(f"공방: {workshop.name}, 주소: {workshop.address}, 전화: {workshop.phone}")
    return lines


def session_label(starts_at: datetime, now: datetime) -> str:
    """Name a class day the way the owner asks about it."""
    day = local(starts_at).date()
    match (day - now.date()).days:
        case 0:
            return f"오늘 수업: {clock(starts_at)}"
        case 1:
            return f"내일 수업: {clock(starts_at)}"
        case _:
            return f"다가오는 수업: {month_day_weekday(day)} {clock(starts_at)}"


async def schedule_lines(db: AsyncSession, now: datetime) -> list[str]:
    """Describe classes from today through the next week, and near-term tasks."""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    sessions = await db.execute(
        select(ClassSessionRow, seats_taken()).where(
            ClassSessionRow.status != "cancelled", ClassSessionRow.starts_at >= day_start(today),
            ClassSessionRow.starts_at < next_day_start(today + timedelta(days=UPCOMING_DAYS)),
        ).order_by(ClassSessionRow.starts_at).limit(SECTION_LIMIT),
    )
    lines: list[str] = []
    for row, seats in sessions.tuples():
        left = max(row.capacity - seats, 0)
        label = session_label(row.starts_at, now)
        lines.append(f"{label} {row.title} · 예약 {seats}/{row.capacity}명 · 남은 자리 {left}명")
    tasks = await db.scalars(
        select(TaskRow).where(TaskRow.status == "open", TaskRow.due_at < next_day_start(tomorrow))
        .order_by(TaskRow.due_at).limit(SECTION_LIMIT),
    )
    for task in tasks:
        due = "내일까지" if local(task.due_at).date() == tomorrow else "오늘까지"
        lines.append(f"{due} 할 일: {task.title} · {task.detail}")
    return lines


def parcel_line(card: Card, now: datetime) -> str:
    """Tell missed pickups apart from today's, so the answer never merges them."""
    summary = " · ".join(card.lines)
    if card.due is not None and datetime.fromisoformat(card.due.at) < now:
        missed = "발송 대기(기한 지남, 수거를 놓쳐 아직 안 보냄)"
        return f"{missed}: {card.title} · {summary} · 원래 {card.deadline}"
    return f"발송 대기: {card.title} · {summary} · {card.deadline or ''}"


async def work_lines(db: AsyncSession, now: datetime, cards: list[Card]) -> list[str]:
    """Describe items waiting for the owner, collecting their cards for the answer."""
    today = now.date()
    inquiries = await db.scalars(
        select(InquiryRow).where(InquiryRow.status == "pending")
        .order_by(InquiryRow.received_at.desc()).limit(SECTION_LIMIT),
    )
    lines = [f"답변 기다리는 문의: {row.customer} · {row.subject} · {row.question}" for row in inquiries]
    page = ShipmentPage("soonest", SECTION_LIMIT, 0)
    shipments = await shipment_cards(db, list(to_send(today)), page, today)
    cards.extend(shipments)
    lines.extend(parcel_line(card, now) for card in shipments)
    bookings = await db.execute(
        booking_records().where(BookingRow.status == "deposit_pending")
        .order_by(BookingRow.deposit_due_at).limit(SECTION_LIMIT),
    )
    for record in bookings.tuples():
        card = booking_card(record, now)
        cards.append(card)
        lines.append(f"예약금 대기: {card.title} · {' · '.join(card.lines)} · {card.deadline or ''}")
    orders = await db.execute(
        order_records().where(OrderRow.status == "paid").order_by(OrderRow.ordered_at).limit(SECTION_LIMIT),
    )
    for record in orders.tuples():
        card = order_card(record)
        cards.append(card)
        lines.append(f"확인할 주문: {card.title} · {' · '.join(card.lines)}")
    drafts = await db.scalars(
        select(ContentDraftRow).where(ContentDraftRow.status == "draft").limit(SECTION_LIMIT),
    )
    lines += [f"검토할 홍보 초안: {row.title} · {row.summary}" for row in drafts]
    return lines


async def policy_lines(db: AsyncSession) -> list[str]:
    """Add the workshop's written rules."""
    items = await db.scalars(select(SettingItemRow).order_by(SettingItemRow.sort_order))
    return [f"{item.title}: {item.body}" for item in items]


async def shop_facts() -> ShopFacts:
    """Read the profile and customer-facing rules in a transaction closed before the model call."""
    async with transaction() as db:
        row = await db.get(WorkshopRow, 1)
        items = await db.scalars(
            select(SettingItemRow).where(SettingItemRow.is_editable).order_by(SettingItemRow.sort_order),
        )
        policies = tuple(Policy(item.title, item.body) for item in items)
    workshop = None if row is None else Workshop(row.name, row.phone, row.address, row.description)
    return ShopFacts(workshop, policies)


async def build_context(now: datetime) -> tuple[list[str], list[Card]]:
    """Read facts and their cards in a short transaction that closes before the model call."""
    cards: list[Card] = []
    async with transaction() as db:
        lines = (
            await workload_lines(db, now) + await schedule_lines(db, now)
            + await work_lines(db, now, cards) + await policy_lines(db)
        )
    return lines, cards


def named_cards(answer: str, cards: Sequence[Card]) -> list[Card]:
    """Keep one card per title the answer names; a parcel to send comes before the order it belongs to."""
    named = {card.title: card for card in reversed(cards) if card.title in answer}
    return list(named.values())[::-1][:ASK_ITEM_LIMIT]


