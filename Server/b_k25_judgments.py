"""Judgments (K25): questions the facts could not answer, answered by the owner and turned into rules."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Annotated, Final, Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k25_claims import Ledger, RuleFact
from b_k25_engine import (
    Arm,
    Context,
    load_context,
    record_event,
    store_reply,
    upsert_grounding,
    write_grounded_draft,
)
from b_k25_numbers import number_tokens
from b_k25_prompts import (
    RULE_SAMPLING,
    RuleSuggestion,
    mask_contacts,
    parse_rule,
    rule_messages,
)
from b_k25_replies import (
    ClaimView,
    JudgmentView,
    judgment_view,
    verification,
)
from b_k25_rules import card_for_rule, save_rule
from b_k25_tables import JudgmentRow, card_id_for
from common import Now, Session, required_text
from contracts import ApiModel, ApiRequest
from database import transaction
from models import InquiryRow
from providers import chat

router = APIRouter()
RULE_ATTEMPTS: Final = 2
MAX_RULE_CHARS: Final = 200
MAX_ANSWER_CHARS: Final = 500
WHOLE_WORKSHOP: Final = "전체"
type Scope = Literal["rule", "once"]


class RulePreviewRequest(ApiRequest):
    """The owner's answer, before deciding whether it becomes a rule."""

    answer: Annotated[str, Field(min_length=1, max_length=MAX_ANSWER_CHARS)]


class RulePreview(ApiModel):
    """The sentence the answer would become and the class it would belong to."""

    rule_text: str
    class_name: str | None


class AnswerRequest(ApiRequest):
    """The owner's answer, and whether it is reused in later drafts."""

    answer: Annotated[str, Field(min_length=1, max_length=MAX_ANSWER_CHARS)]
    scope: Scope


class JudgmentAnswer(ApiModel):
    """The saved rule, if any, and the draft written again for the waiting customer."""

    judgment_id: str
    rule_text: str | None
    rule_id: str | None
    arm: Arm
    draft: str
    claims: list[ClaimView]
    lock: Literal["clear", "locked", "unchecked"]
    mismatch_count: int
    checked_kinds: list[str]


def class_of_question(ledger: Ledger) -> str | None:
    """Return the single class a question is about, or nothing when it names several or none."""
    named = [name for name in ledger.class_names if name in ledger.classes_named_in("")]
    return named[0] if len(named) == 1 else None


async def suggest_rule(issue: str, answer: str, class_names: Sequence[str]) -> RuleSuggestion:
    """Turn an answer into one reusable sentence that keeps every number the owner said."""
    spoken = mask_contacts(answer)
    wanted = number_tokens(spoken)
    for _ in range(RULE_ATTEMPTS):
        try:
            raw = await chat(rule_messages(issue, spoken, class_names), RULE_SAMPLING)
        except HTTPException:
            break
        suggestion = parse_rule(raw)
        if suggestion is None or len(suggestion.rule) > MAX_RULE_CHARS:
            continue
        if number_tokens(suggestion.rule) == wanted:
            return suggestion
    return RuleSuggestion(" ".join(spoken.split())[:MAX_RULE_CHARS], "")


def applied_class(suggestion: RuleSuggestion, context: Context) -> str | None:
    """Choose the class a rule belongs to; the model's name counts only when the class exists."""
    if suggestion.applies_to in context.ledger.class_names:
        return suggestion.applies_to
    if suggestion.applies_to == WHOLE_WORKSHOP:
        return None
    return class_of_question(context.ledger)


def anonymous(text: str, customer: str) -> str:
    """Keep a customer's name out of a rule other customers' drafts will quote."""
    return text.replace(customer, "손님") if len(customer.strip()) > 1 else text


async def open_judgment(db: AsyncSession, judgment_id: str) -> tuple[JudgmentRow, InquiryRow]:
    """Lock an open judgment, or refuse one that is already settled."""
    judgment = await db.scalar(
        select(JudgmentRow).where(JudgmentRow.id == judgment_id).with_for_update(),
    )
    if judgment is None:
        raise HTTPException(404, "resource not found")
    if judgment.status != "open":
        raise HTTPException(409, "judgment is already answered")
    inquiry = await db.get(InquiryRow, judgment.inquiry_id)
    if inquiry is None:
        raise HTTPException(404, "inquiry not found")
    return judgment, inquiry


