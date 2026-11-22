"""Store collected channel data beside the business tables."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: Final[str] = "0005"
down_revision: Final[str | None] = "0004"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None

KIND_CHECK: Final = "channels_kind_check"


def moment(name: str, *, nullable: bool = False) -> sa.Column[sa.DateTime]:
    """Declare a timezone-aware column."""
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def stamped(name: str) -> sa.Column[sa.DateTime]:
    """Declare an audit timestamp the database fills in."""
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def count(name: str) -> sa.Column[sa.Integer]:
    """Declare a run counter."""
    return sa.Column(name, sa.Integer(), server_default="0", nullable=False)


def upgrade() -> None:
    """Add sources, runs, and items; let a blog appear as a channel."""
    op.create_table(
        "collector_sources",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("config", JSONB(), server_default="{}", nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        moment("last_run_at", nullable=True),
        moment("last_collected_at", nullable=True),
        stamped("created_at"),
        stamped("updated_at"),
        sa.CheckConstraint("state IN ('collecting', 'idle', 'needs_connection', 'error')"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "collector_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        moment("started_at"),
        moment("finished_at", nullable=True),
        count("collected"),
        count("inserted"),
        count("mapped"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')"),
        sa.CheckConstraint("collected >= 0 AND inserted >= 0 AND mapped >= 0"),
        sa.ForeignKeyConstraint(["source_id"], ["collector_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collector_runs_source_started", "collector_runs", ["source_id", "started_at"])
    op.create_table(
        "collected_items",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        moment("published_at", nullable=True),
        sa.Column("raw", JSONB(), nullable=False),
        sa.Column("mapped", sa.Boolean(), server_default="false", nullable=False),
        moment("collected_at"),
        moment("updated_at"),
        sa.CheckConstraint("kind IN ('post', 'comment', 'insight', 'order', 'inquiry')"),
        sa.ForeignKeyConstraint(["source_id"], ["collector_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    op.create_index("ix_collected_items_source_collected", "collected_items", ["source_id", "collected_at"])
    op.create_index("ix_collected_items_unmapped", "collected_items", ["source_id", "mapped"])
    op.drop_constraint(KIND_CHECK, "channels", type_="check")
    op.create_check_constraint(
        KIND_CHECK, "channels", "kind IN ('instagram', 'naver_store', 'naver_booking', 'naver_blog')",
    )


def downgrade() -> None:
    """Drop collected data; inquiries and orders already mapped from it stay."""
    op.execute("DELETE FROM channels WHERE kind = 'naver_blog'")
    op.drop_constraint(KIND_CHECK, "channels", type_="check")
    op.create_check_constraint(
        KIND_CHECK, "channels", "kind IN ('instagram', 'naver_store', 'naver_booking')",
    )
    op.drop_table("collected_items")
    op.drop_table("collector_runs")
    op.drop_table("collector_sources")
