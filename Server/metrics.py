"""Aggregates shared by every screen, so equal labels always agree."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from sqlalchemy import BigInteger, ColumnElement, func, select, type_coerce
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import Metric
from database import Base
from display import count, day_start, month_start, next_day_start, next_month, won
from models import (
    BookingRow,
    ChannelRow,
    ClassSessionRow,
    ContentDraftRow,
    InquiryRow,
    OrderRow,
    ShipmentRow,
)

UNSHIPPED: Final = ("packing", "invoice_pending")


def to_send(today: date) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """Parcels to send on a day: its own pickups plus earlier ones still unsent.

    The today tab, the operations badge, and the calendar all count with this one condition.
    """
    return ShipmentRow.status.in_(UNSHIPPED), ShipmentRow.ship_by_at < next_day_start(today)


@dataclass(frozen=True, slots=True)
class Counts:
    """Current workload, independent of the requested page or filter."""

    bookings: int
    confirmed_bookings: int
    deposit_pending: int
    orders: int
    paid_orders: int
    orders_today: int
    revenue_today: int
    revenue_this_month: int
    unshipped: int
    ship_due_today: int
    in_transit: int
    arriving_today: int
    late_in_transit: int
    delivered: int
    pending_inquiries: int
    channels: int
    drafts: int
    booked_people_today: int

    @property
    def attention(self) -> int:
        """Count work the operations tab asks the owner to handle first."""
        return self.deposit_pending + self.pending_inquiries + self.ship_due_today


def counted(model: type[Base], *conditions: ColumnElement[bool]) -> ColumnElement[int]:
    """Build a scalar count over one table."""
    return select(func.count()).select_from(model).where(*conditions).scalar_subquery()


async def integers(db: AsyncSession, columns: Sequence[ColumnElement[int]]) -> list[int]:
    """Read many aggregates from one statement and therefore one snapshot."""
    values = await db.scalar(select(type_coerce(array(list(columns)), ARRAY(BigInteger()))))
    return list(values or [])


async def load_counts(db: AsyncSession, today: date) -> Counts:
    """Compute every shared number in one consistent statement."""
    day_begin, day_end = day_start(today), next_day_start(today)
    month_begin = day_start(month_start(today))
    month_end = day_start(next_month(month_start(today)))
    active_booking = BookingRow.status != "cancelled"
    active_order = OrderRow.status != "cancelled"
    today_orders = (OrderRow.ordered_at >= day_begin, OrderRow.ordered_at < day_end, active_order)
    month_orders = (OrderRow.ordered_at >= month_begin, OrderRow.ordered_at < month_end, active_order)
    transit = ShipmentRow.status == "in_transit"
    values = await integers(db, [
        counted(BookingRow, active_booking),
        counted(BookingRow, BookingRow.status == "confirmed"),
        counted(BookingRow, BookingRow.status == "deposit_pending"),
        counted(OrderRow, active_order),
        counted(OrderRow, OrderRow.status == "paid"),
        counted(OrderRow, *today_orders),
        select(func.coalesce(func.sum(OrderRow.amount_won), 0)).where(*today_orders).scalar_subquery(),
        select(func.coalesce(func.sum(OrderRow.amount_won), 0)).where(*month_orders).scalar_subquery(),
        counted(ShipmentRow, ShipmentRow.status.in_(UNSHIPPED)),
        counted(ShipmentRow, *to_send(today)),
        counted(ShipmentRow, transit),
        counted(ShipmentRow, transit, ShipmentRow.expected_arrival_on == today),
        counted(ShipmentRow, transit, ShipmentRow.expected_arrival_on < today),
        counted(ShipmentRow, ShipmentRow.status == "delivered"),
        counted(InquiryRow, InquiryRow.status == "pending"),
        counted(ChannelRow),
        counted(ContentDraftRow, ContentDraftRow.status == "draft"),
        select(func.coalesce(func.sum(BookingRow.party_size), 0))
        .join(ClassSessionRow, ClassSessionRow.id == BookingRow.session_id)
        .where(
            active_booking, ClassSessionRow.status != "cancelled",
            ClassSessionRow.starts_at >= day_begin, ClassSessionRow.starts_at < day_end,
        ).scalar_subquery(),
    ])
    return Counts(*values)


def metric(key: str, label: str, value: int, detail: str | None = None) -> Metric:
    """Build a metric counted in items."""
    return Metric(key=key, label=label, value=value, display=count(value), detail=detail)


def channel_metric(value: int) -> Metric:
    """Build the registered-channel metric, counted in places rather than cases."""
    return Metric(key="channels", label="저장한 채널", value=value, display=f"{value:,}개")


def money_metric(key: str, label: str, value: int) -> Metric:
    """Build a metric measured in won."""
    return Metric(key=key, label=label, value=value, display=won(value))


def delivery_metrics(counts: Counts) -> list[Metric]:
    """Use identical delivery numbers on the today and delivery screens."""
    return [
        metric("unshipped", "발송 예정", counts.unshipped),
        metric("inTransit", "배송 중", counts.in_transit),
        metric("delivered", "배송 완료", counts.delivered),
    ]
