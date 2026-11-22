"""Each rule fires exactly on its boundary, on the Seoul clock, and stays quiet once the state moved on."""

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agent_findings import Finding
from agent_proactive import detect
from agent_types import TargetRef
from display import SEOUL
from models import Base
from tests.agent_proactive_support import (
    HOUR,
    MINUTE,
    NOW,
    booking,
    customer,
    grounding,
    inquiry,
    judgment,
    order,
    parcel,
    plan,
    quote,
    run_decision,
    seoul,
    session,
    store,
)

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
DEADLINE: Final = seoul(12, day=23)
EVENING: Final = seoul(18)
CLASS: Final = seoul(10, day=25)
NOV_30: Final = datetime(2026, 11, 30, 23, 0, tzinfo=SEOUL)


async def findings(engine: AsyncEngine, now: datetime) -> list[Finding]:
    async with async_sessionmaker(engine)() as db:
        return await detect(db, now)


async def only(engine: AsyncEngine, now: datetime) -> Finding:
    found = await findings(engine, now)
    assert len(found) == 1, found
    return found[0]


async def test_an_empty_workshop_has_nothing_to_raise(migrated: AsyncEngine) -> None:
    assert await findings(migrated, NOW) == []


async def test_a_paid_order_is_raised_three_hours_after_payment(migrated: AsyncEngine) -> None:
    await store(migrated, customer(), order("a", 1040, ordered_at=NOW - 3 * HOUR))

    finding = await only(migrated, NOW)

    assert (finding.kind, finding.tool, finding.tier) == ("order_unconfirmed", "confirm_order", "T2")
    assert (finding.target, finding.args) == (TargetRef("order", "order-a", "#1040", 0), {"order": "1040"})
    assert finding.dedupe_key == "confirm_order:order:order-a:2026-11-22"
    assert not finding.runs_without_owner


@pytest.mark.parametrize(
    ("ordered_at", "status"),
    [
        (NOW - 3 * HOUR + MINUTE, "paid"), (NOW - 9 * HOUR, "processing"), (NOW - 9 * HOUR, "completed"),
        (NOW - 9 * HOUR, "cancelled"),
    ],
)
async def test_a_confirmed_cancelled_or_recent_order_is_left_alone(
    migrated: AsyncEngine, ordered_at: datetime, status: str,
) -> None:
    await store(migrated, customer(), order("a", 1040, ordered_at=ordered_at, status=status))

    assert await findings(migrated, NOW) == []


@pytest.mark.parametrize("ship_by", [seoul(23, 59), seoul(16), seoul(9, day=21)])
async def test_an_unpacked_parcel_due_today_or_earlier_is_raised_once(
    migrated: AsyncEngine, ship_by: datetime,
) -> None:
    await store(migrated, customer(), *parcel("a", 1041, ship_by_at=ship_by))

    finding = await only(migrated, NOW)

    assert (finding.kind, finding.tool) == ("parcel_unpacked", "mark_packed")
    assert finding.target == TargetRef("shipment", "shipment-a", "#1041", 0)
    assert finding.args == {"order": "1041"}


async def test_a_packed_parcel_without_an_invoice_is_raised_with_the_invoice_tool(
    migrated: AsyncEngine,
) -> None:
    await store(migrated, customer(), *parcel("a", 1041, ship_by_at=seoul(16), status="invoice_pending"))

    draft = (await only(migrated, NOW)).draft()

    assert (draft.tool, draft.dedupe_key) == (
        "register_invoice", "register_invoice:shipment:shipment-a:2026-11-22",
    )
    assert draft.evidence_needed


@pytest.mark.parametrize(
    ("ship_by", "status"),
    [
        (seoul(0, day=23), "packing"),
        (seoul(16), "in_transit"), (seoul(16), "delivered"),
    ],
)
async def test_parcels_for_later_days_or_already_moving_are_left_alone(
    migrated: AsyncEngine, ship_by: datetime, status: str,
) -> None:
    await store(migrated, customer(), *parcel("a", 1041, ship_by_at=ship_by, status=status))

    assert await findings(migrated, NOW) == []


