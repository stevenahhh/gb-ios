"""Detail reads for booking, class, and work cards."""

from typing import Literal, assert_never

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from bookings import SessionState, booking_card, booking_records, schedule_text
from common import Now, Session
from contracts import ApiModel, Card, CardAction, CardDue, CardUndo, Status
from display import local, masked, won
from models import BookingRow, ChannelRow, ClassSessionRow, OrderRow, ShipmentRow, TaskRow
from orders import order_card, order_records
from shipments import shipment_card, shipment_records
from tasks import task_card

router = APIRouter()
type DetailKind = Literal["order", "shipment", "task"]


class BookingDetail(ApiModel):
    """Booking facts and the enclosing class's completion revision."""

    id: str
    title: str
    status: Status | None
    schedule: str
    customer: str
    people: int
    minutes: int
    source: str
    seat_note: str | None
    deposit_display: str
    deposit_confirmed: bool
    deposit_deadline: str | None
    deposit_due: CardDue | None = None
    revision: int
    action: CardAction | None
    undo: CardUndo | None
    session: SessionState


class ClassDetail(SessionState):
    """A class with active bookings ordered by their creation."""

    title: str
    schedule: str
    booking_ids: list[str]


@router.get("/bookings/{booking_id}")
async def booking_detail(booking_id: str, db: Session, now: Now) -> BookingDetail:
    """Read booking details without exposing the customer's full name."""
    record = (
        await db.execute(booking_records().where(BookingRow.id == booking_id))
    ).tuples().one_or_none()
    if record is None:
        raise HTTPException(404, "resource not found")
    booking, session, customer, taken = record
    card = booking_card(record, now)
    channel = await db.get(ChannelRow, booking.channel_id) if booking.channel_id else None
    return BookingDetail(
        id=booking.id, title=card.title, status=card.status, schedule=schedule_text(session),
        customer=masked(customer.name), people=booking.party_size, minutes=session.duration_minutes,
        source=channel.name if channel else "직접 입력",
        seat_note=f"남은 자리 {max(session.capacity - taken, 0)}개",
        deposit_display=won(booking.deposit_won), deposit_confirmed=booking.status == "confirmed",
        deposit_deadline=card.deadline, deposit_due=card.due,
        revision=booking.revision, action=card.action, undo=card.undo,
        session=SessionState(
            id=session.id, is_done=session.status == "completed", revision=session.revision,
            starts_at=local(session.starts_at).isoformat(timespec="seconds"),
        ),
    )


@router.get("/class-sessions/{session_id}")
async def class_detail(session_id: str, db: Session) -> ClassDetail:
    """Read class completion and active booking identifiers."""
    session = await db.get(ClassSessionRow, session_id)
    if session is None:
        raise HTTPException(404, "resource not found")
    ids = await db.scalars(
        select(BookingRow.id)
        .where(BookingRow.session_id == session_id, BookingRow.status != "cancelled")
        .order_by(BookingRow.created_at, BookingRow.id),
    )
    return ClassDetail(
        id=session.id, title=session.title, schedule=schedule_text(session),
        is_done=session.status == "completed", revision=session.revision, booking_ids=list(ids),
        starts_at=local(session.starts_at).isoformat(timespec="seconds"),
    )


@router.get("/cards/{kind}/{card_id}")
async def card_detail(kind: DetailKind, card_id: str, db: Session, now: Now) -> Card:
    """Reload one order, shipment, or task card by its stable identifier."""
    match kind:
        case "order":
            record = (
                await db.execute(order_records().where(OrderRow.id == card_id))
            ).tuples().one_or_none()
            if record is not None:
                return order_card(record)
        case "shipment":
            shipment = (
                await db.execute(shipment_records().where(ShipmentRow.id == card_id))
            ).tuples().one_or_none()
            if shipment is not None:
                return shipment_card(shipment, now.date())
        case "task":
            task = await db.get(TaskRow, card_id)
            if task is not None:
                return task_card(task, now.date())
        case _:
            assert_never(kind)
    raise HTTPException(404, "resource not found")
