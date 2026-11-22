"""Add the assistant agent's settings, runs, steps, proposals, and memories; nothing else changes."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: Final[str] = "0006_agent"
down_revision: Final[str | None] = "0005_k25"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None

EMPTY_OBJECT: Final = sa.text("'{}'::jsonb")
EMPTY_LIST: Final = sa.text("'[]'::jsonb")
QUIET_CHECK: Final = (
    "(quiet_start IS NULL) = (quiet_end IS NULL) AND (quiet_start IS NULL OR quiet_start <> quiet_end)"
)


def moment(name: str, *, nullable: bool = False) -> sa.Column[sa.DateTime]:
    """Build a timestamp column that defaults to now unless it may stay empty."""
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    """Create the tables and the single settings row; the assistant stays off until the owner turns it on."""
    op.create_table(
        "agent_settings",
        sa.Column("id", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("mode", sa.Text(), server_default="off", nullable=False),
        sa.Column("proactive", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("per_tool", JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("daily_cap", sa.Integer(), server_default="20", nullable=False),
        sa.Column("quiet_start", sa.Time(), server_default="22:00", nullable=True),
        sa.Column("quiet_end", sa.Time(), server_default="08:00", nullable=True),
        sa.Column("interval_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        moment("updated_at"),
        sa.CheckConstraint("id = 1"),
        sa.CheckConstraint("mode IN ('off', 'ask', 'auto')"),
        sa.CheckConstraint("daily_cap BETWEEN 1 AND 50"),
        sa.CheckConstraint(QUIET_CHECK),
        sa.CheckConstraint("interval_minutes BETWEEN 5 AND 240"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO agent_settings (id) VALUES (1)")
    op.create_table(
        "agent_setting_changes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("previous", JSONB(), nullable=True),
        sa.Column("value", JSONB(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        moment("changed_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_setting_changes_changed_at",
        "agent_setting_changes",
        ["changed_at"],
        unique=False,
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("request", JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("model_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        moment("created_at"),
        moment("started_at", nullable=True),
        moment("ended_at", nullable=True),
        sa.CheckConstraint("source IN ('chat', 'voice', 'proactive')"),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'fallback', 'failed', 'stopped')"),
        sa.CheckConstraint("model_calls >= 0 AND tokens >= 0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        "ix_agent_runs_status_created_at",
        "agent_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index("ix_agent_runs_created_at", "agent_runs", ["created_at"], unique=False)
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("args", JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("target_kind", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("target_label", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), server_default=EMPTY_LIST, nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("revision_before", sa.Integer(), nullable=True),
        sa.Column("revision_after", sa.Integer(), nullable=True),
        sa.Column("undo_path", sa.Text(), nullable=True),
        sa.Column("undo_data", JSONB(), nullable=True),
        moment("undo_until", nullable=True),
        moment("undone_at", nullable=True),
        moment("created_at"),
        sa.CheckConstraint("seq >= 1"),
        sa.CheckConstraint("tier IN ('T0', 'T1', 'T2')"),
        sa.CheckConstraint("decision IN ('auto', 'proposed', 'refused', 'clarify')"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq"),
    )
    op.create_index(
        "ix_agent_steps_decision_created_at",
        "agent_steps",
        ["decision", "created_at"],
        unique=False,
    )
    op.create_table(
        "agent_proposals",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("preview", JSONB(), server_default=EMPTY_LIST, nullable=False),
        sa.Column("evidence_needed", JSONB(), server_default=EMPTY_LIST, nullable=False),
        sa.Column("args", JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("target_kind", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("target_label", sa.Text(), nullable=True),
        sa.Column("expected_revision", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), server_default="open", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        moment("created_at"),
        moment("decided_at", nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.CheckConstraint("state IN ('open', 'approved', 'dismissed', 'expired')"),
        sa.ForeignKeyConstraint(["step_id"], ["agent_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_proposals_state_expires_at",
        "agent_proposals",
        ["state", "expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_agent_proposals_dedupe_key",
        "agent_proposals",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        moment("created_at"),
        moment("last_used_at", nullable=True),
        moment("deleted_at", nullable=True),
        sa.CheckConstraint("kind IN ('fact', 'preference', 'rule_of_thumb')"),
        sa.CheckConstraint("btrim(text) <> ''"),
        sa.CheckConstraint("btrim(source_quote) <> ''"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_memories_deleted_at_created_at",
        "agent_memories",
        ["deleted_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop only the added tables; every other table keeps its data."""
    op.drop_table("agent_memories")
    op.drop_table("agent_proposals")
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
    op.drop_table("agent_setting_changes")
    op.drop_table("agent_settings")