async def test_a_parcel_becomes_due_at_midnight_on_the_seoul_clock(migrated: AsyncEngine) -> None:
    await store(migrated, customer(), *parcel("a", 1041, ship_by_at=seoul(10, day=23)))
    just_before = datetime(2026, 11, 22, 14, 59, 59, tzinfo=UTC)
    midnight = just_before + timedelta(seconds=1)

    early, late = await findings(migrated, just_before), await findings(migrated, midnight)

    assert early == []
    assert [finding.day.isoformat() for finding in late] == ["2026-11-23"]


async def test_the_same_instant_in_utc_and_in_seoul_finds_the_same_rows(migrated: AsyncEngine) -> None:
    await store(
        migrated, customer(), *parcel("a", 1041, ship_by_at=seoul(16)),
        order("b", 1042, ordered_at=NOW - 4 * HOUR), inquiry("c", received_at=NOW - 3 * HOUR),
    )

    assert await findings(migrated, NOW.astimezone(UTC)) == await findings(migrated, NOW)


async def test_the_last_parcel_of_a_month_is_raised_on_the_day_and_again_after_it(
    migrated: AsyncEngine,
) -> None:
    await store(migrated, customer(), *parcel("a", 1041, ship_by_at=NOV_30))

    due = await only(migrated, datetime(2026, 11, 30, 14, 0, tzinfo=UTC))
    overdue = await only(migrated, datetime(2026, 11, 30, 15, 30, tzinfo=UTC))

    assert (due.dedupe_key, overdue.dedupe_key) == (
        "mark_packed:shipment:shipment-a:2026-11-30", "mark_packed:shipment:shipment-a:2026-12-01",
    )


@pytest.mark.parametrize("due", [NOW + timedelta(hours=24), NOW - HOUR, NOW + MINUTE])
async def test_a_deposit_due_within_a_day_or_already_late_is_raised(
    migrated: AsyncEngine, due: datetime,
) -> None:
    await store(migrated, customer(), session("a", starts_at=CLASS), booking("b", "a", due=due))

    finding = await only(migrated, NOW)

    assert (finding.kind, finding.tool) == ("deposit_due", "confirm_deposit")
    assert (finding.target.kind, finding.target.id, finding.target.revision) == ("booking", "booking-b", 0)
    assert finding.args == {"booking": "도자기 원데이 클래스"}


@pytest.mark.parametrize(
    ("due", "starts_at", "session_status", "booking_status"),
    [
        (NOW + timedelta(hours=24, minutes=1), CLASS, "scheduled", "deposit_pending"),
        (NOW + HOUR, NOW - HOUR, "scheduled", "deposit_pending"),
        (NOW + HOUR, CLASS, "cancelled", "deposit_pending"),
        (NOW + HOUR, CLASS, "scheduled", "confirmed"),
    ],
)
async def test_a_deposit_is_left_alone_when_it_is_not_due_or_its_class_is_over(
    migrated: AsyncEngine, due: datetime, starts_at: datetime, session_status: str, booking_status: str,
) -> None:
    await store(
        migrated, customer(), session("a", starts_at=starts_at, status=session_status),
        booking("b", "a", due=due, status=booking_status),
    )

    assert await findings(migrated, NOW) == []


async def test_an_inquiry_without_a_draft_is_raised_two_hours_after_it_arrived(migrated: AsyncEngine) -> None:
    await store(migrated, inquiry("a", received_at=NOW - 2 * HOUR))

    finding = await only(migrated, NOW)

    assert (finding.kind, finding.tool, finding.tier) == ("inquiry_undrafted", "save_reply_draft", "T1")
    assert finding.runs_without_owner
    assert (finding.target.kind, finding.target.id, finding.args) == (
        "inquiry", "inquiry-a", {"inquiry": "박지은"},
    )


@pytest.mark.parametrize(
    ("received_at", "draft", "status", "extra"),
    [
        (NOW - 2 * HOUR + MINUTE, "", "pending", ()),
        (NOW - 5 * HOUR, "안녕하세요", "pending", ()),
        (NOW - 5 * HOUR, "", "approved", ()),
        (NOW - 5 * HOUR, "", "pending", (grounding("a", "준비한 답장"),)),
        (NOW - 5 * HOUR, "", "pending", (judgment("a"),)),
    ],
)
async def test_an_inquiry_already_handled_is_left_alone(
    migrated: AsyncEngine, received_at: datetime, draft: str, status: str, extra: tuple[Base, ...],
) -> None:
    await store(migrated, inquiry("a", received_at=received_at, draft=draft, status=status), *extra)

    assert await findings(migrated, NOW) == []


