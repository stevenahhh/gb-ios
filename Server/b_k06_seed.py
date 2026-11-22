# How to run: from Server, after seed.py, run `uv run python b_k06_seed.py`.
"""Explicit example data for the cancellation card; every record is labelled 예시 and nothing is updated."""

import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

import anyio
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from b_k06_models import (
    WORKSHOP_ID,
    CancellationCaseRow,
    PolicyNoticeRow,
    PolicyVersionRow,
    SessionPlanRow,
    WaitlistEntryRow,
)
from database import Base, DatabaseConfigurationError, get_engine
from display import SEOUL
from models import BookingRow, ClassSessionRow, CustomerRow
from seed_data import INSTAGRAM

type ExampleTable = tuple[type[Base], Sequence[Mapping[str, object]]]


def rules(three_days: int) -> list[dict[str, int | bool | str]]:
    """Build one rule table."""
    return [
        {
            "days_before": 3, "refund_percent": three_days, "deduct_material": False,
            "carry_over_allowed": True, "note": f"3일 전까지 {three_days}%",
        },
        {
            "days_before": 2, "refund_percent": 50, "deduct_material": False, "carry_over_allowed": True,
            "note": "2일 전 50%",
        },
        {
            "days_before": 0, "refund_percent": 0, "deduct_material": False, "carry_over_allowed": False,
            "note": "당일 환불 없음",
        },
    ]


def tables(today: date) -> list[ExampleTable]:
    """Build rows around the seeding day."""

    def at(offset: int, hour: int) -> datetime:
        return datetime.combine(today + timedelta(days=offset), time(hour), SEOUL)

    def session(key: str, title: str, moment: datetime, capacity: int) -> dict[str, str | int | datetime]:
        return {
            "id": f"session-k06-{key}", "title": title, "starts_at": moment, "duration_minutes": 120,
            "capacity": capacity, "deposit_won": 20000, "status": "scheduled",
        }

    def booking(key: str, where: str, customer: str, people: int) -> dict[str, str | int | datetime | None]:
        return {
            "id": f"booking-k06-{key}", "session_id": where, "customer_id": customer,
            "channel_id": INSTAGRAM, "party_size": people, "status": "confirmed", "deposit_won": 20000,
            "deposit_due_at": None, "deposit_confirmed_at": at(-10, 12),
        }

    def precedent(key: str, days: int, reason: str) -> dict[str, object]:
        return {
            "id": f"case-k06-{key}", "workshop_id": WORKSHOP_ID, "booking_id": None,
            "session_id": "session-past-mug", "kind": "cancel", "policy_version_id": "policy-k06-3",
            "computed": {}, "decision": "carry_over", "reason": reason, "reason_category": "health",
            "draft": "", "decided_won": 0, "decided_at": at(-days, 10),
        }

    return [
        (CustomerRow, [{"id": "customer-k06-hayun", "name": "김하윤", "phone": "010-0000-0000"}]),
        (ClassSessionRow, [
            session("today", "예시 머그컵 클래스", at(0, 15), 4),
            session("small", "예시 물레 클래스", at(2, 14), 4),
            session("other", "예시 물레 클래스", at(3, 14), 4),
        ]),
        (BookingRow, [
            booking("hayun", "session-k06-today", "customer-k06-hayun", 1),
            booking("small", "session-k06-small", "customer-jung-taeu", 1),
            booking("other", "session-k06-other", "customer-yoon-sua", 1),
        ]),
        (PolicyVersionRow, [
            {
                "id": f"policy-k06-{version}", "workshop_id": WORKSHOP_ID, "version": version,
                "rules": rules(share), "late": {"late_minutes": 15, "note": "15분 넘게 늦으면 노쇼"},
                "unread": [], "source_text": "예시 규정", "approved_at": at(-days, 10),
            }
            for version, share, days in ((1, 80, 60), (2, 90, 40), (3, 100, 20))
        ]),
        (PolicyNoticeRow, [{
            "id": "notice-k06-hayun", "booking_id": "booking-k06-hayun",
            "policy_version_id": "policy-k06-3", "noticed_at": at(-10, 12),
        }]),
        (CancellationCaseRow, [
            precedent("a", 30, "예시: 아이가 아파서 1회 이월"),
            precedent("b", 55, "예시: 감기로 1회 이월"),
        ]),
        (WaitlistEntryRow, [
            {
                "id": f"waitlist-k06-{rank}", "class_session_id": "session-k06-today",
                "customer_id": customer, "source": source, "rank": rank,
            }
            for rank, customer, source in (
                (1, "customer-kim-haneul", "waitlist"), (2, "customer-park-seoyeon", "makeup"),
            )
        ]),
        (SessionPlanRow, [{
            "session_id": "session-k06-small", "min_seats": 2, "material_won": 8000,
            "material_order_deadline": at(1, 10),
        }]),
    ]


async def apply(connection: AsyncConnection, today: date) -> int:
    """Insert missing example rows."""
    inserted = 0
    for model, rows in tables(today):
        result = await connection.execute(insert(model).values(list(rows)).on_conflict_do_nothing())
        inserted += result.rowcount
    return inserted


async def main() -> None:
    """Seed in one transaction without credential-bearing tracebacks."""
    try:
        engine = get_engine()
        try:
            async with engine.begin() as connection:
                inserted = await apply(connection, datetime.now(SEOUL).date())
        finally:
            await engine.dispose()
            get_engine.cache_clear()
    except (DatabaseConfigurationError, SQLAlchemyError, OSError, TimeoutError):
        message = "Seeding failed; run migrations and seed.py first."
        raise SystemExit(message) from None
    _ = sys.stdout.write(f"K06 example data: {inserted} rows inserted.\n")


if __name__ == "__main__":
    anyio.run(main)
