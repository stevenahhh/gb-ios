"""Write and check one grounded reply (K25): route, draft, extract, and compare with the ledger.

Facts are read in a short transaction before any model call and results are stored in another
one after it, so no connection waits for the model.
"""

import hashlib
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from typing import Final, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai import generate
from ai_output import reply_problems
from assistant import shop_facts
from b_k25_claims import (
    Evaluation,
    Ledger,
    ModelClaim,
    SessionFact,
    claim_to_json,
    claims_from_json,
    days_named,
    deferral_only,
    evaluate,
    mentions,
    parse_model_claims,
    recheck,
    seat_spans,
)
from b_k25_ledger import load_ledger
from b_k25_prompts import (
    EXTRACT_SAMPLING,
    NAME_PLACEHOLDER,
    ROUTE_SAMPLING,
    Route,
    basis_text,
    draft_messages,
    extract_messages,
    parse_route,
    route_messages,
)
from b_k25_tables import GroundedEventRow, GroundingRow, JudgmentRow
from database import transaction
from models import InquiryRow
from prompts import DRAFT_SAMPLING, Inquiry, ShopFacts
from prompts import draft_messages as plain_draft_messages
from providers import chat

type Arm = Literal["control", "grounded"]
type EventKind = Literal[
    "draft", "approved", "override", "judgment_opened", "judgment_answered", "judgment_dismissed",
]
LOGGER: Final = logging.getLogger("roundup.grounded")
ATTEMPTS: Final = 2
MAX_FALLBACK_SESSIONS: Final = 2
UPSTREAM_STATUSES: Final = frozenset({502, 503})


@dataclass(frozen=True, slots=True)
class Context:
    """Everything one reply needs, read before any model call."""

    inquiry: InquiryRow
    ledger: Ledger
    shop: ShopFacts
    arm: Arm
    stored: GroundingRow | None
    now: datetime


@dataclass(frozen=True, slots=True)
class WrittenReply:
    """A draft, how it was checked, and whether the model was able to write it."""

    draft: str
    evaluation: Evaluation
    is_fallback: bool


def arm_for(inquiry_id: str) -> Arm:
    """Split inquiries in half by a stable hash, so reopening one never changes its arm."""
    return "grounded" if hashlib.sha256(inquiry_id.encode()).digest()[0] % 2 == 0 else "control"


async def load_context(inquiry_id: str, now: datetime) -> Context:
    """Read the inquiry, its ledger, and its earlier check."""
    shop = await shop_facts()
    async with transaction() as db:
        inquiry = await db.get(InquiryRow, inquiry_id)
        if inquiry is None:
            raise HTTPException(404, "inquiry not found")
        stored = await db.get(GroundingRow, inquiry_id)
        ledger = await load_ledger(db, inquiry, now)
    arm: Arm = arm_for(inquiry_id)
    if stored is not None and stored.ab_arm in {"control", "grounded"}:
        arm = "grounded" if stored.ab_arm == "grounded" else "control"
    return Context(inquiry, ledger, shop, arm, stored, now)


def unsupported_seats(text: str, sources: str) -> list[str]:
    """Report seat counts that appear nowhere in the facts or the customer's question."""
    known = {span.value for span in seat_spans(sources)}
    return [
        f"근거 없는 자리 수 {span.value}자리" for span in seat_spans(text) if span.value not in known
    ]


def grounded_problems(text: str, basis: str, question: str) -> list[str]:
    """Extend the reply check with seat counts; it only decides a retry, the ledger decides the lock."""
    problems = reply_problems(text, basis, question)
    if not text:
        return problems
    return problems + unsupported_seats(text, f"{basis}\n{question}")


async def route_inquiry(context: Context) -> Route:
    """Ask whether the facts answer the question; a malformed or failed answer means a draft."""
    for _ in range(ATTEMPTS):
        try:
            raw = await chat(route_messages(context.ledger, context.shop), ROUTE_SAMPLING)
        except HTTPException as error:
            LOGGER.warning("route_fallback", extra={"error_type": type(error).__name__})
            break
        answer = parse_route(raw)
        if answer is not None:
            return answer
    return Route("draft")


