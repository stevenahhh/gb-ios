"""${message}."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: Final[str] = ${repr(up_revision)}
down_revision: Final[str | None] = ${repr(down_revision)}
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None


def upgrade() -> None:
    """Apply this revision."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert this revision."""
    ${downgrades if downgrades else "pass"}
