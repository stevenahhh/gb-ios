"""Routes of the grounded reply engine (K25): state, draft, recheck, approval, and A/B metrics."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Final, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k25_claims import Claim, Evaluation, Lock, claim_to_json
from b_k25_engine import (
    Arm,
    check_final,
    close_open_judgments,
    load_context,
    open_judgment,
    record_event,
    route_inquiry,
    save_draft,
    save_plain_draft,
    write_grounded_draft,
    write_plain_draft,
)
from b_k25_ledger import load_ledger
from b_k25_tables import GroundedEventRow, GroundingRow, JudgmentRow
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

    kind: Literal["price", "seats", "date", "deposit", "fact", "rule"]
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

    arm: Arm
    draft: str
    claims: list[ClaimView]
    lock: Lock
    mismatch_count: int
    judgment: JudgmentView | None = None


class ReplyState(ApiModel):
    """What the inquiry screen shows about the saved draft; no arm means it was never drafted here."""

    inquiry_id: str
    arm: Arm | None
    claims: list[ClaimView]
    lock: Lock
    mismatch_count: int
    judgment: JudgmentView | None
    override_reason: str | None


class Verification(ApiModel):
    """The check of a text the owner is editing."""

    claims: list[ClaimView]
    lock: Lock
    mismatch_count: int


class VerifyRequest(ApiRequest):
    """The text as it stands in the editor."""

    draft: Annotated[str, Field(max_length=MAX_TEXT)]


class GroundedDecision(ApiRequest):
    """Approval of a reply; a locked one needs a reason to be sent as it is."""

    decision: Literal["approve"]
    draft: Annotated[str, Field(max_length=MAX_TEXT)]
    expected_revision: Revision
    override_reason: Annotated[str, Field(min_length=1, max_length=MAX_REASON_CHARS)] | None = None


class ArmMetrics(ApiModel):
    """Measured results of one arm; rates are null until there is something to divide."""

    arm: Arm
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
        mismatch_count=mismatches(evaluation.claims),
    )


@router.get("/grounded-replies/metrics")
async def metrics(
    db: Session, now: Now, start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> list[ArmMetrics]:
    """Report each arm's results for the given days, by default the last four weeks."""
    first = start or now.date() - DEFAULT_WINDOW
    last = end or now.date()
    events = list(await db.scalars(
        select(GroundedEventRow).where(
            GroundedEventRow.created_at >= day_start(first),
            GroundedEventRow.created_at < next_day_start(last),
        ),
    ))
    arms: tuple[Arm, ...] = ("control", "grounded")
    return [arm_metrics(arm, [event for event in events if event.arm == arm]) for arm in arms]


def arm_metrics(arm: Arm, events: Sequence[GroundedEventRow]) -> ArmMetrics:
    """Summarize one arm; an approval without a measured time counts but is left out of the median."""
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
    return ArmMetrics(
        arm=arm, approvals=len(approved), unedited_approvals=unedited,
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
    """Check the saved draft again and return the claims the inquiry screen shows."""
    inquiry = await db.get(InquiryRow, inquiry_id)
    if inquiry is None:
        raise HTTPException(404, "inquiry not found")
    stored = await db.get(GroundingRow, inquiry_id)
    judgment = await open_judgment_view(db, inquiry)
    if stored is None or stored.generated_draft is None:
        return ReplyState(
            inquiry_id=inquiry_id, arm=None if stored is None else arm_of(stored), claims=[],
            lock="unchecked", mismatch_count=0, judgment=judgment,
            override_reason=None if stored is None else stored.override_reason,
        )
    evaluation = check_final(inquiry.draft, await load_ledger(db, inquiry, now), stored)
    checked = verification(evaluation)
    return ReplyState(
        inquiry_id=inquiry_id, arm=arm_of(stored), claims=checked.claims, lock=checked.lock,
        mismatch_count=checked.mismatch_count, judgment=judgment, override_reason=stored.override_reason,
    )


def arm_of(row: GroundingRow) -> Arm:
    """Read a stored arm."""
    return "grounded" if row.ab_arm == "grounded" else "control"


@router.post("/grounded-replies/{inquiry_id}/draft")
async def write_draft(inquiry_id: str, now: Now) -> GroundedDraft:
    """Write a reply draft: the control arm as before, the grounded arm from the ledger and rules.

    The model routes first. A question the facts cannot answer becomes a judgment for the owner
    and no draft is written.
    """
    context = await load_context(inquiry_id, now)
    if context.arm == "control":
        plain = await write_plain_draft(context)
        await save_plain_draft(context, plain)
        return GroundedDraft(arm="control", draft=plain, claims=[], lock="unchecked", mismatch_count=0)
    route = await route_inquiry(context)
    if route.kind == "judgment":
        judgment = await open_judgment(context, route.issue)
        return GroundedDraft(
            arm="grounded", draft="", claims=[], lock="unchecked", mismatch_count=0,
            judgment=judgment_view(judgment, context.inquiry),
        )
    reply = await write_grounded_draft(context)
    await save_draft(context, reply)
    await close_open_judgments(context)
    checked = verification(reply.evaluation)
    return GroundedDraft(
        arm="grounded", draft=reply.draft, claims=checked.claims, lock=checked.lock,
        mismatch_count=checked.mismatch_count,
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
    stored = await db.get(GroundingRow, inquiry_id, with_for_update=True)
    evaluation = check_final(text, await load_ledger(db, row, now), stored)
    if evaluation.lock == "locked" and body.override_reason is None:
        raise HTTPException(409, "draft does not match the ledger")
    row.status = "approved"
    row.draft = text
    row.revision += 1
    await db.flush()
    if stored is not None:
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
    """Store the final check and record the approval for the A/B test."""
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
    record_event(db, stored, "approved", {
        "unedited": final.text == (stored.generated_draft or "").strip(), "seconds": seconds,
        "lock": evaluation.lock, "override": overridden,
    }, now)