async def write_plain_draft(context: Context) -> str:
    """Write the control arm's draft exactly as the existing draft route does."""
    inquiry = Inquiry(
        context.inquiry.customer, context.inquiry.subject, context.inquiry.question,
        tuple(context.inquiry.facts),
    )
    basis = "\n".join([*inquiry.facts, context.shop.text])
    question = f"{context.inquiry.subject}\n{context.inquiry.question}"
    check = partial(reply_problems, basis=basis, question=question)
    return await generate(plain_draft_messages(inquiry, context.shop), DRAFT_SAMPLING, check)


def fallback_draft(context: Context) -> str:
    """Answer from the ledger alone when the model could not write a usable reply."""
    ledger = context.ledger
    asks_class = any(mentions(ledger.question, name) for name in ledger.class_names)
    named: tuple[SessionFact, ...] = ()
    if asks_class or days_named(ledger.question, ledger.today):
        named = ledger.dated_sessions("")
    lines = [f"{context.inquiry.customer} 님, 문의 주셔서 감사해요."]
    lines += [
        f"{session.label} {session.title}에는 남은 자리가 {session.seats_left}자리예요."
        for session in named[:MAX_FALLBACK_SESSIONS]
    ]
    lines.append("자세한 내용은 확인해서 다시 알려드릴게요.")
    return " ".join(lines)


async def extract_claims(template: str, customer: str) -> tuple[ModelClaim, ...] | None:
    """Ask the model for the statements in a draft; a failed answer means the check stays open.

    The model reads the draft before the customer's name is filled in, so the name stays here.
    """
    try:
        raw = await chat(extract_messages(template), EXTRACT_SAMPLING)
    except HTTPException as error:
        LOGGER.warning("extract_fallback", extra={"error_type": type(error).__name__})
        return None
    claims = parse_model_claims(raw, template)
    if claims is None:
        return None
    return tuple(replace(claim, text=claim.text.replace(NAME_PLACEHOLDER, customer)) for claim in claims)


async def write_grounded_draft(context: Context, owner_answer: str = "") -> WrittenReply:
    """Write a grounded draft, then check every number it states against the ledger."""
    messages = draft_messages(context.ledger, context.shop, owner_answer=owner_answer)
    basis = basis_text(context.ledger, context.shop)
    question = context.ledger.question
    is_fallback = False
    try:
        raw = await generate(
            messages, DRAFT_SAMPLING, partial(grounded_problems, basis=basis, question=question),
        )
    except HTTPException as error:
        if error.status_code not in UPSTREAM_STATUSES:
            raise
        LOGGER.warning("draft_fallback", extra={"error_type": type(error).__name__})
        raw, is_fallback = fallback_draft(context), True
    customer = context.inquiry.customer
    draft = raw.replace(NAME_PLACEHOLDER, customer)
    found = None if is_fallback else await extract_claims(raw, customer)
    return WrittenReply(draft, evaluate(draft, context.ledger, found), is_fallback)


def check_final(draft: str, ledger: Ledger, stored: GroundingRow | None) -> Evaluation:
    """Check the text the owner is about to approve, without asking the model again."""
    if stored is None or stored.ab_arm != "grounded":
        return Evaluation((), "unchecked", extraction_ok=False)
    kept = claims_from_json(stored.claims_json)
    return recheck(draft, ledger, kept, extraction_ok=stored.extraction_ok)


async def upsert_grounding(db: AsyncSession, inquiry_id: str, arm: Arm) -> GroundingRow:
    """Create the row on the first attempt and lock it for the write that follows."""
    _ = await db.execute(
        insert(GroundingRow).values(inquiry_id=inquiry_id, ab_arm=arm)
        .on_conflict_do_nothing(index_elements=[GroundingRow.inquiry_id]),
    )
    row = await db.get(GroundingRow, inquiry_id, with_for_update=True, populate_existing=True)
    if row is None:
        raise HTTPException(404, "inquiry not found")
    return row


