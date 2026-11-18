"""Inquiry HTTP contract; decisions persist replies without external side effects."""

from typing import Annotated, ClassVar, Literal, NewType, assert_never

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import ExpectedRevision
from common import Offset, Revision, Session, can_reopen, invalid_transition, require_revision
from models import InquiryRow

InquiryId = NewType("InquiryId", str)
router = APIRouter()


class Inquiry(BaseModel):
    """Serialized inquiry shared with the iOS lane."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    id: InquiryId
    customer: str
    subject: str
    question: str
    facts: list[str]
    draft: str
    status: Literal["pending", "approved", "rejected"]
    revision: Revision


class DraftEdit(BaseModel):
    """A pending draft edit requires the revision the client observed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)
    draft: str = Field(max_length=4000)
    expected_revision: Revision = Field(alias="expectedRevision")


class Decision(DraftEdit):
    """A decision carries the final draft and uses the same revision contract."""

    decision: Literal["approve", "reject"]


async def locked_inquiry(
    inquiry_id: InquiryId, expected_revision: int, db: AsyncSession,
) -> InquiryRow:
    """Lock before checking state, so competing edits cannot both succeed."""
    row = await db.scalar(
        select(InquiryRow).where(InquiryRow.id == inquiry_id).with_for_update(),
    )
    if row is None:
        raise HTTPException(404, "inquiry not found")
    if row.status != "pending" or row.revision != expected_revision:
        raise HTTPException(409, "inquiry already decided or revision is stale")
    return row


@router.get("/inquiries")
async def list_inquiries(
    db: Session, limit: Annotated[int, Query(ge=1, le=500)] = 200, offset: Offset = 0,
) -> list[Inquiry]:
    """Return durable inquiries by ID, including already decided ones."""
    rows = await db.scalars(select(InquiryRow).order_by(InquiryRow.id).limit(limit).offset(offset))
    return [Inquiry.model_validate(row) for row in rows]


@router.patch("/inquiries/{inquiry_id}/draft")
async def edit_draft(inquiry_id: InquiryId, body: DraftEdit, db: Session) -> Inquiry:
    """Persist a pending edit without trimming the user's working draft."""
    row = await locked_inquiry(inquiry_id, body.expected_revision, db)
    row.draft = body.draft
    row.revision += 1
    await db.flush()
    return Inquiry.model_validate(row)


@router.post("/inquiries/{inquiry_id}/decision")
async def decide(inquiry_id: InquiryId, body: Decision, db: Session) -> Inquiry:
    """Persist a final reply decision without booking or sending a message."""
    row = await locked_inquiry(inquiry_id, body.expected_revision, db)
    text = body.draft.strip()
    match body.decision:
        case "approve":
            if not text:
                raise HTTPException(422, "blank draft cannot be approved")
            row.status = "approved"
        case "reject":
            row.status = "rejected"
        case _:
            assert_never(body.decision)
    row.draft = text
    row.revision += 1
    await db.flush()
    return Inquiry.model_validate(row)


@router.post("/inquiries/{inquiry_id}/reopen")
async def reopen(inquiry_id: InquiryId, body: ExpectedRevision, db: Session) -> Inquiry:
    """Reopen a recorded decision while preserving the reply draft."""
    row = await db.scalar(select(InquiryRow).where(InquiryRow.id == inquiry_id).with_for_update())
    if row is None:
        raise HTTPException(404, "inquiry not found")
    require_revision(row.revision, body.expected_revision)
    if not can_reopen(is_decided=row.status in {"approved", "rejected"}):
        raise invalid_transition()
    row.status = "pending"
    row.revision += 1
    await db.flush()
    return Inquiry.model_validate(row)
