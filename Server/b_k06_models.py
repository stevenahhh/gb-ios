"""Tables of the cancellation and no-show card; existing tables are only referenced."""

from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models import TableArgs, timestamp

WORKSHOP_ID = 1


class PolicyVersionRow(Base):
    """One approved refund rule table; a saved version never changes."""

    __tablename__: str = "policy_versions"
    __table_args__: TableArgs = (
        UniqueConstraint("workshop_id", "version", name="uq_policy_versions_workshop_version"),
        CheckConstraint("version > 0"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workshop_id: Mapped[int] = mapped_column(SmallInteger)
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[list[JsonValue]] = mapped_column(JSONB)
    late: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    unread: Mapped[list[str]] = mapped_column(ARRAY(Text))
    source_text: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = timestamp()


class PolicyNoticeRow(Base):
    """When the owner copied a rule summary for one booking."""

    __tablename__: str = "policy_notices"
    __table_args__: TableArgs = (Index("ix_policy_notices_booking_id", "booking_id"),)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id", ondelete="RESTRICT"))
    noticed_at: Mapped[datetime] = timestamp()


class CancellationCaseRow(Base):
    """One owner decision and the calculation it was made on; the customer's message is never stored."""

    __tablename__: str = "cancellation_cases"
    __table_args__: TableArgs = (
        CheckConstraint("kind IN ('cancel', 'no_show', 'refill', 'under_min')"),
        CheckConstraint(
            "decision IN ('by_rule', 'carry_over', 'full_refund', 'custom', 'run', 'merge', 'cancel')",
        ),
        Index("ix_cancellation_cases_kind_decided_at", "workshop_id", "kind", "decided_at"),
        Index("ix_cancellation_cases_booking_id", "booking_id"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workshop_id: Mapped[int] = mapped_column(SmallInteger)
    booking_id: Mapped[str | None] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    policy_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
    )
    computed: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    decision: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    reason_category: Mapped[str | None] = mapped_column(Text)
    draft: Mapped[str] = mapped_column(Text)
    arm: Mapped[str | None] = mapped_column(Text)
    decided_won: Mapped[int | None] = mapped_column(Integer)
    pasted_at: Mapped[datetime | None] = timestamp(nullable=True)
    card_shown_at: Mapped[datetime | None] = timestamp(nullable=True)
    decided_at: Mapped[datetime] = timestamp()
    approved_at: Mapped[datetime | None] = timestamp(nullable=True)
    edit_chars: Mapped[int | None] = mapped_column(Integer)


class WaitlistEntryRow(Base):
    """A customer who asked for a seat or still has a make-up class."""

    __tablename__: str = "waitlist_entries"
    __table_args__: TableArgs = (
        UniqueConstraint("class_session_id", "rank", name="uq_waitlist_entries_session_rank"),
        CheckConstraint("source IN ('waitlist', 'makeup')"), CheckConstraint("rank > 0"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(Text)
    rank: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingMarkRow(Base):
    """Attendance and cancellation moments of one booking."""

    __tablename__: str = "booking_marks"
    booking_id: Mapped[str] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True,
    )
    attended_at: Mapped[datetime | None] = timestamp(nullable=True)
    no_show_at: Mapped[datetime | None] = timestamp(nullable=True)
    cancelled_at: Mapped[datetime | None] = timestamp(nullable=True)


class SessionPlanRow(Base):
    """The smallest class the owner runs and when its materials must be ordered."""

    __tablename__: str = "session_plans"
    __table_args__: TableArgs = (
        CheckConstraint("min_seats > 0"), CheckConstraint("material_won >= 0"),
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("class_sessions.id", ondelete="CASCADE"), primary_key=True,
    )
    min_seats: Mapped[int | None] = mapped_column(Integer)
    material_order_deadline: Mapped[datetime | None] = timestamp(nullable=True)
    material_won: Mapped[int | None] = mapped_column(Integer)
