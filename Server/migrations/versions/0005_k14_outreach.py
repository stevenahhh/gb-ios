"""Add the outreach quote tables; no existing table changes."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: Final[str] = "k14_0005"
down_revision: Final[str | None] = "0005_k06"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None

STATUSES: Final = "'draft', 'sent', 'accepted', 'accepted_adjusted', 'declined', 'no_reply'"


def audit_columns() -> list[sa.Column[object]]:
    """Build the revision and timestamp columns every audited table has."""
    return [
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    """Create the cost card, default rate, and quote tables."""
    op.create_table(
        "class_costs",
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("material_per_person_krw", sa.Integer(), nullable=False),
        sa.Column("oneday_price_krw", sa.Integer(), nullable=False),
        sa.Column("prep_minutes", sa.Integer(), nullable=False),
        sa.Column("cleanup_minutes", sa.Integer(), nullable=False),
        sa.Column("max_headcount", sa.Integer(), nullable=False),
        *audit_columns(),
        sa.CheckConstraint("material_per_person_krw >= 0"),
        sa.CheckConstraint("oneday_price_krw > 0"),
        sa.CheckConstraint("prep_minutes >= 0"),
        sa.CheckConstraint("cleanup_minutes >= 0"),
        sa.CheckConstraint("max_headcount > 0"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("class_id"),
    )
    op.create_table(
        "outreach_defaults",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("instructor_hourly_krw", sa.Integer(), nullable=False),
        sa.Column("assistant_daily_krw", sa.Integer(), nullable=False),
        sa.Column("travel_mode", sa.Text(), nullable=False),
        sa.Column("travel_per_km_krw", sa.Integer(), nullable=False),
        sa.Column("travel_flat_krw", sa.Integer(), nullable=False),
        sa.Column("minimum_fee_krw", sa.Integer(), nullable=False),
        *audit_columns(),
        sa.CheckConstraint("id = 1"),
        sa.CheckConstraint("travel_mode IN ('flat', 'per_km')"),
        sa.CheckConstraint("instructor_hourly_krw >= 0"),
        sa.CheckConstraint("assistant_daily_krw >= 0"),
        sa.CheckConstraint("travel_per_km_krw >= 0"),
        sa.CheckConstraint("travel_flat_krw >= 0"),
        sa.CheckConstraint("minimum_fee_krw >= 0"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "outreach_quotes",
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("signals", postgresql.JSONB(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("org_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("missing_costs", postgresql.JSONB(), nullable=False),
        sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("follow_up_task_id", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_total_krw", sa.Integer(), nullable=True),
        sa.Column("ab_arm", sa.Text(), nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        *audit_columns(),
        sa.CheckConstraint(f"status IN ({STATUSES})"),
        sa.CheckConstraint("ab_arm IN ('A', 'B')"),
        sa.CheckConstraint("elapsed_seconds >= 0"),
        sa.CheckConstraint("revision >= 0"),
        sa.ForeignKeyConstraint(["follow_up_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_quotes_created_at", "outreach_quotes", ["created_at"], unique=False)


def downgrade() -> None:
    """Remove only what this revision added."""
    op.drop_index("ix_outreach_quotes_created_at", table_name="outreach_quotes")
    op.drop_table("outreach_quotes")
    op.drop_table("outreach_defaults")
    op.drop_table("class_costs")
