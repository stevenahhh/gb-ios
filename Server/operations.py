"""Operations tab: attention counts and monthly numbers with defined meanings."""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common import Now, Session
from contracts import ApiModel, Metric
from display import count, day_start, month_start, next_month, previous_month
from metrics import counted, integers, load_counts, metric
from models import BookingRow, ClassSessionRow, ContentDraftRow, InquiryRow, OrderRow, ShipmentRow

router = APIRouter()
MONTHS_SHOWN: Final = 6
type Area = Literal["bookings", "orders", "deliveries", "channels"]


class AreaSummary(ApiModel):
    """The row count beside one work area."""

    area: Area
    display: str


class MonthOption(ApiModel):
    """A selectable reporting month."""

    key: str
    title: str
    range: str


class Comparison(ApiModel):
    """Change from the previous month; absent without a baseline."""

    label: str
    display: str


class Period(ApiModel):
    """Monthly summary."""

    month: MonthOption
    handled: int
    total: int
    rate_percent: int | None
    rate_display: str
    metrics: list[Metric]
    comparisons: list[Comparison]


class Operations(ApiModel):
    """Everything shown on the operations tab."""

    attention_count: int
    attention: list[Metric]
    period: Period
    months: list[MonthOption]
    areas: list[AreaSummary]


@dataclass(frozen=True, slots=True)
class MonthNumbers:
    """Rows attributed to one month and how many are handled."""

    bookings: int
    bookings_handled: int
    orders: int
    orders_handled: int
    shipments: int
    shipments_handled: int
    inquiries: int
    inquiries_handled: int
    drafts: int

    @property
    def total(self) -> int:
        """Count all work items in the processing rate."""
        return self.bookings + self.orders + self.shipments + self.inquiries

    @property
    def handled(self) -> int:
        """Count work items that need no further owner action."""
        return self.bookings_handled + self.orders_handled + self.shipments_handled + self.inquiries_handled


def month_option(first: date) -> MonthOption:
    """Describe a month for the period menu."""
    last = next_month(first).toordinal() - 1
    end = date.fromordinal(last)
    return MonthOption(
        key=first.strftime("%Y-%m"),
        title=f"{first.month}월",
        range=f"{first:%m.%d} – {end:%m.%d}",  # noqa: RUF001
    )


async def month_numbers(db: AsyncSession, first: date) -> MonthNumbers:
    """Count one month's work from its defining timestamps."""
    begin, end = day_start(first), day_start(next_month(first))
    in_month = (ClassSessionRow.starts_at >= begin, ClassSessionRow.starts_at < end)
    booked = (
        select(func.count())
        .select_from(BookingRow)
        .join(ClassSessionRow, ClassSessionRow.id == BookingRow.session_id)
        .where(*in_month)
    )
    orders = (OrderRow.ordered_at >= begin, OrderRow.ordered_at < end, OrderRow.status != "cancelled")
    shipments = (ShipmentRow.ship_by_at >= begin, ShipmentRow.ship_by_at < end)
    inquiries = (InquiryRow.received_at >= begin, InquiryRow.received_at < end)
    values = await integers(
        db,
        [
            booked.where(BookingRow.status != "cancelled").scalar_subquery(),
            booked.where(BookingRow.status == "confirmed").scalar_subquery(),
            counted(OrderRow, *orders),
            counted(OrderRow, *orders, OrderRow.status != "paid"),
            counted(ShipmentRow, *shipments),
            counted(ShipmentRow, *shipments, ShipmentRow.status.in_(("in_transit", "delivered"))),
            counted(InquiryRow, *inquiries),
            counted(InquiryRow, *inquiries, InquiryRow.status != "pending"),
            counted(ContentDraftRow, ContentDraftRow.created_at >= begin, ContentDraftRow.created_at < end),
        ],
    )
    return MonthNumbers(*values)


def change(current: int, previous: int) -> str:
    """Format month-over-month change, or a dash without a baseline."""
    if previous == 0:
        return "—"
    return f"{round((current - previous) * 100 / previous):+d}%"


@router.get("/operations")
async def operations(
    db: Session,
    now: Now,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> Operations:
    """Build attention counts, the selected month, and area totals."""
    today = now.date()
    current_month = month_start(today)
    options = [current_month]
    for _ in range(MONTHS_SHOWN - 1):
        options.append(previous_month(options[-1]))
    selected = date.fromisoformat(f"{month}-01") if month else current_month
    counts = await load_counts(db, today)
    numbers = await month_numbers(db, selected)
    baseline = await month_numbers(db, previous_month(selected))
    rate = round(numbers.handled * 100 / numbers.total) if numbers.total else None
    return Operations(
        attention_count=counts.attention,
        attention=[
            metric("depositPending", "예약금 미확인", counts.deposit_pending),
            metric("pendingInquiries", "미답변 문의", counts.pending_inquiries),
            metric("unshipped", "발송 대기", counts.unshipped),
        ],
        period=Period(
            month=month_option(selected),
            handled=numbers.handled,
            total=numbers.total,
            rate_percent=rate,
            rate_display="—" if rate is None else f"{rate}%",
            metrics=[
                metric("bookings", "예약", numbers.bookings),
                metric("orders", "주문", numbers.orders),
                metric("shipments", "배송", numbers.shipments),
                metric("drafts", "콘텐츠", numbers.drafts),
            ],
            comparisons=[
                Comparison(label="예약 전월 대비", display=change(numbers.bookings, baseline.bookings)),
                Comparison(label="주문 전월 대비", display=change(numbers.orders, baseline.orders)),
            ],
        ),
        months=[month_option(first) for first in options],
        areas=[
            AreaSummary(area="bookings", display=count(counts.bookings)),
            AreaSummary(area="orders", display=count(counts.orders)),
            AreaSummary(
                area="deliveries", display=count(counts.unshipped + counts.in_transit + counts.delivered),
            ),
            AreaSummary(area="channels", display=f"{counts.channels:,}개"),
        ],
    )
