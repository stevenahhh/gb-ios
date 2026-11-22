"""Tables of the grounded reply engine (K25); every one of them only adds to the existing schema."""

import hashlib
from datetime import datetime
from typing import Final, Literal

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models import REVISION_CHECK, Entity, TableArgs

type Arm = Literal["grounded"]
# Every inquiry is grounded; the app and two columns still carry the word.
GROUNDED: Final[Arm] = "grounded"


def card_id_for(class_name: str) -> str:
    """Derive a stable card id from the class name, so a class without a card has one too."""
    digest = hashlib.sha256(" ".join(class_name.split()).encode()).hexdigest()
    return f"card-{digest[:16]}"


class FactCardRow(Entity, Base):
    """The class facts the owner confirmed; an empty column is not evidence."""

    __tablename__: str = "class_fact_cards"
    __table_args__: TableArgs = (
        UniqueConstraint("class_name"), CheckConstraint("btrim(class_name) <> ''"),
        CheckConstraint("duration_minutes > 0"), CheckConstraint("capacity > 0"),
        CheckConstraint("price_won > 0"), CheckConstraint("deposit_won > 0"),
        CheckConstraint(REVISION_CHECK),
    )
    class_name: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    capacity: Mapped[int | None] = mapped_column(Integer)
    included_materials: Mapped[str | None] = mapped_column(Text)
    parking: Mapped[str | None] = mapped_column(Text)
    refund_policy: Mapped[str | None] = mapped_column(Text)
    price_won: Mapped[int | None] = mapped_column(Integer)
    deposit_won: Mapped[int | None] = mapped_column(Integer)


class OwnerRuleRow(Base):
    """One sentence the owner chose to reuse; a retired rule stays for its history."""

    __tablename__: str = "owner_rules"
    __table_args__: TableArgs = (
        CheckConstraint("btrim(rule_text) <> ''"), Index("ix_owner_rules_card_id", "card_id"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("class_fact_cards.id", ondelete="RESTRICT"))
    question_summary: Mapped[str] = mapped_column(Text)
    rule_text: Mapped[str] = mapped_column(Text)
    source_inquiry_id: Mapped[str | None] = mapped_column(ForeignKey("inquiries.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JudgmentRow(Base):
    """A question the facts could not answer, handed to the owner."""

    __tablename__: str = "judgment_requests"
    __table_args__: TableArgs = (
        CheckConstraint("status IN ('open', 'answered', 'dismissed')"),
        Index("ix_judgment_requests_inquiry_status", "inquiry_id", "status"),
        Index(
            "uq_judgment_requests_open", "inquiry_id", unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    inquiry_id: Mapped[str] = mapped_column(ForeignKey("inquiries.id", ondelete="CASCADE"))
    issue: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    answer_text: Mapped[str | None] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("owner_rules.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GroundingRow(Base):
    """What the engine keeps for one inquiry: its last check and lock.

    A row from an earlier release may hold another word in ab_arm. It is checked like any other,
    and the next write corrects the word.
    """

    __tablename__: str = "inquiry_grounding"
    __table_args__: TableArgs = (
        CheckConstraint("ab_arm IN ('control', 'grounded')"),
        CheckConstraint("lock_state IN ('clear', 'locked', 'overridden', 'unchecked')"),
    )
    inquiry_id: Mapped[str] = mapped_column(
        ForeignKey("inquiries.id", ondelete="CASCADE"), primary_key=True,
    )
    ab_arm: Mapped[str] = mapped_column(Text)
    lock_state: Mapped[str] = mapped_column(Text, server_default="unchecked")
    claims_json: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    generated_draft: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_ok: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class GroundedEventRow(Base):
    """One measured step of a grounded reply; an approval also keeps the check of its text."""

    __tablename__: str = "grounded_events"
    __table_args__: TableArgs = (
        CheckConstraint("arm IN ('control', 'grounded')"),
        CheckConstraint(
            (
                "kind IN ('draft', 'approved', 'override', 'judgment_opened', 'judgment_answered',"
                " 'judgment_dismissed')"
            ),
        ),
        Index("ix_grounded_events_inquiry_id", "inquiry_id"),
        Index("ix_grounded_events_arm_kind_created_at", "arm", "kind", "created_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    inquiry_id: Mapped[str] = mapped_column(ForeignKey("inquiries.id", ondelete="CASCADE"))
    arm: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
