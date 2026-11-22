"""Build B tables for the outreach quote judge (K14); existing tables stay untouched."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models import REVISION_CHECK, Audited, Entity, TableArgs, timestamp

STATUSES = "'draft', 'sent', 'accepted', 'accepted_adjusted', 'declined', 'no_reply'"


class ClassCostRow(Audited, Base):
    """The owner's cost card for one class, keyed by the class title."""

    __tablename__: str = "class_costs"
    __table_args__: TableArgs = (
        CheckConstraint("material_per_person_krw >= 0"), CheckConstraint("oneday_price_krw > 0"),
        CheckConstraint("prep_minutes >= 0"), CheckConstraint("cleanup_minutes >= 0"),
        CheckConstraint("max_headcount > 0"), CheckConstraint(REVISION_CHECK),
    )
    class_id: Mapped[str] = mapped_column(Text, primary_key=True)
    material_per_person_krw: Mapped[int] = mapped_column(Integer)
    oneday_price_krw: Mapped[int] = mapped_column(Integer)
    prep_minutes: Mapped[int] = mapped_column(Integer)
    cleanup_minutes: Mapped[int] = mapped_column(Integer)
    max_headcount: Mapped[int] = mapped_column(Integer)


class OutreachDefaultsRow(Audited, Base):
    """The workshop's own outreach rates; one row per deployment."""

    __tablename__: str = "outreach_defaults"
    __table_args__: TableArgs = (
        CheckConstraint("id = 1"), CheckConstraint("travel_mode IN ('flat', 'per_km')"),
        CheckConstraint("instructor_hourly_krw >= 0"), CheckConstraint("assistant_daily_krw >= 0"),
        CheckConstraint("travel_per_km_krw >= 0"), CheckConstraint("travel_flat_krw >= 0"),
        CheckConstraint("minimum_fee_krw >= 0"), CheckConstraint(REVISION_CHECK),
    )
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    instructor_hourly_krw: Mapped[int] = mapped_column(Integer)
    assistant_daily_krw: Mapped[int] = mapped_column(Integer)
    travel_mode: Mapped[str] = mapped_column(Text)
    travel_per_km_krw: Mapped[int] = mapped_column(Integer)
    travel_flat_krw: Mapped[int] = mapped_column(Integer)
    minimum_fee_krw: Mapped[int] = mapped_column(Integer)


class OutreachQuoteRow(Entity, Base):
    """One outreach inquiry turned into a quote; the inquiry text itself is never stored."""

    __tablename__: str = "outreach_quotes"
    __table_args__: TableArgs = (
        CheckConstraint(f"status IN ({STATUSES})"), CheckConstraint("ab_arm IN ('A', 'B')"),
        CheckConstraint("elapsed_seconds >= 0"), CheckConstraint(REVISION_CHECK),
        Index("ix_outreach_quotes_created_at", "created_at"),
    )
    status: Mapped[str] = mapped_column(Text)
    class_id: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict[str, object]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB)
    signals: Mapped[list[str]] = mapped_column(JSONB)
    locked: Mapped[bool] = mapped_column(Boolean)
    org_verified_at: Mapped[datetime | None] = timestamp(nullable=True)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    missing_costs: Mapped[list[str]] = mapped_column(JSONB)
    follow_up_at: Mapped[datetime | None] = timestamp(nullable=True)
    follow_up_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    outcome: Mapped[str | None] = mapped_column(Text)
    outcome_at: Mapped[datetime | None] = timestamp(nullable=True)
    final_total_krw: Mapped[int | None] = mapped_column(Integer)
    ab_arm: Mapped[str] = mapped_column(Text)
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer)
