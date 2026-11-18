"""Product orders: list and confirmation, which opens fulfilment."""

from datetime import datetime, time, timedelta
from typing import Final, Literal, assert_never

from fastapi import APIRouter
from sqlalchemy import ColumnElement, Nullable, Select, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from bookings import ExpectedRevision
from common import Now, PageQuery, Session, invalid_transition, locked, matches
from contracts import Card, CardAction, CardUndo, Page, Status
from display import SEOUL, local, masked, month_day, won
from metrics import load_counts, metric, money_metric
from models import ChannelRow, CustomerRow, OrderRow, ShipmentRow

router = APIRouter()
PICKUP: Final = time(16)
SAME_DAY_CUTOFF: Final = time(15)
type OrderFilter = Literal["all", "paid", "processing"]
type OrderSort = Literal["newest", "oldest"]
type OrderRecord = tuple[OrderRow, CustomerRow, ChannelRow | None, str | None]


def order_records() -> Select[OrderRecord]:
    """Join everything an order card displays."""
    return (
        select(OrderRow, CustomerRow, Nullable(ChannelRow), Nullable(ShipmentRow.status))
        .join(CustomerRow, CustomerRow.id == OrderRow.customer_id)
        .outerjoin(ChannelRow, ChannelRow.id == OrderRow.channel_id)
        .outerjoin(ShipmentRow, ShipmentRow.order_id == OrderRow.id)
    )


def order_card(record: OrderRecord) -> Card:
    """Present one order and the action its state allows."""
    order, customer, channel, shipment_status = record
    source = channel.name if channel else "직접 주문"
    lines = [
        f"#{order.order_number} · {month_day(local(order.ordered_at).date())} 주문 · {source}",
        f"{masked(customer.name)} · {order.quantity}개 · {won(order.amount_won)}",
    ]
    action = None
    match order.status:
        case "paid":
            status = Status(text="결제 완료", tone="done")
            action = CardAction(code="confirmOrder", label="주문 확인하기")
        case "processing":
            status = Status(text="처리 중", tone="progress")
        case "completed":
            status = Status(text="배송 완료", tone="done")
        case _:
            status = Status(text="취소", tone="neutral")
    return Card(
        id=order.id, kind="order", title=order.product_name, status=status, lines=lines,
        tag=status.text, revision=order.revision, action=action,
        undo=CardUndo(path=f"/orders/{order.id}/undo-confirm")
        if order.status == "processing" and shipment_status == "packing" else None,
    )


def list_conditions(status: OrderFilter, text: str) -> list[ColumnElement[bool]]:
    """Translate a filter and search into SQL."""
    conditions: list[ColumnElement[bool]] = []
    match status:
        case "all":
            conditions.append(OrderRow.status != "cancelled")
        case "paid" | "processing":
            conditions.append(OrderRow.status == status)
        case _:
            assert_never(status)
    if text:
        number = text.removeprefix("#")
        conditions.append(or_(
            cast(OrderRow.order_number, Text).contains(number, autoescape=True),
            matches(CustomerRow.name, text), matches(OrderRow.product_name, text),
        ))
    return conditions


@router.get("/orders")
async def list_orders(
    db: Session, now: Now, paging: PageQuery, status: OrderFilter = "all", sort: OrderSort = "newest",
) -> Page:
    """Return one filtered, sorted page of orders with screen totals."""
    conditions = list_conditions(status, paging.text)
    ordering = OrderRow.ordered_at.desc() if sort == "newest" else OrderRow.ordered_at.asc()
    records = await db.execute(
        order_records().where(*conditions).order_by(ordering, OrderRow.id)
        .limit(paging.limit).offset(paging.offset),
    )
    total = await db.scalar(
        select(func.count()).select_from(OrderRow)
        .join(CustomerRow, CustomerRow.id == OrderRow.customer_id).where(*conditions),
    ) or 0
    counts = await load_counts(db, now.date())
    return Page(
        metrics=[
            metric("orders", "전체 주문", counts.orders),
            metric("paid", "처리 대기", counts.paid_orders),
            money_metric("monthRevenue", "이번 달 매출", counts.revenue_this_month),
        ],
        items=[order_card(record) for record in records.tuples()],
        total=total, limit=paging.limit, offset=paging.offset, has_more=paging.has_more(total),
    )


def first_pickup(now: datetime) -> datetime:
    """Choose today's courier pickup until the cutoff, otherwise tomorrow's."""
    day = now.date() if now.time() < SAME_DAY_CUTOFF else now.date() + timedelta(days=1)
    return datetime.combine(day, PICKUP, SEOUL)


async def card_for(db: AsyncSession, order_id: str) -> Card:
    """Reload an order after a write."""
    record = (await db.execute(order_records().where(OrderRow.id == order_id))).tuples().one()
    return order_card(record)


@router.post("/orders/{order_id}/confirm")
async def confirm_order(order_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Accept a paid order and create its packing work."""
    order = await locked(db, OrderRow, order_id, body.expected_revision)
    if order.status != "paid":
        raise invalid_transition()
    order.status = "processing"
    order.confirmed_at = now
    order.revision += 1
    db.add(ShipmentRow(
        id=f"shipment-{order.id}", order_id=order.id, status="packing", ship_by_at=first_pickup(now),
    ))
    await db.flush()
    return await card_for(db, order.id)
