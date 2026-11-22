"""Add the cancellation and no-show card tables; no existing table changes."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: Final[str] = "0005_k06"
down_revision: Final[str | None] = "0004"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None


def moment(name: str, *, nullable: bool = False) -> sa.Column[object]:
    """Declare a timezone-aware column."""
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    """Create every table of the feature."""
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workshop_id", sa.SmallInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("late", postgresql.JSONB(), nullable=True),
        sa.Column("unread", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        moment("approved_at"),
        sa.CheckConstraint("version > 0"),
        sa.UniqueConstraint("workshop_id", "version", name="uq_policy_versions_workshop_version"),
    )
    op.create_table(
        "policy_notices",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("booking_id", sa.Text(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "policy_version_id", sa.Text(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        moment("noticed_at"),
    )
    op.create_index("ix_policy_notices_booking_id", "policy_notices", ["booking_id"])
    op.create_table(
        "cancellation_cases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workshop_id", sa.SmallInteger(), nullable=False),
        sa.Column("booking_id", sa.Text(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "session_id", sa.Text(), sa.ForeignKey("class_sessions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "policy_version_id", sa.Text(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("computed", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reason_category", sa.Text(), nullable=True),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("arm", sa.Text(), nullable=True),
        sa.Column("decided_won", sa.Integer(), nullable=True),
        moment("pasted_at", nullable=True),
        moment("card_shown_at", nullable=True),
        moment("decided_at"),
        moment("approved_at", nullable=True),
        sa.Column("edit_chars", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('cancel', 'no_show', 'refill', 'under_min')"),
        sa.CheckConstraint(
            "decision IN ('by_rule', 'carry_over', 'full_refund', 'custom', 'run', 'merge', 'cancel')",
        ),
    )
    op.create_index(
        "ix_cancellation_cases_kind_decided_at", "cancellation_cases", ["workshop_id", "kind", "decided_at"],
    )
    op.create_index("ix_cancellation_cases_booking_id", "cancellation_cases", ["booking_id"])
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "class_session_id", sa.Text(), sa.ForeignKey("class_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id", sa.Text(), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source IN ('waitlist', 'makeup')"),
        sa.CheckConstraint("rank > 0"),
        sa.UniqueConstraint("class_session_id", "rank", name="uq_waitlist_entries_session_rank"),
    )
    op.create_table(
        "booking_marks",
        sa.Column(
            "booking_id", sa.Text(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True,
        ),
        moment("attended_at", nullable=True),
        moment("no_show_at", nullable=True),
        moment("cancelled_at", nullable=True),
    )
    op.create_table(
        "session_plans",
        sa.Column(
            "session_id", sa.Text(), sa.ForeignKey("class_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("min_seats", sa.Integer(), nullable=True),
        moment("material_order_deadline", nullable=True),
        sa.Column("material_won", sa.Integer(), nullable=True),
        sa.CheckConstraint("min_seats > 0"),
        sa.CheckConstraint("material_won >= 0"),
    )


def downgrade() -> None:
    """Drop only the tables this revision created."""
    for name in (
        "session_plans", "booking_marks", "waitlist_entries", "cancellation_cases", "policy_notices",
        "policy_versions",
    ):
        op.drop_table(name)