def record_event(
    db: AsyncSession, row: GroundingRow, kind: EventKind, data: dict[str, JsonValue], now: datetime,
) -> None:
    """Add one measured step of the A/B test, stamped with the request clock."""
    db.add(GroundedEventRow(
        inquiry_id=row.inquiry_id, arm=row.ab_arm, kind=kind, data=data, created_at=now,
    ))


def empty_card_fields(ledger: Ledger) -> list[JsonValue]:
    """Fact columns that stay blank for the classes in question; they explain a deferral."""
    missing: list[JsonValue] = []
    for card in ledger.cards_of(""):
        for name, value in (
            ("includedMaterials", card.included_materials), ("parking", card.parking),
            ("refundPolicy", card.refund_policy), ("priceWon", card.price_won),
        ):
            if value is None:
                missing.append(f"{card.class_name}.{name}")
    return missing


async def save_draft(context: Context, reply: WrittenReply) -> None:
    """Keep the checked draft and its claims; nothing is written to the inquiry itself."""
    evaluation = reply.evaluation
    async with transaction() as db:
        row = await upsert_grounding(db, context.inquiry.id, context.arm)
        row.claims_json = [claim_to_json(claim) for claim in evaluation.claims]
        row.lock_state = evaluation.lock
        row.generated_draft = reply.draft
        row.generated_at = context.now
        row.extraction_ok = evaluation.extraction_ok
        record_event(db, row, "draft", {
            "lock": evaluation.lock, "extraction": evaluation.extraction_ok,
            "fallback": reply.is_fallback,
            "deferral": deferral_only(reply.draft, evaluation.claims),
            "emptyFields": empty_card_fields(context.ledger),
            "mismatches": sum(claim.status == "mismatched" for claim in evaluation.claims),
        }, context.now)


async def save_plain_draft(context: Context, draft: str) -> None:
    """Keep the control arm's draft so an unedited approval can be counted; it is never locked."""
    async with transaction() as db:
        row = await upsert_grounding(db, context.inquiry.id, context.arm)
        row.generated_draft = draft
        row.generated_at = context.now
        record_event(db, row, "draft", {"lock": "unchecked", "deferral": False}, context.now)


async def open_judgment(context: Context, issue: str) -> JudgmentRow:
    """Raise one open judgment for an inquiry, reusing the one it already has."""
    async with transaction() as db:
        row = await upsert_grounding(db, context.inquiry.id, context.arm)
        created = await db.scalar(
            insert(JudgmentRow).values(
                id=f"judgment-{uuid4().hex}", inquiry_id=context.inquiry.id, issue=issue,
            ).on_conflict_do_nothing(
                index_elements=[JudgmentRow.inquiry_id], index_where=text("status = 'open'"),
            ).returning(JudgmentRow.id),
        )
        judgment = await db.scalar(
            select(JudgmentRow).where(
                JudgmentRow.inquiry_id == context.inquiry.id, JudgmentRow.status == "open",
            ),
        )
        if judgment is None:
            raise HTTPException(409, "judgment is already answered")
        if created is not None:
            record_event(db, row, "judgment_opened", {"issue": judgment.issue}, context.now)
    return judgment


async def close_open_judgments(context: Context) -> None:
    """Retire an open judgment when the facts now answer the question."""
    async with transaction() as db:
        row = await upsert_grounding(db, context.inquiry.id, context.arm)
        judgment = await db.scalar(
            select(JudgmentRow).where(
                JudgmentRow.inquiry_id == context.inquiry.id, JudgmentRow.status == "open",
            ).with_for_update(),
        )
        if judgment is None:
            return
        judgment.status = "dismissed"
        record_event(db, row, "judgment_dismissed", {"by": "redraft"}, context.now)

