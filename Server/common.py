"""FastAPI dependencies and row helpers shared by business routes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final

from fastapi import Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from database import session
from display import SEOUL
from models import Entity

MAX_TEXT: Final = 4000
Revision = Annotated[int, Field(strict=True, ge=0)]
Session = Annotated[AsyncSession, Depends(session, scope="function")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Search = Annotated[str, Query(max_length=100)]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(max_length=MAX_TEXT)]


@dataclass(frozen=True, slots=True)
class Paging:
    """Search text and window shared by list endpoints."""

    q: Search = ""
    limit: Limit = 30
    offset: Offset = 0

    @property
    def text(self) -> str:
        """Return the normalized search text."""
        return self.q.strip()

    def has_more(self, total: int) -> bool:
        """Tell whether rows remain after this page."""
        return self.offset + self.limit < total


PageQuery = Annotated[Paging, Depends()]


def current_time() -> datetime:
    """Provide the request clock in workshop time."""
    return datetime.now(SEOUL)


Now = Annotated[datetime, Depends(current_time)]


async def locked[T: Entity](
    db: AsyncSession, model: type[T], row_id: str, expected_revision: int,
) -> T:
    """Lock a row before checking its revision so one concurrent writer wins."""
    row = await db.scalar(select(model).where(model.id == row_id).with_for_update())
    if row is None:
        raise HTTPException(404, "resource not found")
    require_revision(row.revision, expected_revision)
    return row


def require_revision(current: int, expected: int) -> None:
    """Reject writes based on a stale read."""
    if current != expected:
        raise HTTPException(409, "revision is stale")


def invalid_transition() -> HTTPException:
    """Build the response for an action that the current state does not allow."""
    return HTTPException(409, "action is not valid for the current state")


def can_reopen(*, is_decided: bool) -> bool:
    """Allow decided work to reopen; a future sent/published check belongs here."""
    return is_decided


def required_text(value: str) -> str:
    """Trim user text and reject blank values."""
    text = value.strip()
    if not text:
        raise HTTPException(422, "text must not be blank")
    return text


def matches(
    column: InstrumentedAttribute[str] | InstrumentedAttribute[str | None], query: str,
) -> ColumnElement[bool]:
    """Build a literal case-insensitive substring match."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")
