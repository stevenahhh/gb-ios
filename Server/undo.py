"""Revision-checked reversals of owner actions, with no external side effects."""

from fastapi import APIRouter
from sqlalchemy import select

from bookings import DEPOSIT_WINDOW, ExpectedRevision
from bookings import card_for as booking_card
from common import Now, Session, invalid_transition, locked
from contracts import Card
from models import BookingRow, ClassSessionRow, OrderRow, ShipmentRow, TaskRow
from orders import card_for as order_card
from shipments import card_for as shipment_card
from tasks import task_card

router = APIRouter()


@router.post("/bookings/{booking_id}/undo-deposit")
async def undo_deposit(booking_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Restore deposit attention while preserving an existing deadline."""
    booking = await locked(db, BookingRow, booking_id, body.expected_revision)
    if booking.status != "confirmed" or booking.deposit_won <= 0:
        raise invalid_transition()
    session = await db.get_one(ClassSessionRow, booking.session_id)
    booking.status = "deposit_pending"
    booking.deposit_confirmed_at = None
    booking.deposit_due_at = booking.deposit_due_at or min(now + DEPOSIT_WINDOW, session.starts_at)
    booking.revision += 1
    await db.flush()
    return await booking_card(db, booking.id, now)


@router.post("/orders/{order_id}/undo-confirm")
async def undo_confirm(order_id: str, body: ExpectedRevision, db: Session) -> Card:
    """Undo acceptance only while fulfilment is still packing."""
    # Fulfilment writers acquire shipment before order; keep that lock order here.
    shipment = await db.scalar(
        select(ShipmentRow).where(ShipmentRow.order_id == order_id).with_for_update(),
    )
    order = await locked(db, OrderRow, order_id, body.expected_revision)
    if order.status != "processing" or shipment is None or shipment.status != "packing":
        raise invalid_transition()
    order.status = "paid"
    order.confirmed_at = None
    order.revision += 1
    await db.delete(shipment)
    await db.flush()
    return await order_card(db, order.id)


@router.post("/shipments/{shipment_id}/undo")
async def undo_shipment(shipment_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Move fulfilment back exactly one step and clear that step's facts."""
    shipment = await locked(db, ShipmentRow, shipment_id, body.expected_revision)
    match shipment.status:
        case "delivered":
            order = await db.get_one(OrderRow, shipment.order_id, with_for_update=True)
            shipment.status = "in_transit"
            shipment.delivered_at = None
            if order.status == "completed":
                order.status = "processing"
                order.revision += 1
        case "in_transit":
            shipment.status = "invoice_pending"
            shipment.carrier = None
            shipment.tracking_number = None
            shipment.shipped_at = None
            shipment.expected_arrival_on = None
        case "invoice_pending":
            shipment.status = "packing"
            shipment.packed_at = None
        case _:
            raise invalid_transition()
    shipment.revision += 1
    await db.flush()
    return await shipment_card(db, shipment.id, now)


@router.post("/tasks/{task_id}/undo")
async def undo_task(task_id: str, body: ExpectedRevision, db: Session, now: Now) -> Card:
    """Restore an unfinished task without changing its due date."""
    task = await locked(db, TaskRow, task_id, body.expected_revision)
    if task.status != "done":
        raise invalid_transition()
    task.status = "open"
    task.completed_at = None
    task.revision += 1
    await db.flush()
    return task_card(task, now.date())
