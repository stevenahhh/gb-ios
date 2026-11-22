"""Routes of the grounded reply engine (K25): state, draft, recheck, approval, and metrics."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Final, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k25_claims import Claim, Evaluation, Lock, claim_to_json, claims_from_json
from b_k25_engine import (
    check_final,
    close_open_judgments,
    load_context,
    open_judgment,
    record_event,
    route_inquiry,
    save_draft,
    upsert_grounding,
    write_grounded_draft,
)
from b_k25_ledger import load_ledger
from b_k25_tables import GROUNDED, Arm, GroundedEventRow, GroundingRow, JudgmentRow
from common import MAX_TEXT, Now, Revision, Session
from contracts import ApiModel, ApiRequest
from display import day_start, next_day_start
from inquiries import Inquiry, InquiryId, locked_inquiry
from models import InquiryRow

router = APIRouter()
DEFAULT_WINDOW: Final = timedelta(days=28)
MAX_REASON_CHARS: Final = 200


class ClaimView(ApiModel):
    """One number or statement of a draft and what supports it."""

    kind: Literal["price", "seats", "date", "time", "deposit", "fact", "rule"]
    text: str
    value: str
    source: Literal["ledger", "price_list", "fact_card", "owner_rule", "customer", "none"]
    source_label: str
    ledger_value: str | None
    status: Literal["matched", "mismatched", "unsupported", "unchecked"]
    match: bool
    note: str | None
    replacement: str | None


class JudgmentView(ApiModel):
    """A question the facts could not answer, with the customer's own words."""

    id: str
    inquiry_id: str
    issue: str
    status: Literal["open", "answered", "dismissed"]
    customer: str
    question: str
    answer_text: str | None
    created_at: datetime


class GroundedDraft(ApiModel):
    """A written draft with its check; a raised judgment has no draft."""

    arm: Arm = GROUNDED
    draft: str
    claims: list[ClaimView]
    lock: Lock
    mismatch_count: int
    checked_kinds: list[str]
    judgment: JudgmentView | None = None


class ReplyState(ApiModel):
    """What the inquiry screen shows about the saved draft."""

    inquiry_id: str
    arm: Arm = GROUNDED
    claims: list[ClaimView]
    lock: Lock
    mismatch_count: int
    checked_kinds: list[str]
    judgment: JudgmentView | None
    override_reason: str | None


class Verification(ApiModel):
    """The check of a text the owner is editing, and which kinds of number it compared."""

    claims: list[ClaimView]
    lock: Lock
    mismatch_count: int
    checked_kinds: list[str]


class VerifyRequest(ApiRequest):
    """The text as it stands in the editor."""

    draft: Annotated[str, Field(max_length=MAX_TEXT)]


class GroundedDecision(ApiRequest):
    """Approval of a reply; a locked one needs a reason to be sent as it is."""

    decision: Literal["approve"]
    draft: Annotated[str, Field(max_length=MAX_TEXT)]
    expected_revision: Revision
    override_reason: Annotated[str, Field(min_length=1, max_length=MAX_REASON_CHARS)] | None = None


class Approval(BaseModel):
    """The check an approval recorded with the digest of its text."""

    digest: str
    lock: Lock
    claims: list[dict[str, JsonValue]]
    checked: list[str]


class ReplyMetrics(ApiModel):
    """Measured results of the replies; rates are null until there is something to divide."""

    arm: Arm = GROUNDED
    approvals: int
    unedited_approvals: int
    unedited_rate: float | None
    median_seconds: int | None
    drafts: int
    deferral_drafts: int
    deferral_rate: float | None
    locked_drafts: int
    overrides: int
    judgments_opened: int
    judgments_answered: int
    judgments_dismissed: int


def claim_view(claim: Claim) -> ClaimView:
    """Serialize one checked claim."""
    return ClaimView(
        kind=claim.kind, text=claim.text, value=claim.value, source=claim.source,
        source_label=claim.source_label, ledger_value=claim.ledger_value, status=claim.status,
        match=claim.match, note=claim.note, replacement=claim.replacement,
    )


def mismatches(claims: Sequence[Claim]) -> int:
    """Count the numbers that contradict the ledger, for the lock line."""
    return sum(claim.status == "mismatched" for claim in claims)


