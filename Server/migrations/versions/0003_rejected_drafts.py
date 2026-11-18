"""Allow owners to reject content and assistant recommendations."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0003"
down_revision: Final[str | None] = "0002"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None


def upgrade() -> None:
    """Expand the existing status checks without changing stored work."""
    op.drop_constraint("content_drafts_status_check", "content_drafts", type_="check")
    op.create_check_constraint(
        "content_drafts_status_check", "content_drafts", "status IN ('draft', 'reviewed', 'rejected')",
    )
    op.drop_constraint(
        "assistant_recommendations_status_check", "assistant_recommendations", type_="check",
    )
    op.create_check_constraint(
        "assistant_recommendations_status_check", "assistant_recommendations",
        "status IN ('open', 'acknowledged', 'rejected')",
    )


def downgrade() -> None:
    """Restore old statuses before tightening the checks."""
    op.execute(sa.text("UPDATE content_drafts SET status = 'draft' WHERE status = 'rejected'"))
    op.execute(sa.text(
        "UPDATE assistant_recommendations SET status = 'open' WHERE status = 'rejected'",
    ))
    op.drop_constraint("content_drafts_status_check", "content_drafts", type_="check")
    op.create_check_constraint(
        "content_drafts_status_check", "content_drafts", "status IN ('draft', 'reviewed')",
    )
    op.drop_constraint(
        "assistant_recommendations_status_check", "assistant_recommendations", type_="check",
    )
    op.create_check_constraint(
        "assistant_recommendations_status_check", "assistant_recommendations",
        "status IN ('open', 'acknowledged')",
    )
