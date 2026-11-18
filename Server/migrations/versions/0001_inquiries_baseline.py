"""Adopt the original inquiries table, or create it on an empty database."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: Final[str] = "0001"
down_revision: Final[str | None] = None
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None

REQUIRED_COLUMNS: Final = frozenset(
    {"id", "customer", "subject", "question", "facts", "draft", "status", "revision"},
)


class IncompatibleInquiriesTableError(Exception):
    """An existing inquiries table does not have the deployed v1 shape."""


def upgrade() -> None:
    """Keep existing rows untouched; deployed databases need no manual stamp."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("inquiries"):
        existing = {column["name"] for column in inspector.get_columns("inquiries")}
        if not existing >= REQUIRED_COLUMNS:
            raise IncompatibleInquiriesTableError
        return
    op.create_table(
        "inquiries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("customer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("facts", ARRAY(sa.Text()), nullable=False),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')"),
        sa.CheckConstraint("revision >= 0"),
    )


def downgrade() -> None:
    """Keep customer data; the baseline is never dropped automatically."""
