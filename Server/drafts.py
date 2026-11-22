"""Local assistant draft edits, decisions, and reversible review history."""

from datetime import datetime
from typing import Literal, assert_never

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import ExpectedRevision
from common import LongText, Now, Session, can_reopen, invalid_transition, locked, required_text
from contracts import ApiModel, DraftKind, DraftStatus
from draft_contracts import STATUSES
from metrics import load_counts
from models import ChannelRow, ContentDraftRow, RecommendationRow
from recommendations import recommendation_lines, weekend_opening

router = APIRouter()
type DraftRow = ContentDraftRow | RecommendationRow


class AssistantDraft(ApiModel):
    """One editable assistant result, which never sends or publishes itself."""

    id: str
    kind: DraftKind
    title: str
    lines: list[str]
    text: str
    status: DraftStatus
    revision: int
    after_approval: str
    can_reopen: bool


class DraftEdit(ExpectedRevision):
    """A pending draft's working text."""

    draft: LongText


class DraftDecision(DraftEdit):
    """The owner's explicit approval or rejection of final text."""

    decision: Literal["approve", "reject"]


def draft_model(kind: DraftKind) -> type[ContentDraftRow] | type[RecommendationRow]:
    """Resolve the validated path kind to its storage owner."""
    match kind:
        case "content":
            return ContentDraftRow
        case "recommendation":
            return RecommendationRow
        case _:
            assert_never(kind)


async def present(row: DraftRow, db: AsyncSession, now: datetime) -> AssistantDraft:
    """Describe a draft using current channel and recommendation facts."""
    match row:
        case ContentDraftRow():
            channel = await db.get_one(ChannelRow, row.channel_id)
            kind: DraftKind = "content"
            lines = [f"{channel.name} 올릴 글", row.summary]
            after = "글은 사장님이 직접 올려 주세요. 수락하셔도 저절로 올라가지 않아요."
        case RecommendationRow():
            kind = "recommendation"
            facts = recommendation_lines(
                row, await load_counts(db, now.date()), await weekend_opening(db, now),
            )
            lines = facts[:-1] if facts else []
            after = "수락하셔도 신청이나 발송이 저절로 되지는 않아요."
        case _:
            assert_never(row)
    status = STATUSES[row.status]
    return AssistantDraft(
        id=row.id, kind=kind, title=row.title, lines=lines, text=row.body, status=status,
        revision=row.revision, after_approval=after, can_reopen=can_reopen(is_decided=status != "pending"),
    )


async def sync_linked(db: AsyncSession, content: ContentDraftRow) -> None:
    """Apply a content decision to every linked recommendation in this transaction."""
    status = {"draft": "open", "reviewed": "acknowledged", "rejected": "rejected"}[content.status]
    rows = await db.scalars(
        select(RecommendationRow).where(RecommendationRow.draft_id == content.id)
        .order_by(RecommendationRow.id).with_for_update(),
    )
    for row in rows:
        row.status = status
        row.acknowledged_at = content.reviewed_at
        row.revision += 1


@router.get("/assistant-drafts/{kind}/{draft_id}")
async def detail(kind: DraftKind, draft_id: str, db: Session, now: Now) -> AssistantDraft:
    """Read a draft's text, facts, and available reopening state."""
    row = await db.get(draft_model(kind), draft_id)
    if row is None:
        raise HTTPException(404, "resource not found")
    return await present(row, db, now)


def save_text(row: DraftRow, text: str) -> None:
    """Replace a locked pending draft's working text."""
    if STATUSES[row.status] != "pending":
        raise invalid_transition()
    row.body = required_text(text)
    row.revision += 1


@router.patch("/assistant-drafts/{kind}/{draft_id}/draft")
async def edit(
    kind: DraftKind, draft_id: str, body: DraftEdit, db: Session, now: Now,
) -> AssistantDraft:
    """Save nonblank working text only while a draft is pending."""
    row = await locked(db, draft_model(kind), draft_id, body.expected_revision)
    save_text(row, body.draft)
    await db.flush()
    return await present(row, db, now)


@router.post("/assistant-drafts/{kind}/{draft_id}/decision")
async def decide(
    kind: DraftKind, draft_id: str, body: DraftDecision, db: Session, now: Now,
) -> AssistantDraft:
    """Record an explicit local decision, including linked recommendation state."""
    row = await locked(db, draft_model(kind), draft_id, body.expected_revision)
    if STATUSES[row.status] != "pending":
        raise invalid_transition()
    row.body = required_text(body.draft)
    match body.decision:
        case "approve":
            approved = True
        case "reject":
            approved = False
        case _:
            assert_never(body.decision)
    match row:
        case ContentDraftRow():
            row.status = "reviewed" if approved else "rejected"
            row.reviewed_at = now
            await sync_linked(db, row)
        case RecommendationRow():
            row.status = "acknowledged" if approved else "rejected"
            row.acknowledged_at = now
        case _:
            assert_never(row)
    row.revision += 1
    await db.flush()
    return await present(row, db, now)


@router.post("/assistant-drafts/{kind}/{draft_id}/reopen")
async def reopen(
    kind: DraftKind, draft_id: str, body: ExpectedRevision, db: Session, now: Now,
) -> AssistantDraft:
    """Reopen decided text without changing it or contacting any provider."""
    row = await locked(db, draft_model(kind), draft_id, body.expected_revision)
    if not can_reopen(is_decided=STATUSES[row.status] != "pending"):
        raise invalid_transition()
    match row:
        case ContentDraftRow():
            row.status = "draft"
            row.reviewed_at = None
            await sync_linked(db, row)
        case RecommendationRow():
            row.status = "open"
            row.acknowledged_at = None
        case _:
            assert_never(row)
    row.revision += 1
    await db.flush()
    return await present(row, db, now)
