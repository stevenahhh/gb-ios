"""Rule detectors for the proactive assistant.

Every detector reads the business tables and never calls a model. A finding names one row, says in
Korean why it needs the owner, and suggests one tool. Only a draft may run without the owner's turn;
everything that touches money, parcels, or a customer waits for the owner as a proposal.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Final, Literal, assert_never

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_findings import Finding
from agent_settings import MAX_DAILY_CAP
from agent_types import TargetRef
from b_k06_models import CancellationCaseRow, SessionPlanRow
from b_k06_policy import iso
from b_k06_sessions import UnderMinCard, under_min_cards
from b_k14 import row_view
from b_k14_models import OutreachQuoteRow
from b_k25_tables import GroundingRow, JudgmentRow
from bookings import seats_taken
from display import clock, local, masked, month_day_weekday, next_day_start, relative_moment, won
from metrics import to_send
from models import BookingRow, ClassSessionRow, CustomerRow, InquiryRow, OrderRow, ShipmentRow

type ParcelKind = Literal["parcel_unpacked", "invoice_missing"]

LOGGER: Final = logging.getLogger("roundup.agent")
CONFIRM_AFTER: Final = timedelta(hours=3)
REPLY_AFTER: Final = timedelta(hours=2)
DEPOSIT_AHEAD: Final = timedelta(hours=24)
CLASS_AHEAD: Final = timedelta(hours=24)
ANSWER_AFTER: Final = timedelta(days=3)
# At most one daily cap of targets is raised per day, so twice that leaves fresh rows past today's.
PER_DETECTOR: Final = 2 * MAX_DAILY_CAP
VISIBLE: Final = r"\S"
PARCEL_STATUS: Final[Mapping[ParcelKind, str]] = MappingProxyType({
    "parcel_unpacked": "packing", "invoice_missing": "invoice_pending",
})


def hours_since(moment: datetime, now: datetime) -> int:
    """Count whole hours passed."""
    return int((now - moment).total_seconds() // 3600)


async def unconfirmed_orders(db: AsyncSession, now: datetime) -> list[Finding]:
    """Paid orders nobody confirmed within three hours."""
    rows = await db.execute(
        select(OrderRow, CustomerRow.name).join(CustomerRow, CustomerRow.id == OrderRow.customer_id)
        .where(OrderRow.status == "paid", OrderRow.ordered_at <= now - CONFIRM_AFTER)
        .order_by(OrderRow.ordered_at, OrderRow.id).limit(PER_DETECTOR),
    )
    return [
        Finding(
            kind="order_unconfirmed", day=local(now).date(),
            target=TargetRef("order", order.id, f"#{order.order_number}", order.revision),
            title=f"#{order.order_number} 주문 확인",
            reason=(
                f"결제하고 {hours_since(order.ordered_at, now)}시간이 지났는데 "
                "아직 주문을 확인하지 않았어요."
            ),
            preview=(
                ("상품", order.product_name), ("주문자", masked(name)),
                ("수량", f"{order.quantity}개"), ("결제금액", won(order.amount_won)),
            ),
            args={"order": str(order.order_number)},
        )
        for order, name in rows.tuples()
    ]


async def unsent_parcels(
    db: AsyncSession, now: datetime, kind: ParcelKind, *pickup: ColumnElement[bool],
) -> list[Finding]:
    """Parcels of one step whose pickup meets the conditions, earliest pickup first."""
    rows = await db.execute(
        select(ShipmentRow, OrderRow, CustomerRow.name)
        .join(OrderRow, OrderRow.id == ShipmentRow.order_id)
        .join(CustomerRow, CustomerRow.id == OrderRow.customer_id)
        .where(*pickup, ShipmentRow.status == PARCEL_STATUS[kind])
        .order_by(ShipmentRow.ship_by_at, ShipmentRow.id).limit(PER_DETECTOR),
    )
    return [parcel_finding(kind, (shipment, order, name), now) for shipment, order, name in rows.tuples()]


def parcel_finding(kind: ParcelKind, parcel: tuple[ShipmentRow, OrderRow, str], now: datetime) -> Finding:
    """Describe one parcel that has not moved on, and when its pickup is or was."""
    shipment, order, name = parcel
    pickup = relative_moment(shipment.ship_by_at, local(now).date())
    missed = shipment.ship_by_at < now
    match kind:
        case "parcel_unpacked":
            title = f"#{order.order_number} 포장 다 됐나요"
            reason = (
                f"택배 가져갈 때가 {pickup}이었는데 포장이 아직이에요." if missed
                else f"{pickup}에 택배가 나가요. 포장은 아직이에요."
            )
        case "invoice_missing":
            title = f"#{order.order_number} 송장 넣기"
            reason = (
                f"포장은 끝났어요. 송장번호만 비어 있어요. 기사님 방문은 {pickup}이었어요." if missed
                else f"포장은 끝났어요. 송장번호만 비어 있어요. {pickup}에 택배가 나가요."
            )
        case _:
            assert_never(kind)
    return Finding(
        kind=kind, day=local(now).date(),
        target=TargetRef("shipment", shipment.id, f"#{order.order_number}", shipment.revision),
        title=title, reason=reason,
        preview=(
            ("상품", order.product_name), ("받는 분", masked(name)),
            ("수량", f"{order.quantity}개"), ("택배 수거", pickup),
        ),
        args={"order": str(order.order_number)},
    )


async def unpacked_parcels(db: AsyncSession, now: datetime) -> list[Finding]:
    """Parcels due today or earlier that nobody packed."""
    return await unsent_parcels(db, now, "parcel_unpacked", *to_send(local(now).date()))


async def parcels_without_invoice(db: AsyncSession, now: datetime) -> list[Finding]:
    """Packed parcels due today or earlier that have no tracking number."""
    return await unsent_parcels(db, now, "invoice_missing", *to_send(local(now).date()))


async def later_parcels_without_invoice(db: AsyncSession, now: datetime) -> list[Finding]:
    """Packed parcels for a later day that have no tracking number."""
    later = ShipmentRow.ship_by_at >= next_day_start(local(now).date())
    return await unsent_parcels(db, now, "invoice_missing", later)


async def deposits_due(db: AsyncSession, now: datetime) -> list[Finding]:
    """Deposits due within 24 hours, or already late, for classes that have not started."""
    today = local(now).date()
    rows = await db.execute(
        select(BookingRow, ClassSessionRow, CustomerRow.name)
        .join(ClassSessionRow, ClassSessionRow.id == BookingRow.session_id)
        .join(CustomerRow, CustomerRow.id == BookingRow.customer_id)
        .where(
            BookingRow.status == "deposit_pending", BookingRow.deposit_due_at <= now + DEPOSIT_AHEAD,
            ClassSessionRow.status == "scheduled", ClassSessionRow.starts_at > now,
        )
        .order_by(BookingRow.deposit_due_at, BookingRow.id).limit(PER_DETECTOR),
    )
    findings: list[Finding] = []
    for booking, session, name in rows.tuples():
        deposit_due = booking.deposit_due_at or now
        when = relative_moment(deposit_due, today)
        starts = local(session.starts_at)
        findings.append(Finding(
            kind="deposit_due", day=today,
            target=TargetRef(
                "booking", booking.id, f"{masked(name)} 님 · {session.title}", booking.revision,
            ),
            title=f"{session.title} 예약금 확인",
            reason=(
                f"입금 마감을 넘겼어요. 예약금은 아직 확인 전이에요. 마감은 {when}이었어요."
                if deposit_due < now
                else f"예약금은 {when}까지 받기로 했는데 입금 확인을 아직 안 하셨어요."
            ),
            preview=(
                ("수업", f"{month_day_weekday(starts.date())}요일 {clock(starts)}"),
                ("예약자", f"{masked(name)} · {booking.party_size}명"),
                ("예약금", won(booking.deposit_won)), ("입금 마감", when),
            ),
            args={"booking": session.title},
        ))
    return findings


async def undrafted_inquiries(db: AsyncSession, now: datetime) -> list[Finding]:
    """Inquiries waiting over two hours with no draft and no question already asked of the owner.

    The grounded engine keeps its draft in its own table, and an open judgment means the engine asked
    the owner, so neither is an inquiry nobody looked at.
    """
    drafted = exists(select(GroundingRow.inquiry_id).where(
        GroundingRow.inquiry_id == InquiryRow.id, GroundingRow.generated_draft.regexp_match(VISIBLE),
    ))
    asked = exists(select(JudgmentRow.id).where(
        JudgmentRow.inquiry_id == InquiryRow.id, JudgmentRow.status == "open",
    ))
    rows = await db.scalars(
        select(InquiryRow)
        .where(
            InquiryRow.status == "pending", InquiryRow.received_at <= now - REPLY_AFTER,
            ~InquiryRow.draft.regexp_match(VISIBLE), ~drafted, ~asked,
        )
        .order_by(InquiryRow.received_at, InquiryRow.id).limit(PER_DETECTOR),
    )
    today = local(now).date()
    return [
        Finding(
            kind="inquiry_undrafted", day=today,
            target=TargetRef("inquiry", row.id, f"{masked(row.customer)} 님 질문", row.revision),
            title=f"{masked(row.customer)} 님께 미리 쓴 답장",
            reason=f"물어보신 지 {hours_since(row.received_at, now)}시간째 답장을 아직 못 썼어요.",
            preview=(("받은 시간", relative_moment(row.received_at, today)),),
            args={"inquiry": row.customer},
        )
        for row in rows
    ]


async def under_min_classes(db: AsyncSession, now: datetime) -> list[Finding]:
    """Classes below their smallest size, shown from the evening before their material deadline."""
    today = local(now).date()
    return [
        class_finding(
            card,
            f"재료는 {due}까지 사야 해요.",
            now,
        )
        for card in await under_min_cards(db, now)
        for due in (relative_moment(local(datetime.fromisoformat(card.order_deadline)), today),)
    ]


async def under_min_classes_without_deadline(db: AsyncSession, now: datetime) -> list[Finding]:
    """Classes below their smallest size with no material deadline, from a day before they start."""
    today = local(now).date()
    decided = select(CancellationCaseRow.session_id).where(
        CancellationCaseRow.kind == "under_min", CancellationCaseRow.decision == "run",
    )
    rows = await db.execute(
        select(ClassSessionRow, seats_taken(), SessionPlanRow.min_seats)
        .join(SessionPlanRow, SessionPlanRow.session_id == ClassSessionRow.id)
        .where(
            ClassSessionRow.status == "scheduled", ClassSessionRow.starts_at > now,
            ClassSessionRow.starts_at <= now + CLASS_AHEAD, ClassSessionRow.id.not_in(decided),
            SessionPlanRow.material_order_deadline.is_(None), seats_taken() < SessionPlanRow.min_seats,
        )
        .order_by(ClassSessionRow.starts_at, ClassSessionRow.id).limit(PER_DETECTOR),
    )
    return [
        class_finding(
            UnderMinCard(
                session_id=session.id, class_name=session.title, starts_at=iso(session.starts_at),
                revision=session.revision, booked=booked, min_seats=min_seats,
                order_deadline=iso(session.starts_at), material_won=None, merge_candidates=[],
            ),
            f"수업은 {relative_moment(session.starts_at, today)}에 시작해요.",
            now,
        )
        for session, booked, min_seats in rows.tuples() if min_seats is not None
    ]


def class_finding(card: UnderMinCard, when: str, now: datetime) -> Finding:
    """Describe one class below its smallest size; the reminder goes at its deadline."""
    starts = local(datetime.fromisoformat(card.starts_at))
    deadline_at = local(datetime.fromisoformat(card.order_deadline))
    return Finding(
        kind="class_under_min", day=local(now).date(),
        target=TargetRef("session", card.session_id, card.class_name),
        title=f"{card.class_name} 수업 열지 정해 주세요",
        reason=f"예약 인원이 {card.booked}명뿐이라 최소 {card.min_seats}명이 안 돼요. {when}",
        preview=(
            ("수업", f"{month_day_weekday(starts.date())}요일 {clock(starts)}"),
            ("예약", f"{card.booked}명"), ("최소 인원", f"{card.min_seats}명"),
        ),
        args={
            "title": f"{card.class_name} 수업 열지 정해 주세요", "day": deadline_at.date().isoformat(),
            "time": clock(deadline_at), "detail": f"예약 {card.booked}명, 최소 인원 {card.min_seats}명",
        },
    )


async def waiting_quotes(db: AsyncSession, now: datetime) -> list[Finding]:
    """Sent quotes with no recorded answer after the agreed follow-up time, or after three days without one.

    The row keeps no sending time; its last change is never earlier, so the wait is never cut short.
    """
    today = local(now).date()
    waiting_since = func.coalesce(OutreachQuoteRow.follow_up_at, OutreachQuoteRow.updated_at + ANSWER_AFTER)
    rows = await db.scalars(
        select(OutreachQuoteRow)
        .where(OutreachQuoteRow.status == "sent", waiting_since <= now)
        .order_by(waiting_since, OutreachQuoteRow.id).limit(PER_DETECTOR),
    )
    findings: list[Finding] = []
    for row in rows:
        try:
            view = row_view(row, now)
        except ValueError as error:
            LOGGER.warning("agent_quote_unreadable", extra={"error_type": type(error).__name__})
            continue
        days = (now - row.updated_at).days
        findings.append(Finding(
            kind="quote_waiting", day=today,
            target=TargetRef("quote", row.id, view.title, row.revision),
            title=f"{view.title} 견적 답변 적기",
            reason=(
                "기관에 다시 연락할 날이 지났어요. 답을 받으셨다면 적어 주세요."
                if row.follow_up_at is not None
                else f"견적 보내고 {days}일째 기관 답변 칸이 비어 있어요."
            ),
            preview=(("내용", view.detail), ("견적", won(view.total_krw))),
            args={"quote": view.title},
        ))
    return findings


type Detector = Callable[[AsyncSession, datetime], Awaitable[list[Finding]]]
DETECTORS: Final[tuple[Detector, ...]] = (
    unpacked_parcels, parcels_without_invoice, deposits_due, under_min_classes,
    under_min_classes_without_deadline, unconfirmed_orders, undrafted_inquiries, waiting_quotes,
    later_parcels_without_invoice,
)


async def detect(db: AsyncSession, now: datetime) -> list[Finding]:
    """Run every detector; kinds with a deadline today come first."""
    found: list[Finding] = []
    for detector in DETECTORS:
        found.extend(await detector(db, now))
    return found
