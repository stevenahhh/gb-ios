"""Fulfilment: packing, invoice registration, and manual delivery confirmation."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Final, Literal, assert_never

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import ColumnElement, Select, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from bookings import ExpectedRevision
from common import (
    Now,
    PageQuery,
    Session,
    ShortText,
    invalid_transition,
    locked,
    matches,
    required_text,
)
from contracts import ApiRequest, Card, CardDue, CardField, CardList, CardUndo, Page
from display import due, local, masked, relative_day, relative_moment
from metrics import UNSHIPPED, delivery_metrics, load_counts
from models import CustomerRow, OrderRow, ShipmentRow
from orders import MAX_BATCH, PARCEL_STATES, Batch, BatchItem, lock_order, order_fields, order_progress

router = APIRouter()
ESTIMATED_TRANSIT: Final = timedelta(days=2)
INVOICE_LOCK: Final = 0x696E766F
TAG_SCHEDULED: Final = "발송 예정"
type ShipmentFilter = Literal["all", "scheduled", "in_transit", "delivered"]
type ShipmentSort = Literal["soonest", "latest"]
type ShipmentRecord = tuple[ShipmentRow, OrderRow, CustomerRow]
type TrackingNumber = Annotated[str, Field(min_length=4, max_length=40)]


class InvoiceRegistration(ExpectedRevision):
    """Carrier details entered after packing."""

    carrier: ShortText
    tracking_number: TrackingNumber


class InvoiceItem(BatchItem):
    """One packed parcel and its own tracking number."""

    tracking_number: TrackingNumber


class InvoiceBatch(ApiRequest):
    """Parcels handed to one carrier in the same pickup."""

    carrier: ShortText
    items: Annotated[list[InvoiceItem], Field(min_length=1, max_length=MAX_BATCH)]


@dataclass(frozen=True, slots=True)
class ShipmentPage:
    """Paging and ordering for a shipment query."""

    sort: ShipmentSort
    limit: int
    offset: int


def shipment_records() -> Select[ShipmentRecord]:
    """Join everything a shipment card displays."""
    return (
        select(ShipmentRow, OrderRow, CustomerRow)
        .join(OrderRow, OrderRow.id == ShipmentRow.order_id)
        .join(CustomerRow, CustomerRow.id == OrderRow.customer_id)
    )


def arrival_text(arrival: date | None, today: date) -> str:
    """Describe the estimated arrival honestly when it has passed."""
    if arrival is None:
        return "도착일 아직 모름"
    if arrival < today:
        return f"도착일 지남 · {relative_day(arrival, today)}"
    return f"{relative_day(arrival, today)} 도착 예정"


def pickup_due(shipment: ShipmentRow) -> CardDue:
    """Describe the courier pickup an unshipped parcel must make."""
    return due(shipment.ship_by_at, suffix=" 택배 수거", missed="수거 놓침")


def shipment_card(record: ShipmentRecord, today: date) -> Card:
    """Present one shipment and the action its state allows."""
    shipment, order, customer = record
    summary = f"#{order.order_number} · {masked(customer.name)} · {order.quantity}개"
    pickup = f"{relative_moment(shipment.ship_by_at, today)} 택배 수거"
    tracking = f"{shipment.carrier} {shipment.tracking_number}"
    status, action = PARCEL_STATES[shipment.status]
    match shipment.status:
        case "packing":
            lines = [summary, shipment.handling_note or "포장이 끝나면 송장번호를 넣어 주세요"]
            tag, deadline = TAG_SCHEDULED, pickup
        case "invoice_pending":
            lines = [summary, "포장 끝 · 이제 송장 넣을 차례"]
            tag, deadline = TAG_SCHEDULED, pickup
        case "in_transit":
            lines = [summary, tracking, arrival_text(shipment.expected_arrival_on, today)]
            tag, deadline = "배송 중", None
        case _:
            arrived = local(shipment.delivered_at).date() if shipment.delivered_at else today
            lines = [summary, f"{relative_day(arrived, today)} 도착"]
            tag, deadline = "완료", None
    return Card(
        id=shipment.id, kind="shipment", title=order.product_name, status=status, lines=lines,
        deadline=deadline, tag=tag, revision=shipment.revision, action=action,
        due=pickup_due(shipment) if shipment.status in UNSHIPPED else None,
        undo=CardUndo(path=f"/shipments/{shipment.id}/undo") if shipment.status != "packing" else None,
        fields=order_fields(order, customer) + (
            [CardField(label="송장", value=tracking)] if shipment.tracking_number else []
        ),
        progress=order_progress(order.status, shipment.status),
    )


async def shipment_cards(
    db: AsyncSession, conditions: list[ColumnElement[bool]], page: ShipmentPage, today: date,
) -> list[Card]:
    """Load shipment cards by deadline, with finished deliveries last."""
    deadline = ShipmentRow.ship_by_at
    records = await db.execute(
        shipment_records().where(*conditions)
        .order_by(
            case((ShipmentRow.status == "delivered", 1), else_=0),
            deadline.asc() if page.sort == "soonest" else deadline.desc(),
            ShipmentRow.id,
        )
        .limit(page.limit).offset(page.offset),
    )
    return [shipment_card(record, today) for record in records.tuples()]


def list_conditions(status: ShipmentFilter, text: str) -> list[ColumnElement[bool]]:
    """Translate a filter and search into SQL."""
    conditions: list[ColumnElement[bool]] = []
    match status:
        case "all":
            pass
        case "scheduled":
            conditions.append(ShipmentRow.status.in_(UNSHIPPED))
        case "in_transit" | "delivered":
            conditions.append(ShipmentRow.status == status)
        case _:
            assert_never(status)
    if text:
        conditions.append(or_(
            cast(OrderRow.order_number, Text).contains(text.removeprefix("#"), autoescape=True),
            matches(ShipmentRow.tracking_number, text), matches(CustomerRow.name, text),
            matches(OrderRow.product_name, text),
        ))
    return conditions


@router.get("/shipments")
async def list_shipments(
    db: Session, now: Now, paging: PageQuery, status: ShipmentFilter = "all", sort: ShipmentSort = "soonest",
) -> Page:
    """Return one filtered, sorted page of shipments with screen totals."""
    conditions = list_conditions(status, paging.text)
    total = await db.scalar(
        select(func.count()).select_from(ShipmentRow)
        .join(OrderRow, OrderRow.id == ShipmentRow.order_id)
        .join(CustomerRow, CustomerRow.id == OrderRow.customer_id).where(*conditions),
    ) or 0
    return Page(
        metrics=delivery_metrics(await load_counts(db, now.date())),
        items=await shipment_cards(
            db, conditions, ShipmentPage(sort, paging.limit, paging.offset), now.date(),
        ),
        total=total, limit=paging.limit, offset=paging.offset, has_more=paging.has_more(total),
    )


async def card_for(db: AsyncSession, shipment_id: str, now: datetime) -> Card:
    """Reload a shipment after a write."""
    record = (await db.execute(shipment_records().where(ShipmentRow.id == shipment_id))).tuples().one()
    return shipment_card(record, now.date())


async def cards_for(db: AsyncSession, shipment_ids: list[str], now: datetime) -> CardList:
    """Reload the parcels a batch changed, in request order."""
    records = await db.execute(shipment_records().where(ShipmentRow.id.in_(shipment_ids)))
    cards = {card.id: card for card in (shipment_card(record, now.date()) for record in records.tuples())}
    return CardList(items=[cards[shipment_id] for shipment_id in shipment_ids])


async def hold_invoice_lock(db: AsyncSession) -> None:
    """Serialize every writer of tracking numbers, so one number never serves two parcels."""
    _ = await db.execute(select(func.pg_advisory_xact_lock(INVOICE_LOCK)))


async def require_unused_number(db: AsyncSession, number: str, shipment_id: str) -> None:
    """Refuse a tracking number another parcel already carries, ignoring separators."""
    digits = re.sub(r"\D", "", number)
    if not digits:
        return
    stored = func.regexp_replace(ShipmentRow.tracking_number, "[^0-9]", "", "g")
    taken = await db.scalar(
        select(ShipmentRow.id).where(stored == digits, ShipmentRow.id != shipment_id).limit(1),
    )
    if taken is not None:
        raise HTTPException(409, "tracking number is already used")


def pack_parcel(shipment: ShipmentRow, now: datetime) -> None:
    """Record that a locked parcel is packed."""
    if shipment.status != "packing":
        raise invalid_transition()
    shipment.status = "invoice_pending"
    shipment.packed_at = now
    shipment.revision += 1


def send_parcel(shipment: ShipmentRow, carrier: str, tracking_number: str, now: datetime) -> None:
    """Attach carrier details to a locked parcel and move it into transit."""
    if shipment.status != "invoice_pending":
        raise invalid_transition()
    shipment.carrier = required_text(carrier)
    shipment.tracking_number = required_text(tracking_number)
    shipment.status = "in_transit"
    shipment.shipped_at = now
    shipment.expected_arrival_on = now.date() + ESTIMATED_TRANSIT
    shipment.revision += 1


async def deliver_parcel(db: AsyncSession, shipment: ShipmentRow, now: datetime) -> None:
    """Record delivery of a locked parcel and complete its order."""
    if shipment.status != "in_transit":
        raise invalid_transition()
    order = await db.get_one(OrderRow, shipment.order_id, with_for_update=True)
    shipment.status = "delivered"
    shipment.delivered_at = now
    shipment.revision += 1
    order.status = "completed"
    order.revision += 1


@router.post("/shipments/pack")
async def pack_many(body: Batch, db: Session, now: Now) -> CardList:
    """Pack several parcels at once; one parcel that cannot move refuses the whole batch."""
    for item in lock_order(body.items):
        pack_parcel(await locked(db, ShipmentRow, item.id, item.expected_revision), now)
    await db.flush()
    return await cards_for(db, [item.id for item in body.items], now)


@router.post("/shipments/invoice")
async def register_many(body: InvoiceBatch, db: Session, now: Now) -> CardList:
    """Register one carrier's tracking numbers for several packed parcels at once."""
    await hold_invoice_lock(db)
    for item in lock_order(body.items):
        shipment = await locked(db, ShipmentRow, item.id, item.expected_revision)
        await require_unused_number(db, item.tracking_number, shipment.id)
        send_parcel(shipment, body.carrier, item.tracking_number, now)
    await db.flush()
    return await cards_for(db, [item.id for item in body.items], now)