@pytest.mark.parametrize("draft", ["   ", "\n"])
async def test_a_blank_draft_counts_as_none(migrated: AsyncEngine, draft: str) -> None:
    await store(migrated, inquiry("a", received_at=NOW - 5 * HOUR, draft=draft), grounding("a", "  "))

    assert [finding.kind for finding in await findings(migrated, NOW)] == ["inquiry_undrafted"]


async def test_an_answered_judgment_no_longer_hides_an_inquiry(migrated: AsyncEngine) -> None:
    await store(migrated, inquiry("a", received_at=NOW - 5 * HOUR), judgment("a", "answered"))

    assert [finding.kind for finding in await findings(migrated, NOW)] == ["inquiry_undrafted"]


async def test_a_class_below_its_smallest_size_is_raised_from_the_evening_before_its_deadline(
    migrated: AsyncEngine,
) -> None:
    await store(
        migrated, customer(), session("a", starts_at=CLASS),
        booking("b", "a", due=None, status="confirmed", people=2), plan("a", min_seats=4, deadline=DEADLINE),
    )

    quiet, raised = await findings(migrated, EVENING - MINUTE), await only(migrated, EVENING)

    assert quiet == []
    assert (raised.kind, raised.tool) == ("class_under_min", "add_event")
    assert raised.target == TargetRef("session", "session-a", "도자기 원데이 클래스")
    assert (raised.args["day"], raised.args["time"]) == ("2026-11-23", "12:00")


@pytest.mark.parametrize(
    ("people", "min_seats", "rows", "now"),
    [
        (4, 4, (), EVENING), (2, None, (), EVENING), (2, 4, (run_decision("a"),), EVENING),
        (2, 4, (), DEADLINE + MINUTE),
    ],
)
async def test_a_class_with_enough_people_a_decision_or_a_passed_deadline_is_left_alone(
    migrated: AsyncEngine, people: int, min_seats: int | None, rows: tuple[Base, ...], now: datetime,
) -> None:
    await store(
        migrated, customer(), session("a", starts_at=CLASS),
        booking("b", "a", due=None, status="confirmed", people=people),
        plan("a", min_seats=min_seats, deadline=DEADLINE), *rows,
    )

    assert await findings(migrated, now) == []


async def test_a_sent_quote_is_raised_when_its_follow_up_moment_comes(migrated: AsyncEngine) -> None:
    await store(migrated, quote("a", follow_up_at=NOW))

    finding = await only(migrated, NOW)

    assert (finding.kind, finding.tool) == ("quote_waiting", "record_quote_outcome")
    assert (finding.target, finding.args) == (
        TargetRef("quote", "quote-a", "한빛초등학교", 0), {"quote": "한빛초등학교"},
    )


@pytest.mark.parametrize(
    ("follow_up_at", "status", "outcome"),
    [
        (NOW + MINUTE, "sent", None), (None, "sent", None), (NOW - HOUR, "draft", None),
        (NOW - HOUR, "accepted", "accepted"),
    ],
)
async def test_a_quote_that_is_not_waiting_is_left_alone(
    migrated: AsyncEngine, follow_up_at: datetime | None, status: str, outcome: str | None,
) -> None:
    await store(migrated, quote("a", follow_up_at=follow_up_at, status=status, outcome=outcome))

    assert await findings(migrated, NOW) == []


async def test_the_kinds_with_a_deadline_today_come_first(migrated: AsyncEngine) -> None:
    await store(
        migrated, customer(),
        *parcel("a", 1041, ship_by_at=seoul(16)), order("b", 1042, ordered_at=NOW - 4 * HOUR),
        inquiry("c", received_at=NOW - 3 * HOUR), quote("d", follow_up_at=NOW - HOUR),
    )

    assert [finding.kind for finding in await findings(migrated, NOW)] == [
        "parcel_unpacked", "order_unconfirmed", "inquiry_undrafted", "quote_waiting",
    ]