def judgment_view(row: JudgmentRow, inquiry: InquiryRow) -> JudgmentView:
    """Serialize a judgment with the inquiry it belongs to."""
    status: Literal["open", "answered", "dismissed"] = "open"
    if row.status in {"answered", "dismissed"}:
        status = "answered" if row.status == "answered" else "dismissed"
    return JudgmentView(
        id=row.id, inquiry_id=row.inquiry_id, issue=row.issue, status=status, customer=inquiry.customer,
        question=f"{inquiry.subject}\n{inquiry.question}", answer_text=row.answer_text,
        created_at=row.created_at,
    )


async def open_judgment_view(db: AsyncSession, inquiry: InquiryRow) -> JudgmentView | None:
    """Return the question still waiting for the owner, if any."""
    row = await db.scalar(
        select(JudgmentRow).where(JudgmentRow.inquiry_id == inquiry.id, JudgmentRow.status == "open"),
    )
    return None if row is None else judgment_view(row, inquiry)


def verification(evaluation: Evaluation) -> Verification:
    """Shape a check for the app."""
    return Verification(
        claims=[claim_view(claim) for claim in evaluation.claims], lock=evaluation.lock,
        mismatch_count=mismatches(evaluation.claims), checked_kinds=list(evaluation.checked),
    )


def digest_of(reply: str) -> str:
    """Mark a reply, so its approval can tell it again without a second copy of the words."""
    return hashlib.sha256(reply.strip().encode()).hexdigest()


async def completed_check(db: AsyncSession, inquiry: InquiryRow) -> Verification | None:
    """Return the check a completed reply was approved with, or nothing when its text needs a new one.

    A reply completed without an approval here was never checked, so it stays unchecked. An approval
    from an earlier release recorded no digest, so nothing tells whether its text was edited since.
    """
    if inquiry.status != "approved":
        return None
    data = await db.scalar(
        select(GroundedEventRow.data).where(
            GroundedEventRow.inquiry_id == inquiry.id, GroundedEventRow.kind == "approved",
            GroundedEventRow.arm == GROUNDED,
        ).order_by(GroundedEventRow.id.desc()).limit(1),
    )
    if data is None:
        return Verification(claims=[], lock="unchecked", mismatch_count=0, checked_kinds=[])
    if data.get("digest") != digest_of(inquiry.draft):
        return None
    approval = Approval.model_validate(data)
    claims = claims_from_json(approval.claims)
    return Verification(
        claims=[claim_view(claim) for claim in claims], lock=approval.lock,
        mismatch_count=mismatches(claims), checked_kinds=approval.checked,
    )


