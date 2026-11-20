"""Assistant facts are read from PostgreSQL, never accepted from clients."""

from datetime import datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import booking_card, booking_records, seats_taken
from contracts import Card
from database import transaction
from display import clock, day_start, next_day_start, won
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
from shipments import ShipmentPage, shipment_cards

SECTION_LIMIT: Final = 20


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


async def schedule_lines(db: AsyncSession, now: datetime) -> list[str]:
    """Describe today's classes and tasks."""
    today = now.date()
    sessions = await db.execute(
        select(ClassSessionRow, seats_taken()).where(
            ClassSessionRow.status != "cancelled", ClassSessionRow.starts_at >= day_start(today),
            ClassSessionRow.starts_at < next_day_start(today),
        ).order_by(ClassSessionRow.starts_at).limit(SECTION_LIMIT),
    )
    lines = [
        f"오늘 수업: {clock(row.starts_at)} {row.title} · 예약 {seats}/{row.capacity}명"
        for row, seats in sessions.tuples()
    ]
    tasks = await db.scalars(
        select(TaskRow).where(TaskRow.status == "open", TaskRow.due_at < next_day_start(today))
        .order_by(TaskRow.due_at).limit(SECTION_LIMIT),
    )
    lines += [f"오늘까지 할 일: {task.title} · {task.detail}" for task in tasks]
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


async def build_context(now: datetime) -> tuple[list[str], list[Card]]:
    """Read facts and their cards in a short transaction that closes before the model call."""
    cards: list[Card] = []
    async with transaction() as db:
        lines = (
            await workload_lines(db, now) + await schedule_lines(db, now)
            + await work_lines(db, now, cards) + await policy_lines(db)
        )
    return lines, cards


