"""Record overdue work carried into a day's list; no existing table changes."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0006"
down_revision: Final[str | None] = "0005_k25"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None


def upgrade() -> None:
    """Create the carry-over table."""
    op.create_table(
        "carry_overs",
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("carried_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("target IN ('task', 'shipment')"),
        sa.PrimaryKeyConstraint("target", "target_id"),
    )


def downgrade() -> None:
    """Forget what was carried; tasks and shipments keep their deadlines."""
    op.drop_table("carry_overs")
