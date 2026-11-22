"""Add the grounded reply engine (K25) tables; existing tables are not changed."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: Final[str] = "0005_k25"
down_revision: Final[str | None] = "k14_0005"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None


def moment(name: str, *, nullable: bool = False) -> sa.Column[sa.DateTime]:
    """Build a timestamp column that defaults to now unless it may stay empty."""
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    """Create the fact cards, rules, judgments, checks, and measured events."""
    op.create_table(
        "class_fact_cards",
        sa.Column("class_name", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("included_materials", sa.Text(), nullable=True),
        sa.Column("parking", sa.Text(), nullable=True),
        sa.Column("refund_policy", sa.Text(), nullable=True),
        sa.Column("price_won", sa.Integer(), nullable=True),
        sa.Column("deposit_won", sa.Integer(), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("btrim(class_name) <> ''"),
        sa.CheckConstraint("capacity > 0"),
        sa.CheckConstraint("deposit_won > 0"),
        sa.CheckConstraint("duration_minutes > 0"),
        sa.CheckConstraint("price_won > 0"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_name"),
    )
    op.create_table(
        "owner_rules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("card_id", sa.Text(), nullable=True),
        sa.Column("question_summary", sa.Text(), nullable=False),
        sa.Column("rule_text", sa.Text(), nullable=False),
        sa.Column("source_inquiry_id", sa.Text(), nullable=True),
        moment("created_at"),
        moment("retired_at", nullable=True),
        sa.CheckConstraint("btrim(rule_text) <> ''"),
        sa.ForeignKeyConstraint(["card_id"], ["class_fact_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_inquiry_id"], ["inquiries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_rules_card_id", "owner_rules", ["card_id"], unique=False)
    op.create_table(
        "judgment_requests",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("inquiry_id", sa.Text(), nullable=False),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("rule_id", sa.Text(), nullable=True),
        moment("created_at"),
        moment("answered_at", nullable=True),
        sa.CheckConstraint("status IN ('open', 'answered', 'dismissed')"),
        sa.ForeignKeyConstraint(["inquiry_id"], ["inquiries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["owner_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_judgment_requests_inquiry_status", "judgment_requests", ["inquiry_id", "status"], unique=False,
    )
    op.create_index(
        "uq_judgment_requests_open", "judgment_requests", ["inquiry_id"], unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "inquiry_grounding",
        sa.Column("inquiry_id", sa.Text(), nullable=False),
        sa.Column("ab_arm", sa.Text(), nullable=False),
        sa.Column("lock_state", sa.Text(), server_default="unchecked", nullable=False),
        sa.Column("claims_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("generated_draft", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        moment("created_at"),
        moment("updated_at"),
        sa.CheckConstraint("ab_arm IN ('control', 'grounded')"),
        sa.CheckConstraint("lock_state IN ('clear', 'locked', 'overridden', 'unchecked')"),
        sa.ForeignKeyConstraint(["inquiry_id"], ["inquiries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("inquiry_id"),
    )
    op.create_table(
        "grounded_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("inquiry_id", sa.Text(), nullable=False),
        sa.Column("arm", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("data", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        moment("created_at"),
        sa.CheckConstraint("arm IN ('control', 'grounded')"),
        sa.CheckConstraint(
            "kind IN ('draft', 'approved', 'override', 'judgment_opened', 'judgment_answered',"
            " 'judgment_dismissed')",
        ),
        sa.ForeignKeyConstraint(["inquiry_id"], ["inquiries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grounded_events_inquiry_id", "grounded_events", ["inquiry_id"], unique=False)
    op.create_index(
        "ix_grounded_events_arm_kind_created_at", "grounded_events", ["arm", "kind", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the added tables; inquiries and every other table keep their data."""
    op.drop_table("grounded_events")
    op.drop_table("inquiry_grounding")
    op.drop_table("judgment_requests")
    op.drop_table("owner_rules")
    op.drop_table("class_fact_cards")