@router.post("/shipments/deliver")
async def deliver_many(body: Batch, db: Session, now: Now) -> CardList:
    """Mark several parcels delivered and complete their orders together."""
    for item in lock_order(body.items):
        await deliver_parcel(db, await locked(db, ShipmentRow, item.id, item.expected_revision), now)
    await db.flush()
    return await cards_for(db, [item.id for item in body.items], now)


@router.post("/shipments/{shipment_id}/pack")
async def pack(shipment_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Record that the parcel is packed."""
    pack_parcel(await locked(db, ShipmentRow, shipment_id, body.expected_revision), now)
    await db.flush()
    return await card_for(db, shipment_id, now)


@router.post("/shipments/{shipment_id}/invoice")
async def register_invoice(shipment_id: str, body: InvoiceRegistration, db: Session, now: Now) -> Card:
    """Attach carrier details and move the parcel into transit."""
    await hold_invoice_lock(db)
    shipment = await locked(db, ShipmentRow, shipment_id, body.expected_revision)
    await require_unused_number(db, body.tracking_number, shipment.id)
    send_parcel(shipment, body.carrier, body.tracking_number, now)
    await db.flush()
    return await card_for(db, shipment_id, now)


@router.post("/shipments/{shipment_id}/deliver")
async def mark_delivered(shipment_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Record delivery and complete the order in the same transaction."""
    await deliver_parcel(db, await locked(db, ShipmentRow, shipment_id, body.expected_revision), now)
    await db.flush()
    return await card_for(db, shipment_id, now)
