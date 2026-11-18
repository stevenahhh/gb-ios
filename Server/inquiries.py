"""Inquiry HTTP contract; completed replies persist without external side effects."""

from typing import Annotated, ClassVar, Literal, NewType

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common import Offset, Revision, Session
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
    status: Literal["pending", "approved"]
    revision: Revision


class DraftEdit(BaseModel):
    """A reply edit requires the revision the client observed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)
    draft: str = Field(max_length=4000)
    expected_revision: Revision = Field(alias="expectedRevision")


class Decision(DraftEdit):
    """Completing a reply carries its final text and uses the same revision contract."""

    decision: Literal["approve"]


async def locked_inquiry(
    inquiry_id: InquiryId, expected_revision: int, db: AsyncSession,
) -> InquiryRow:
    """Lock before checking state, so competing edits cannot both succeed."""
    row = await db.scalar(
        select(InquiryRow).where(InquiryRow.id == inquiry_id).with_for_update(),
    )
    if row is None:
        raise HTTPException(404, "inquiry not found")
    if row.revision != expected_revision:
        raise HTTPException(409, "inquiry revision is stale")
    return row


@router.get("/inquiries")
async def list_inquiries(
    db: Session, limit: Annotated[int, Query(ge=1, le=500)] = 200, offset: Offset = 0,
) -> list[Inquiry]:
    """Return durable inquiries by ID, including answered ones."""
    rows = await db.scalars(select(InquiryRow).order_by(InquiryRow.id).limit(limit).offset(offset))
    return [Inquiry.model_validate(row) for row in rows]


@router.patch("/inquiries/{inquiry_id}/draft")
async def edit_draft(inquiry_id: InquiryId, body: DraftEdit, db: Session) -> Inquiry:
    """Persist an edit without trimming the working text; a completed reply stays non-blank."""
    row = await locked_inquiry(inquiry_id, body.expected_revision, db)
    if row.status == "approved" and not body.draft.strip():
        raise HTTPException(422, "completed reply cannot be blank")
    row.draft = body.draft
    row.revision += 1
    await db.flush()
    return Inquiry.model_validate(row)


@router.post("/inquiries/{inquiry_id}/decision")
async def decide(inquiry_id: InquiryId, body: Decision, db: Session) -> Inquiry:
    """Mark a reply complete, or update a completed one, without booking or sending a message."""
    row = await locked_inquiry(inquiry_id, body.expected_revision, db)
    text = body.draft.strip()
    if not text:
        raise HTTPException(422, "blank reply cannot be completed")
    row.status = "approved"
    row.draft = text
    row.revision += 1
    await db.flush()
    return Inquiry.model_validate(row)