@router.get("/grounded-replies/metrics")
async def metrics(
    db: Session, now: Now, start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> list[ReplyMetrics]:
    """Report the results for the given days, by default the last four weeks, as a list of one entry."""
    first = start or now.date() - DEFAULT_WINDOW
    last = end or now.date()
    events = list(await db.scalars(
        select(GroundedEventRow).where(
            # An earlier release measured drafts nobody checked under another word.
            GroundedEventRow.arm == GROUNDED,
            GroundedEventRow.created_at >= day_start(first),
            GroundedEventRow.created_at < next_day_start(last),
        ),
    ))
    return [reply_metrics(events)]


def reply_metrics(events: Sequence[GroundedEventRow]) -> ReplyMetrics:
    """Summarize the steps; an approval without a measured time counts but is left out of the median."""
    approved = [event.data for event in events if event.kind == "approved"]
    drafts = [event.data for event in events if event.kind == "draft"]
    unedited = sum(data.get("unedited") is True for data in approved)
    deferral = sum(data.get("deferral") is True for data in drafts)
    seconds = sorted(
        value for data in approved if isinstance(value := data.get("seconds"), int)
    )
    counts = {kind: sum(event.kind == kind for event in events) for kind in (
        "override", "judgment_opened", "judgment_answered", "judgment_dismissed",
    )}
    return ReplyMetrics(
        approvals=len(approved), unedited_approvals=unedited,
        unedited_rate=unedited / len(approved) if approved else None,
        median_seconds=seconds[len(seconds) // 2] if seconds else None,
        drafts=len(drafts), deferral_drafts=deferral,
        deferral_rate=deferral / len(drafts) if drafts else None,
        locked_drafts=sum(data.get("lock") == "locked" for data in drafts),
        overrides=counts["override"], judgments_opened=counts["judgment_opened"],
        judgments_answered=counts["judgment_answered"], judgments_dismissed=counts["judgment_dismissed"],
    )


@router.get("/grounded-replies/{inquiry_id}")
async def reply_state(inquiry_id: str, db: Session, now: Now) -> ReplyState:
    """Return what the inquiry screen shows: a completed reply as approved, any other checked again."""
    inquiry = await db.get(InquiryRow, inquiry_id)
    if inquiry is None:
        raise HTTPException(404, "inquiry not found")
    stored = await db.get(GroundingRow, inquiry_id)
    judgment = await open_judgment_view(db, inquiry)
    checked = await completed_check(db, inquiry) or verification(
        check_final(inquiry.draft, await load_ledger(db, inquiry, now), stored),
    )
    return ReplyState(
        inquiry_id=inquiry_id, claims=checked.claims, lock=checked.lock,
        mismatch_count=checked.mismatch_count, checked_kinds=checked.checked_kinds,
        judgment=judgment, override_reason=None if stored is None else stored.override_reason,
    )


@router.post("/grounded-replies/{inquiry_id}/draft")
async def write_draft(inquiry_id: str, now: Now) -> GroundedDraft:
    """Write a reply draft from the ledger, the fact cards, and the owner's rules.

    The model routes first. A question the facts cannot answer becomes a judgment for the owner
    and no draft is written.
    """
    context = await load_context(inquiry_id, now)
    route = await route_inquiry(context)
    if route.kind == "judgment":
        judgment = await open_judgment(context, route.issue)
        return GroundedDraft(
            draft="", claims=[], lock="unchecked", mismatch_count=0, checked_kinds=[],
            judgment=judgment_view(judgment, context.inquiry),
        )
    reply = await write_grounded_draft(context)
    await save_draft(context, reply)
    await close_open_judgments(context)
    checked = verification(reply.evaluation)
    return GroundedDraft(
        draft=reply.draft, claims=checked.claims, lock=checked.lock,
        mismatch_count=checked.mismatch_count, checked_kinds=checked.checked_kinds,
    )


@router.post("/grounded-replies/{inquiry_id}/verify")
async def verify(inquiry_id: str, body: VerifyRequest, db: Session, now: Now) -> Verification:
    """Check the text the owner is editing, without a model call."""
    inquiry = await db.get(InquiryRow, inquiry_id)
    if inquiry is None:
        raise HTTPException(404, "inquiry not found")
    stored = await db.get(GroundingRow, inquiry_id)
    return verification(check_final(body.draft, await load_ledger(db, inquiry, now), stored))


@router.post("/grounded-replies/{inquiry_id}/decision")
async def decide(inquiry_id: InquiryId, body: GroundedDecision, db: Session, now: Now) -> Inquiry:
    """Approve a reply like the existing decision route, but keep a locked draft until a reason is given."""
    row = await locked_inquiry(inquiry_id, body.expected_revision, db)
    text = body.draft.strip()
    if not text:
        raise HTTPException(422, "blank reply cannot be completed")
    stored = await upsert_grounding(db, inquiry_id)
    evaluation = check_final(text, await load_ledger(db, row, now), stored)
    if evaluation.lock == "locked" and body.override_reason is None:
        raise HTTPException(409, "draft does not match the ledger")
    row.status = "approved"
    row.draft = text
    row.revision += 1
    await db.flush()
    remember_decision(db, stored, FinalText(text, evaluation, body.override_reason), now)
    await db.flush()
    return Inquiry.model_validate(row)


@dataclass(frozen=True, slots=True)
class FinalText:
    """The approved text, its check, and the reason given for sending it despite a lock."""

    text: str
    evaluation: Evaluation
    reason: str | None


def remember_decision(db: AsyncSession, stored: GroundingRow, final: FinalText, now: datetime) -> None:
    """Store the final check and record the approval, with what a completed reply is shown as later."""
    evaluation = final.evaluation
    overridden = evaluation.lock == "locked"
    stored.lock_state = "overridden" if overridden else evaluation.lock
    stored.override_reason = final.reason if overridden else None
    stored.claims_json = [claim_to_json(claim) for claim in evaluation.claims]
    seconds = None if stored.generated_at is None else int((now - stored.generated_at).total_seconds())
    if overridden:
        record_event(db, stored, "override", {
            "reason": final.reason or "", "mismatches": mismatches(evaluation.claims),
        }, now)
    claims: list[JsonValue] = [*stored.claims_json]
    checked: list[JsonValue] = [*evaluation.checked]
    record_event(db, stored, "approved", {
        "unedited": final.text == (stored.generated_draft or "").strip(), "seconds": seconds,
        "lock": evaluation.lock, "override": overridden,
        "digest": digest_of(final.text), "claims": claims, "checked": checked,
    }, now)
