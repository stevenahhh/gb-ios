"""Product orders: list and confirmation, which opens fulfilment."""

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Annotated, Final, Literal, NamedTuple, assert_never

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import ColumnElement, Nullable, Select, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from bookings import ExpectedRevision
from common import Now, PageQuery, Session, ShortText, invalid_transition, locked, matches
from contracts import (
    ApiRequest,
    Card,
    CardAction,
    CardField,
    CardList,
    CardProgress,
    CardTarget,
    CardUndo,
    Page,
    Status,
)
from display import SEOUL, local, masked, month_day, won
from metrics import load_counts, metric, money_metric
from models import ChannelRow, CustomerRow, OrderRow, ShipmentRow

router = APIRouter()
PICKUP: Final = time(16)
SAME_DAY_CUTOFF: Final = time(15)
type OrderFilter = Literal["all", "paid", "processing"]
type OrderSort = Literal["newest", "oldest"]
type OrderRecord = tuple[OrderRow, CustomerRow, ChannelRow | None, ShipmentRow | None]
ORDER_STEPS: Final = ("결제", "주문 확인", "포장", "발송", "배송 완료")
SHIPMENT_STEP: Final = {"packing": 2, "invoice_pending": 3, "in_transit": 4, "delivered": 5}
MAX_BATCH: Final = 50


class ParcelState(NamedTuple):
    """What a parcel in one state shows and the one step that moves it on."""

    status: Status
    action: CardAction | None


PARCEL_STATES: Final = {
    "packing": ParcelState(
        Status(text="포장 대기", tone="attention"), CardAction(code="pack", label="포장 완료하기"),
    ),
    "invoice_pending": ParcelState(
        Status(text="송장 대기", tone="attention"), CardAction(code="registerInvoice", label="송장 등록하기"),
    ),
    "in_transit": ParcelState(
        Status(text="배송 중", tone="progress"), CardAction(code="markDelivered", label="배송 완료 확인"),
    ),
    "delivered": ParcelState(Status(text="배송 완료", tone="done"), None),
}


class BatchItem(ExpectedRevision):
    """One row of a batch write with the revision the client saw."""

    id: ShortText


class Batch(ApiRequest):
    """Rows changed together: every one must allow the step, or none changes."""

    items: Annotated[list[BatchItem], Field(min_length=1, max_length=MAX_BATCH)]


def lock_order[T: BatchItem](items: Sequence[T]) -> list[T]:
    """Sort rows by id so overlapping batches lock in one order; a repeated row is invalid."""
    if len({item.id for item in items}) != len(items):
        raise HTTPException(422, "each row may appear once")
    return sorted(items, key=lambda item: item.id)


def order_records() -> Select[OrderRecord]:
    """Join everything an order card displays."""
    return (
        select(OrderRow, CustomerRow, Nullable(ChannelRow), Nullable(ShipmentRow))
        .join(CustomerRow, CustomerRow.id == OrderRow.customer_id)
        .outerjoin(ChannelRow, ChannelRow.id == OrderRow.channel_id)
        .outerjoin(ShipmentRow, ShipmentRow.order_id == OrderRow.id)
    )


def order_progress(order_status: str, shipment_status: str | None) -> CardProgress | None:
    """Place an order on the fixed fulfilment steps; cancelled orders have none."""
    match order_status:
        case "paid":
            current = 1
        case "processing":
            current = SHIPMENT_STEP.get(shipment_status or "", 2)
        case "completed":
            current = len(ORDER_STEPS)
        case _:
            return None
    return CardProgress(steps=list(ORDER_STEPS), current=current)


def order_fields(order: OrderRow, customer: CustomerRow) -> list[CardField]:
    """List the order facts shown as label-value rows."""
    return [
        CardField(label="주문자", value=masked(customer.name)),
        CardField(label="수량", value=f"{order.quantity}개"),
        CardField(label="결제금액", value=won(order.amount_won)),
    ]


def order_card(record: OrderRecord) -> Card:
    """Present one order and the action its state allows."""
    order, customer, channel, shipment = record
    shipment_status = shipment.status if shipment else None
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
        case "processing" if shipment is not None:
            # The order shows its parcel's step, so the owner never leaves the order to keep going.
            status, step = PARCEL_STATES[shipment.status]
            target = CardTarget(kind="shipment", id=shipment.id, revision=shipment.revision)
            action = step.model_copy(update={"target": target}) if step else None
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
        source=source, fields=order_fields(order, customer),
        progress=order_progress(order.status, shipment_status),
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


async def cards_for(db: AsyncSession, order_ids: list[str]) -> CardList:
    """Reload the orders a batch changed, in request order."""
    records = await db.execute(order_records().where(OrderRow.id.in_(order_ids)))
    cards = {card.id: card for card in map(order_card, records.tuples())}
    return CardList(items=[cards[order_id] for order_id in order_ids])


def confirm(db: AsyncSession, order: OrderRow, now: datetime) -> None:
    """Accept a locked paid order and create its packing work."""
    if order.status != "paid":
        raise invalid_transition()
    order.status = "processing"
    order.confirmed_at = now
    order.revision += 1
    db.add(ShipmentRow(
        id=f"shipment-{order.id}", order_id=order.id, status="packing", ship_by_at=first_pickup(now),
    ))


@router.post("/orders/confirm")
async def confirm_orders(body: Batch, db: Session, now: Now) -> CardList:
    """Accept several paid orders at once; one stale or finished order refuses the whole batch."""
    for item in lock_order(body.items):
        confirm(db, await locked(db, OrderRow, item.id, item.expected_revision), now)
    await db.flush()
    return await cards_for(db, [item.id for item in body.items])


@router.post("/orders/{order_id}/confirm")
async def confirm_order(order_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Accept a paid order and create its packing work."""
    confirm(db, await locked(db, OrderRow, order_id, body.expected_revision), now)
    await db.flush()
    return await card_for(db, order_id)
