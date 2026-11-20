"""Fulfilment: packing, invoice registration, and manual delivery confirmation."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Final, Literal, assert_never

from fastapi import APIRouter
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
from contracts import Card, CardAction, CardDue, CardField, CardUndo, Page, Status
from display import due, local, masked, relative_day, relative_moment
from metrics import UNSHIPPED, delivery_metrics, load_counts
from models import CustomerRow, OrderRow, ShipmentRow
from orders import order_fields, order_progress

router = APIRouter()
ESTIMATED_TRANSIT: Final = timedelta(days=2)
TAG_SCHEDULED: Final = "발송 예정"
type ShipmentFilter = Literal["all", "scheduled", "in_transit", "delivered"]
type ShipmentSort = Literal["soonest", "latest"]
type ShipmentRecord = tuple[ShipmentRow, OrderRow, CustomerRow]


class InvoiceRegistration(ExpectedRevision):
    """Carrier details entered after packing."""

    carrier: ShortText
    tracking_number: Annotated[str, Field(min_length=4, max_length=40)]


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
        return "도착 예정일 미정"
    if arrival < today:
        return f"도착 예정일 지남 · {relative_day(arrival, today)}"
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
    match shipment.status:
        case "packing":
            lines = [summary, shipment.handling_note or "포장 후 송장을 등록해 주세요"]
            status, tag, deadline = Status(text="포장 대기", tone="attention"), TAG_SCHEDULED, pickup
            action = CardAction(code="pack", label="포장 완료하기")
        case "invoice_pending":
            lines = [summary, "포장 완료 · 송장 등록 필요"]
            status, tag, deadline = Status(text="송장 대기", tone="attention"), TAG_SCHEDULED, pickup
            action = CardAction(code="registerInvoice", label="송장 등록하기")
        case "in_transit":
            lines = [summary, tracking, arrival_text(shipment.expected_arrival_on, today)]
            status, tag, deadline = Status(text="배송 중", tone="progress"), "배송 중", None
            action = CardAction(code="markDelivered", label="배송 완료 확인")
        case _:
            arrived = local(shipment.delivered_at).date() if shipment.delivered_at else today
            lines = [summary, f"{relative_day(arrived, today)} 도착"]
            status, tag, deadline = Status(text="배송 완료", tone="done"), "완료", None
            action = None
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


@router.post("/shipments/{shipment_id}/pack")
async def pack(shipment_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Record that the parcel is packed."""
    shipment = await locked(db, ShipmentRow, shipment_id, body.expected_revision)
    if shipment.status != "packing":
        raise invalid_transition()
    shipment.status = "invoice_pending"
    shipment.packed_at = now
    shipment.revision += 1
    await db.flush()
    return await card_for(db, shipment.id, now)


@router.post("/shipments/{shipment_id}/invoice")
async def register_invoice(shipment_id: str, body: InvoiceRegistration, db: Session, now: Now) -> Card:
    """Attach carrier details and move the parcel into transit."""
    shipment = await locked(db, ShipmentRow, shipment_id, body.expected_revision)
    if shipment.status != "invoice_pending":
        raise invalid_transition()
    shipment.carrier = required_text(body.carrier)
    shipment.tracking_number = required_text(body.tracking_number)
    shipment.status = "in_transit"
    shipment.shipped_at = now
    shipment.expected_arrival_on = now.date() + ESTIMATED_TRANSIT
    shipment.revision += 1
    await db.flush()
    return await card_for(db, shipment.id, now)


@router.post("/shipments/{shipment_id}/deliver")
async def mark_delivered(shipment_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Record delivery and complete the order in the same transaction."""
    shipment = await locked(db, ShipmentRow, shipment_id, body.expected_revision)
    if shipment.status != "in_transit":
        raise invalid_transition()
    order = await db.get_one(OrderRow, shipment.order_id, with_for_update=True)
    shipment.status = "delivered"
    shipment.delivered_at = now
    shipment.revision += 1
    order.status = "completed"
    order.revision += 1
    await db.flush()
    return await card_for(db, shipment.id, now)
