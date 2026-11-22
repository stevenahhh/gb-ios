"""Rows of one small workshop for the proactive tests, placed at fixed Seoul moments."""

from datetime import datetime, time, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agent_settings import load_settings
from agent_settings_edit import SettingsUpdate, update_settings
from b_k06_models import CancellationCaseRow, SessionPlanRow
from b_k14 import QuoteFields, QuoteInputs
from b_k14_calc import Calculation
from b_k14_models import OutreachQuoteRow
from b_k25_tables import GroundingRow, JudgmentRow
from database import Base, transaction
from display import SEOUL
from models import BookingRow, ClassSessionRow, CustomerRow, InquiryRow, OrderRow, ShipmentRow

NOW: Final = datetime(2026, 11, 22, 11, 0, tzinfo=SEOUL)
CUSTOMER: Final = "customer-proactive"
HOUR: Final = timedelta(hours=1)
MINUTE: Final = timedelta(minutes=1)
SHIPPED: Final = ("in_transit", "delivered")


async def store(engine: AsyncEngine, *rows: Base) -> None:
    """Insert rows one by one, parents first, in one transaction."""
    async with async_sessionmaker(engine)() as db, db.begin():
        for row in rows:
            db.add(row)
            await db.flush()


async def set_settings(**fields: object) -> None:
    """Save settings the way the owner's screen does."""
    async with transaction() as db:
        settings = await load_settings(db)
        assert settings is not None
        body = SettingsUpdate.model_validate({"expectedRevision": settings.revision, **fields})
        _ = await update_settings(db, body, NOW)


def customer(name: str = "김하윤") -> CustomerRow:
    return CustomerRow(id=CUSTOMER, name=name, phone=None)


def order(key: str, number: int, *, ordered_at: datetime, status: str = "paid") -> OrderRow:
    return OrderRow(
        id=f"order-{key}", order_number=number, customer_id=CUSTOMER, channel_id=None,
        product_name="머그컵", quantity=1, amount_won=32000, status=status, ordered_at=ordered_at,
    )


def shipment(key: str, *, ship_by_at: datetime, status: str = "packing") -> ShipmentRow:
    return ShipmentRow(
        id=f"shipment-{key}", order_id=f"order-{key}", status=status, ship_by_at=ship_by_at,
        carrier="CJ대한통운" if status in SHIPPED else None,
        tracking_number="123456789012" if status in SHIPPED else None,
    )


def parcel(
    key: str, number: int, *, ship_by_at: datetime, status: str = "packing",
) -> tuple[OrderRow, ShipmentRow]:
    return (
        order(key, number, ordered_at=NOW - 6 * HOUR, status="processing"),
        shipment(key, ship_by_at=ship_by_at, status=status),
    )


def session(
    key: str, *, starts_at: datetime, capacity: int = 6, status: str = "scheduled",
) -> ClassSessionRow:
    return ClassSessionRow(
        id=f"session-{key}", title="도자기 원데이 클래스", starts_at=starts_at, duration_minutes=90,
        capacity=capacity, deposit_won=20000, status=status,
    )


def booking(
    key: str, session_key: str, *, due: datetime | None, status: str = "deposit_pending", people: int = 1,
) -> BookingRow:
    return BookingRow(
        id=f"booking-{key}", session_id=f"session-{session_key}", customer_id=CUSTOMER, channel_id=None,
        party_size=people, status=status, deposit_won=20000, deposit_due_at=due,
    )


def inquiry(key: str, *, received_at: datetime, draft: str = "", status: str = "pending") -> InquiryRow:
    return InquiryRow(
        id=f"inquiry-{key}", customer="박지은", subject="문의", question="토요일 가능한가요?", facts=[],
        draft=draft, status=status, revision=0, received_at=received_at,
    )


def grounding(key: str, draft: str | None) -> GroundingRow:
    return GroundingRow(inquiry_id=f"inquiry-{key}", ab_arm="grounded", generated_draft=draft)


def judgment(key: str, status: str = "open") -> JudgmentRow:
    return JudgmentRow(
        id=f"judgment-{key}", inquiry_id=f"inquiry-{key}", issue="환불 기준을 알려 주세요", status=status,
    )


def plan(key: str, *, min_seats: int | None, deadline: datetime | None) -> SessionPlanRow:
    return SessionPlanRow(
        session_id=f"session-{key}", min_seats=min_seats, material_order_deadline=deadline,
        material_won=None,
    )


def run_decision(key: str) -> CancellationCaseRow:
    return CancellationCaseRow(
        id=f"case-{key}", workshop_id=1, booking_id=None, session_id=f"session-{key}", kind="under_min",
        computed={}, decision="run", reason="진행하기로 했어요", draft="", decided_at=NOW,
    )


def snapshot() -> Calculation:
    return Calculation(
        lines=[], total_krw=500000, per_person_krw=25000, base_instructor_krw=0, instructor_gap_krw=0,
        minimum_applied=False, outreach_minutes=120, travel_unknown=True, net_per_person_outreach=None,
        net_per_person_oneday=None, net_per_hour_outreach=None, net_per_hour_oneday=None,
        baseline_krw=None, verdict="unknown", suggestion="unknown", break_even_headcount=None,
        max_headcount=None, needed_total_krw=None, tier_prices=[], outreach_basis="", oneday_basis="",
    )


def quote(
    key: str, *, follow_up_at: datetime | None, status: str = "sent", outcome: str | None = None,
) -> OutreachQuoteRow:
    return OutreachQuoteRow(
        id=f"quote-{key}", status=status, class_id="도자기 원데이 클래스",
        fields=QuoteFields(org_name="한빛초등학교", date="2026-12-12").model_dump(mode="json"),
        inputs=QuoteInputs(headcount=20).model_dump(mode="json"), signals=[], locked=False,
        snapshot=snapshot().model_dump(mode="json"), missing_costs=[], follow_up_at=follow_up_at,
        outcome=outcome, ab_arm="A",
    )


def seoul(hour: int, minute: int = 0, *, day: int = 22) -> datetime:
    """Return a moment of November 2026 on the workshop clock."""
    return datetime.combine(datetime(2026, 11, day, tzinfo=SEOUL).date(), time(hour, minute), SEOUL)
