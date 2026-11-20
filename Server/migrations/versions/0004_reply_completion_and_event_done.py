"""Retire rejected replies and let owner-added calendar events be checked off."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0004"
down_revision: Final[str | None] = "0003"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None

STATUS_CHECK: Final = "inquiries_status_check"
OLD_FACT: Final = "예약 안내 · 문의 답변을 승인해도 예약은 자동으로 만들어지지 않습니다."
NEW_FACT: Final = "예약 안내 · 문의 답변을 완료해도 예약은 자동으로 만들어지지 않습니다."


def replace_fact(old: str, new: str) -> None:
    """Rewrite one stored reply fact."""
    op.execute(
        sa.text("UPDATE inquiries SET facts = array_replace(facts, :old, :new)").bindparams(old=old, new=new),
    )


def upgrade() -> None:
    """Reopen rejected inquiries so the owner can still answer them."""
    op.execute("UPDATE inquiries SET status = 'pending', revision = revision + 1 WHERE status = 'rejected'")
    op.drop_constraint(STATUS_CHECK, "inquiries", type_="check")
    op.create_check_constraint(STATUS_CHECK, "inquiries", "status IN ('pending', 'approved')")
    replace_fact(OLD_FACT, NEW_FACT)
    op.add_column("calendar_events", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Restore the wider status check; reopened inquiries stay pending."""
    op.drop_column("calendar_events", "completed_at")
    replace_fact(NEW_FACT, OLD_FACT)
    op.drop_constraint(STATUS_CHECK, "inquiries", type_="check")
    op.create_check_constraint(STATUS_CHECK, "inquiries", "status IN ('pending', 'approved', 'rejected')")
