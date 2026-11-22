"""Add the owner's saved public handles and links; existing tables are not changed."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0007_connections"
down_revision: Final[str | None] = "0006_agent"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None


def upgrade() -> None:
    """Create the connections table."""
    op.create_table(
        "connections",
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("btrim(value) <> '' AND length(value) <= 200"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("service"),
    )


def downgrade() -> None:
    """Drop only the connections table."""
    op.drop_table("connections")
