"""Operations tab: attention counts and monthly numbers with defined meanings."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, Final, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common import Now, Session
from contracts import ApiModel, CardDue, Metric
from display import (
    count,
    day_start,
    due,
    local,
    masked,
    month_start,
    next_day_start,
    next_month,
    previous_month,
    relative_day,
    relative_moment,
)
from metrics import counted, integers, load_counts, metric, to_send
from models import BookingRow, ClassSessionRow, CustomerRow, InquiryRow, OrderRow, ShipmentRow

router = APIRouter()
MONTHS_SHOWN: Final = 6
MAX_RANGE_DAYS: Final = 366
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


async def month_numbers(db: AsyncSession, first: date, stop: date | None = None) -> MonthNumbers:
    """Count work in a half-open range, defaulting to one calendar month."""
    begin, end = day_start(first), day_start(stop or next_month(first))
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
        ],
    )
    return MonthNumbers(*values)


def change(current: int, previous: int) -> str:
    """Format month-over-month change, or a dash without a baseline."""
    if previous == 0:
        return "—"
    return f"{round((current - previous) * 100 / previous):+d}%"


def compared(current: int, previous: int, since: str) -> str:
    """Describe a count change in items, which reads better than a percentage."""
    diff = current - previous
    return f"{since}보다 {diff:+d}건" if diff else f"{since}과 같아요"


async def attention_details(
    db: AsyncSession, today: date,
) -> tuple[str | None, str | None, str | None, CardDue | None]:
    """Name the first deposit, drafted inquiries, and the earliest pickup behind each count."""
    deposits = (
        await db.execute(
            select(ClassSessionRow.starts_at, CustomerRow.name)
            .join(BookingRow, BookingRow.session_id == ClassSessionRow.id)
            .join(CustomerRow, CustomerRow.id == BookingRow.customer_id)
            .where(BookingRow.status == "deposit_pending")
            .order_by(ClassSessionRow.starts_at, BookingRow.id),
        )
    ).tuples().all()
    deposit = None
    if deposits:
        starts_at, name = deposits[0]
        others = f" 외 {len(deposits) - 1}명" if len(deposits) > 1 else ""
        deposit = f"{relative_day(local(starts_at).date(), today)} {masked(name)} 님{others}"
    drafted = await db.scalar(
        select(func.count()).select_from(InquiryRow)
        .where(InquiryRow.status == "pending", func.btrim(InquiryRow.draft) != ""),
    ) or 0
    pickup = await db.scalar(select(func.min(ShipmentRow.ship_by_at)).where(*to_send(today)))
    return (
        deposit,
        f"비서 초안 {drafted}건 준비됨" if drafted else None,
        f"{relative_moment(pickup, today)} 택배 수거" if pickup else None,
        due(pickup, suffix=" 택배 수거", missed="수거 놓침") if pickup else None,
    )


@router.get("/operations")
async def operations(
    db: Session,
    now: Now,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> Operations:
    """Build attention counts, the selected month, and area totals."""
    today = now.date()
    current_month = month_start(today)
    options = [current_month]
    for _ in range(MONTHS_SHOWN - 1):
        options.append(previous_month(options[-1]))
    selected = date.fromisoformat(f"{month}-01") if month else current_month
    counts = await load_counts(db, today)
    if (start is None) != (end is None) or (month is not None and start is not None):
        raise HTTPException(422, "provide either month or both start and end")
    option = month_option(selected)
    comparison_period, since = "전월", "지난달"
    if start is not None and end is not None:
        span = (end - start).days + 1
        if span < 1 or span > MAX_RANGE_DAYS or start.toordinal() <= span or end == date.max:
            raise HTTPException(422, "date range must be ascending and at most 366 days")
        numbers = await month_numbers(db, start, next_day_start(end).date())
        baseline = await month_numbers(db, start - timedelta(days=span), start)
        option = MonthOption(
            key="custom", title="선택 기간", range=f"{start:%m.%d} – {end:%m.%d}",  # noqa: RUF001
        )
        comparison_period, since = "이전 기간", "이전 기간"
    else:
        numbers = await month_numbers(db, selected)
        baseline = await month_numbers(db, previous_month(selected))
    rate = round(numbers.handled * 100 / numbers.total) if numbers.total else None
    deposit, drafted, pickup, pickup_due = await attention_details(db, today)
    return Operations(
        attention_count=counts.attention,
        attention=[
            metric("depositPending", "예약금 미확인", counts.deposit_pending, deposit),
            metric("pendingInquiries", "답변 기다리는 문의", counts.pending_inquiries, drafted),
            Metric(
                key="unshipped", label="발송 대기", value=counts.ship_due_today,
                display=count(counts.ship_due_today), detail=pickup, due=pickup_due,
            ),
        ],
        period=Period(
            month=option,
            handled=numbers.handled,
            total=numbers.total,
            rate_percent=rate,
            rate_display="—" if rate is None else f"{rate}%",
            metrics=[
                metric(
                    "bookings", "예약", numbers.bookings,
                    compared(numbers.bookings, baseline.bookings, since),
                ),
                metric(
                    "orders", "주문", numbers.orders, compared(numbers.orders, baseline.orders, since),
                ),
                metric(
                    "shipments", "배송", numbers.shipments,
                    f"발송 대기 {numbers.shipments - numbers.shipments_handled:,}건",
                ),
                metric(
                    "inquiries", "문의", numbers.inquiries,
                    f"답변 기다리는 문의 {numbers.inquiries - numbers.inquiries_handled:,}건",
                ),
            ],
            comparisons=[
                Comparison(
                    label=f"예약 {comparison_period} 대비",
                    display=change(numbers.bookings, baseline.bookings),
                ),
                Comparison(
                    label=f"주문 {comparison_period} 대비", display=change(numbers.orders, baseline.orders),
                ),
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
