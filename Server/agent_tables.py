"""Tables of the assistant agent (migration 0006); every one of them only adds to the schema."""

from datetime import datetime, time
from typing import Final

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
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models import REVISION_CHECK, TableArgs, timestamp

EMPTY_OBJECT: Final = text("'{}'::jsonb")
EMPTY_LIST: Final = text("'[]'::jsonb")
QUIET_CHECK: Final = (
    "(quiet_start IS NULL) = (quiet_end IS NULL) AND (quiet_start IS NULL OR quiet_start <> quiet_end)"
)


def stamped() -> Mapped[datetime]:
    """Declare a moment the server fills when the code sets none."""
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentSettingsRow(Base):
    """The one row of owner switches; a new or a missing row means off."""

    __tablename__: str = "agent_settings"
    __table_args__: TableArgs = (
        CheckConstraint("id = 1"),
        CheckConstraint("mode IN ('off', 'ask', 'auto')"),
        CheckConstraint("daily_cap BETWEEN 1 AND 50"),
        CheckConstraint(QUIET_CHECK),
        CheckConstraint("interval_minutes BETWEEN 5 AND 240"),
        CheckConstraint(REVISION_CHECK),
    )
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default="1")
    mode: Mapped[str] = mapped_column(Text, server_default="off")
    proactive: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    per_tool: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    daily_cap: Mapped[int] = mapped_column(Integer, server_default="20")
    quiet_start: Mapped[time | None] = mapped_column(Time, server_default="22:00")
    quiet_end: Mapped[time | None] = mapped_column(Time, server_default="08:00")
    interval_minutes: Mapped[int] = mapped_column(Integer, server_default="15")
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = stamped()


class AgentSettingChangeRow(Base):
    """One changed setting; the history behind every switch."""

    __tablename__: str = "agent_setting_changes"
    __table_args__: TableArgs = (Index("ix_agent_setting_changes_changed_at", "changed_at"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    field: Mapped[str] = mapped_column(Text)
    previous: Mapped[JsonValue | None] = mapped_column(JSONB, nullable=True)
    value: Mapped[JsonValue | None] = mapped_column(JSONB, nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    changed_at: Mapped[datetime] = stamped()


class AgentRunRow(Base):
    """One run of the assistant; `request` is the raw input of a queued run and is cleared at the end."""

    __tablename__: str = "agent_runs"
    __table_args__: TableArgs = (
        CheckConstraint("source IN ('chat', 'voice', 'proactive')"),
        CheckConstraint("status IN ('queued', 'running', 'done', 'fallback', 'failed', 'stopped')"),
        CheckConstraint("model_calls >= 0 AND tokens >= 0"),
        Index("ix_agent_runs_status_created_at", "status", "created_at"),
        Index("ix_agent_runs_created_at", "created_at"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_id: Mapped[str | None] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    request: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(Text)
    model_calls: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = stamped()
    started_at: Mapped[datetime | None] = timestamp(nullable=True)
    ended_at: Mapped[datetime | None] = timestamp(nullable=True)


class AgentStepRow(Base):
    """One tool call and what the policy did with it; nothing here holds unmasked personal data."""

    __tablename__: str = "agent_steps"
    __table_args__: TableArgs = (
        UniqueConstraint("run_id", "seq"),
        CheckConstraint("seq >= 1"),
        CheckConstraint("tier IN ('T0', 'T1', 'T2')"),
        CheckConstraint("decision IN ('auto', 'proposed', 'refused', 'clarify')"),
        Index("ix_agent_steps_decision_created_at", "decision", "created_at"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    args: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    target_kind: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    target_label: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB, server_default=EMPTY_LIST)
    result: Mapped[str | None] = mapped_column(Text)
    revision_before: Mapped[int | None] = mapped_column(Integer)
    revision_after: Mapped[int | None] = mapped_column(Integer)
    undo_path: Mapped[str | None] = mapped_column(Text)
    undo_data: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    undo_until: Mapped[datetime | None] = timestamp(nullable=True)
    undone_at: Mapped[datetime | None] = timestamp(nullable=True)
    created_at: Mapped[datetime] = stamped()


class AgentProposalRow(Base):
    """A call the owner may approve; `args` and the target are exactly what approval runs."""

    __tablename__: str = "agent_proposals"
    __table_args__: TableArgs = (
        CheckConstraint("state IN ('open', 'approved', 'dismissed', 'expired')"),
        Index("ix_agent_proposals_state_expires_at", "state", "expires_at"),
        Index(
            "uq_agent_proposals_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("agent_steps.id", ondelete="CASCADE"))
    tool: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    preview: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB, server_default=EMPTY_LIST)
    evidence_needed: Mapped[list[str]] = mapped_column(JSONB, server_default=EMPTY_LIST)
    args: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    target_kind: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    target_label: Mapped[str | None] = mapped_column(Text)
    expected_revision: Mapped[int | None] = mapped_column(Integer)
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, server_default="open")
    expires_at: Mapped[datetime] = timestamp()
    created_at: Mapped[datetime] = stamped()
    decided_at: Mapped[datetime | None] = timestamp(nullable=True)
    result: Mapped[str | None] = mapped_column(Text)


class AgentMemoryRow(Base):
    """One of the owner's own notes; it is context for the model, never an instruction or evidence."""

    __tablename__: str = "agent_memories"
    __table_args__: TableArgs = (
        CheckConstraint("kind IN ('fact', 'preference', 'rule_of_thumb')"),
        CheckConstraint("btrim(text) <> ''"),
        CheckConstraint("btrim(source_quote) <> ''"),
        Index("ix_agent_memories_deleted_at_created_at", "deleted_at", "created_at"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = stamped()
    last_used_at: Mapped[datetime | None] = timestamp(nullable=True)
    deleted_at: Mapped[datetime | None] = timestamp(nullable=True)