@router.get("/judgments")
async def list_judgments(
    db: Session, status: Literal["open", "answered", "dismissed"] = "open",
) -> list[JudgmentView]:
    """Return judgments of inquiries that still wait for a reply, oldest first."""
    rows = await db.execute(
        select(JudgmentRow, InquiryRow).join(InquiryRow, InquiryRow.id == JudgmentRow.inquiry_id)
        .where(JudgmentRow.status == status, InquiryRow.status == "pending")
        .order_by(JudgmentRow.created_at, JudgmentRow.id),
    )
    return [judgment_view(judgment, inquiry) for judgment, inquiry in rows.tuples()]


@router.post("/judgments/{judgment_id}/rule-preview")
async def preview_rule(judgment_id: str, body: RulePreviewRequest, now: Now) -> RulePreview:
    """Show the sentence the answer would become; nothing is stored."""
    async with transaction() as db:
        judgment, _ = await open_judgment(db, judgment_id)
        issue, inquiry_id = judgment.issue, judgment.inquiry_id
    context = await load_context(inquiry_id, now)
    suggestion = await suggest_rule(issue, required_text(body.answer), context.ledger.class_names)
    return RulePreview(
        rule_text=anonymous(suggestion.rule, context.inquiry.customer),
        class_name=applied_class(suggestion, context),
    )


@router.post("/judgments/{judgment_id}/answer")
async def answer_judgment(judgment_id: str, body: AnswerRequest, now: Now) -> JudgmentAnswer:
    """Settle a judgment with the owner's words and write the waiting draft again.

    The rule is saved only for scope `rule`. The draft that follows is written from the rule or
    from this answer, and it is checked like any other.
    """
    answer = required_text(body.answer)
    async with transaction() as db:
        judgment, _ = await open_judgment(db, judgment_id)
        issue, inquiry_id = judgment.issue, judgment.inquiry_id
    context = await load_context(inquiry_id, now)
    suggestion = (
        await suggest_rule(issue, answer, context.ledger.class_names) if body.scope == "rule" else None
    )
    rule_text: str | None = None
    class_name: str | None = None
    if suggestion is not None:
        rule_text = anonymous(suggestion.rule, context.inquiry.customer)
        class_name = applied_class(suggestion, context)
    answered = answer_context(context, answer, rule_text, class_name)
    reply = await write_grounded_draft(answered, owner_answer="" if body.scope == "rule" else answer)
    async with transaction() as db:
        judgment, _ = await open_judgment(db, judgment_id)
        rule_id: str | None = None
        if rule_text is not None:
            card_id = None if class_name is None else await card_for_rule(
                db, class_name, card_id_for(class_name),
            )
            rule_id = await save_rule(db, card_id, rule_text, (issue, inquiry_id), now)
        judgment.status = "answered"
        judgment.answer_text = answer
        judgment.rule_id = rule_id
        judgment.answered_at = now
        row = await upsert_grounding(db, inquiry_id, context.arm)
        record_event(db, row, "judgment_answered", {"scope": body.scope}, now)
        store_reply(db, row, answered, reply)
    checked = verification(reply.evaluation)
    return JudgmentAnswer(
        judgment_id=judgment_id, rule_text=rule_text, rule_id=rule_id, arm=context.arm,
        draft=reply.draft, claims=checked.claims, lock=checked.lock,
        mismatch_count=checked.mismatch_count, checked_kinds=checked.checked_kinds,
    )


def answer_context(
    context: Context, answer: str, rule_text: str | None, class_name: str | None,
) -> Context:
    """Add the owner's words to what the redraft may rely on."""
    rules = context.ledger.rules
    if rule_text is not None:
        rules = (RuleFact(rule_text, class_name), *rules)
    ledger = replace(
        context.ledger, rules=rules,
        facts=context.ledger.facts if rule_text is not None else (*context.ledger.facts, answer),
        asked=f"{context.ledger.asked}\n{answer}",
    )
    return replace(context, ledger=ledger)


@router.post("/judgments/{judgment_id}/dismiss")
async def dismiss_judgment(judgment_id: str, db: Session, now: Now) -> JudgmentView:
    """Close a question without an answer; the reply stays an ordinary draft."""
    judgment, inquiry = await open_judgment(db, judgment_id)
    judgment.status = "dismissed"
    judgment.answered_at = now
    row = await upsert_grounding(db, judgment.inquiry_id, "grounded")
    record_event(db, row, "judgment_dismissed", {"by": "owner"}, now)
    await db.flush()
    return judgment_view(judgment, inquiry)
