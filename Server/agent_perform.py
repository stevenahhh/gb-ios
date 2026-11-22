"""Plan, decide, run, and record one tool call, raise what waits for the owner, and purge old undo text.

Each step commits with its own record in one transaction, so nothing changes without a step that says so.
"""

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import uuid4

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import null, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_mask import Masker, honored, unmasked
from agent_policy import decide
from agent_store import (
    RESULT_CHARS,
    StepDraft,
    add_step,
    auto_count,
    policy_settings,
    proposal_view,
    step_view,
)
from agent_tables import AgentProposalRow, AgentStepRow
from agent_toolkit import (
    RevisionConflictError,
    TargetGoneError,
    ToolArgsError,
    ToolRefusedError,
    refusal_text,
)
from agent_tools import TOOLS
from agent_types import (
    PROPOSAL_LIFETIME,
    Plan,
    PolicyContext,
    ProposalDraft,
    ProposalView,
    RunSource,
    StepView,
    TargetRef,
    Tool,
    ToolCall,
    ToolEnv,
    Verdict,
)
from b_k14_models import OutreachQuoteRow
from database import transaction
from display import local
from models import (
    BookingRow,
    CalendarEventRow,
    ClassSessionRow,
    ContentDraftRow,
    InquiryRow,
    OrderRow,
    ShipmentRow,
    TaskRow,
)

LOGGER: Final = logging.getLogger("roundup.agent")


BAD_ARGS: Final = "무슨 뜻인지 잘 모르겠어요. 조금만 더 풀어서 얘기해 주세요."


UNKNOWN_TOOL: Final = "이건 비서한테 맡기실 수 없어요."


CONFLICT: Final = "그사이 내용이 달라졌어요. 새로고침해서 봐 주세요."


GONE: Final = "그 일이 안 보여요. 그새 바뀌었을지도 몰라요."


STORAGE: Final = "중간에 문제가 생겼어요. 앱에서 상태를 봐 주세요."


READ_TARGET: Final = TargetRef("session", "", "")


NEW_TARGET: Final = "new"
SUPERSEDED: Final = "새로 하신 말씀을 따를게요."


REVISIONED: Final = {
    "booking": BookingRow,
    "order": OrderRow,
    "shipment": ShipmentRow,
    "session": ClassSessionRow,
    "event": CalendarEventRow,
    "task": TaskRow,
    "content": ContentDraftRow,
    "quote": OutreachQuoteRow,
}


@dataclass(frozen=True, slots=True)
class RunContext:
    """One run's fixed facts: who asked and how, when, and how to mask what leaves it."""

    run_id: str
    turn: str | None
    now: datetime
    masker: Masker
    aliases: Mapping[str, str]
    source: RunSource = "chat"


@dataclass(frozen=True, slots=True)
class Judged:
    """One call the policy ruled on: the tool, its plan, the step it would record, and what is missing."""

    tool: Tool
    plan: Plan
    draft: StepDraft
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProposalSeed:
    """Everything a proposal keeps so approval can run it exactly as it was shown."""

    tool: Tool
    reason: str
    args: Mapping[str, JsonValue]
    target: TargetRef | None
    preview: Sequence[tuple[str, str]]
    evidence_needed: Sequence[str]
    dedupe_key: str | None = None
    owner_text: str | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class Performed:
    """What one call did, with the step and any proposal, and the text the model sees."""

    step: StepView
    proposal: ProposalView | None
    for_model: str
    acted: bool


async def current_revision(db: AsyncSession, target: TargetRef) -> int | None:
    """Read a target's revision as it is now."""
    if target.kind == "inquiry":
        return await db.scalar(select(InquiryRow.revision).where(InquiryRow.id == target.id))
    model = REVISIONED.get(target.kind)
    if model is None:
        return None
    return await db.scalar(select(model.revision).where(model.id == target.id))


def proposal_row(step: AgentStepRow, seed: ProposalSeed, now: datetime, masker: Masker) -> AgentProposalRow:
    """Prepare a proposal that approval can run exactly as it was shown."""
    target = seed.target
    return AgentProposalRow(
        id=f"proposal-{uuid4().hex}",
        step_id=step.id,
        tool=seed.tool.rule.name,
        title=seed.title or seed.tool.title,
        reason=seed.reason,
        preview=[{"label": label, "value": masker.text(value)} for label, value in seed.preview],
        evidence_needed=list(seed.evidence_needed),
        args={"args": dict(seed.args), "owner_text": seed.owner_text},
        target_kind=None if target is None else target.kind,
        target_id=None if target is None else target.id,
        target_label=None if target is None else masker.text(target.label),
        expected_revision=None if target is None else target.revision,
        dedupe_key=seed.dedupe_key,
        state="open",
        expires_at=now + PROPOSAL_LIFETIME,
        created_at=now,
    )


def for_model(step: StepDraft, text: str, limit: int = 3000) -> str:
    """Say what happened in the form the model reads next."""
    return json.dumps(
        {"decision": step.decision, "reason": step.reason, "result": text[:limit]},
        ensure_ascii=False,
    )


async def stored(db: AsyncSession, context: RunContext, draft: StepDraft, text: str = "") -> Performed:
    """Record a step that changed nothing and say so to the model."""
    row = await add_step(db, context.run_id, draft, context.now)
    return Performed(step_view(row), None, for_model(draft, text), acted=False)


async def attempt(context: RunContext, call: ToolCall) -> Performed:
    """Do one requested call in its own transaction, which rolls back whatever it changed on failure."""
    async with transaction() as db:
        return await perform_in(db, context, call)


async def perform(context: RunContext, call: ToolCall) -> Performed:
    """Do one requested call and record what happened, even when the tool itself fails."""
    [outcome] = await asyncio.gather(attempt(context, call), return_exceptions=True)
    if isinstance(outcome, Performed):
        return outcome
    if not isinstance(outcome, Exception):
        raise outcome
    LOGGER.warning("agent_step_failed", extra={"error_type": type(outcome).__name__})
    async with transaction() as db:
        return await stored(
            db,
            context,
            StepDraft(
                context.masker.text(call.name)[:60],
                "T0",
                "못 끝낸 일",
                context.masker.args(call.arguments),
                "refused",
                STORAGE,
            ),
        )


async def perform_in(db: AsyncSession, context: RunContext, call: ToolCall) -> Performed:
    """Plan, decide, and run one call inside its transaction."""
    masked_args = context.masker.args(call.arguments)
    tool = TOOLS.get(call.name)
    if tool is None:
        return await stored(
            db,
            context,
            StepDraft(
                context.masker.text(call.name)[:60],
                "T0",
                "못 맡는 일",
                masked_args,
                "refused",
                UNKNOWN_TOOL,
            ),
        )
    env = ToolEnv(now=context.now, turn=context.turn, aliases=context.aliases)
    try:
        plan = await tool.plan(db, unmasked(call.arguments, context.aliases), env)
    except ToolArgsError:
        return await stored(
            db,
            context,
            StepDraft(
                tool.rule.name,
                tool.rule.tier,
                tool.title,
                masked_args,
                "refused",
                BAD_ARGS,
            ),
        )
    verdict = decide(
        tool.rule,
        plan.claims,
        PolicyContext(
            turn=context.turn,
            today=local(context.now).date(),
            settings=await policy_settings(db),
            resolution=plan.resolution,
            auto_today=await auto_count(db, context.now),
            checks=plan.checks,
            source=context.source,
        ),
    )
    spoken = (name for *_, name in honored(context.turn or ""))
    masker = Masker.of((*context.masker.names, *spoken))
    judged = judge(tool, masked_args, verdict, masker, plan)
    if verdict.decision == "auto":
        return await run_auto(db, context, judged)
    if verdict.decision == "proposed":
        return await raise_for_call(db, context, judged)
    return await stored(db, context, judged.draft)


def judge(
    tool: Tool,
    masked_args: dict[str, JsonValue],
    verdict: Verdict,
    masker: Masker,
    plan: Plan,
) -> Judged:
    """Write a verdict down as a step draft, with evidence excerpts masked."""
    candidates = plan.resolution.candidates
    draft = StepDraft(
        tool.rule.name,
        tool.rule.tier,
        tool.title,
        masked_args,
        verdict.decision,
        verdict.reason,
        tuple(replace(item, excerpt=masker.text(item.excerpt)) for item in verdict.evidence),
        target=shown(candidates[0], masker) if len(candidates) == 1 else None,
    )
    return Judged(tool, plan, draft, verdict.missing)


def shown(target: TargetRef | None, masker: Masker) -> TargetRef | None:
    """Show a target's label without any name, phone, or address the owner's screen must not carry."""
    return None if target is None else replace(target, label=masker.text(target.label))


async def run_auto(db: AsyncSession, context: RunContext, judged: Judged) -> Performed:
    """Run an allowed call under a savepoint; whatever stops it becomes an honest step."""
    tool, draft = judged.tool, judged.draft
    older = await open_twin(db, tool, draft.target, context.now)
    try:
        async with db.begin_nested():
            outcome = await judged.plan.execute(db, draft.target or READ_TARGET)
    except RevisionConflictError:
        conflict = replace(judged, draft=replace(draft, decision="proposed", reason=CONFLICT), missing=())
        return await raise_for_call(db, context, conflict, refresh=True)
    except TargetGoneError:
        return await stored(db, context, replace(draft, decision="clarify", reason=GONE))
    except (ToolRefusedError, HTTPException, SQLAlchemyError) as error:
        return await stored(db, context, replace(draft, decision="refused", reason=refused_reason(error)))
    if older is not None:
        supersede(older, context.now)
    summary = context.masker.text(outcome.summary)
    done = replace(
        draft,
        target=shown(outcome.target, context.masker) or draft.target,
        result=summary[:RESULT_CHARS],
        revision_after=None if outcome.target is None else outcome.target.revision,
        undo=outcome.undo if tool.undo is not None else None,
    )
    row = await add_step(db, context.run_id, done, context.now)
    return Performed(step_view(row), None, for_model(done, summary), acted=tool.rule.tier != "T0")


def refused_reason(error: Exception) -> str:
    """Say in Korean why a call did not go through; storage failures are logged by type only."""
    if isinstance(error, ToolRefusedError):
        return error.reason
    if isinstance(error, HTTPException):
        return refusal_text(error)
    LOGGER.warning("agent_storage_refused", extra={"error_type": type(error).__name__})
    return STORAGE


async def open_twin(
    db: AsyncSession,
    tool: Tool,
    target: TargetRef | None,
    now: datetime,
) -> AgentProposalRow | None:
    """Lock the card that still waits for the same tool and row; an expired one no longer counts.

    The card is locked before the row it points at, the order in which an approval takes them.
    """
    if target is None or target.id in {"", NEW_TARGET}:
        return None
    return await db.scalar(
        select(AgentProposalRow)
        .where(
            AgentProposalRow.state == "open",
            AgentProposalRow.expires_at > now,
            AgentProposalRow.tool == tool.rule.name,
            AgentProposalRow.target_id == target.id,
            AgentProposalRow.target_kind == target.kind,
        )
        .order_by(AgentProposalRow.created_at.desc(), AgentProposalRow.id.desc())
        .limit(1)
        .with_for_update(),
    )


def is_same_card(older: AgentProposalRow, newer: AgentProposalRow) -> bool:
    """Tell whether an open card already asks for exactly this, on the row as it is now."""
    return (older.args, older.preview, older.expected_revision) == (
        newer.args,
        newer.preview,
        newer.expected_revision,
    )


def supersede(proposal: AgentProposalRow, now: datetime) -> None:
    """Close an older card the owner's newer request replaces, so one card per tool and row is open."""
    proposal.state, proposal.decided_at, proposal.result = "dismissed", now, SUPERSEDED


async def raise_for_call(
    db: AsyncSession,
    context: RunContext,
    judged: Judged,
    *,
    refresh: bool = False,
) -> Performed:
    """Turn a call into a proposal; an equal open one is reused and any other older one steps aside."""
    tool, target = judged.tool, judged.draft.target
    if refresh and target is not None:
        target = replace(target, revision=await current_revision(db, target))
    draft = replace(judged.draft, target=shown(target, context.masker))
    older = await open_twin(db, tool, target, context.now)
    step = await add_step(db, context.run_id, draft, context.now)
    seed = ProposalSeed(
        tool,
        draft.reason,
        judged.plan.args,
        target,
        judged.plan.preview,
        judged.missing,
        owner_text=context.turn if tool.rule.name == "register_invoice" else None,
    )
    row = proposal_row(step, seed, context.now, context.masker)
    if older is not None and is_same_card(older, row):
        told = for_model(draft, "이미 올린 제안이 있어요.")
        return Performed(step_view(step), proposal_view(older), told, acted=False)
    if older is not None:
        supersede(older, context.now)
    db.add(row)
    await db.flush()
    told = for_model(draft, "제안으로 올렸어요. 사장님이 확인해야 해요.")
    return Performed(step_view(step), proposal_view(row), told, acted=False)


async def raise_proposal(
    run_id: str,
    draft: ProposalDraft,
    now: datetime,
    masker: Masker,
) -> ProposalView | None:
    """Raise one proposal without a model call; nothing when its key was used or an open card asks for it."""
    tool = TOOLS[draft.tool]
    async with transaction() as db:
        used = (
            draft.dedupe_key is not None
            and await db.scalar(
                select(AgentProposalRow.id).where(AgentProposalRow.dedupe_key == draft.dedupe_key),
            )
            is not None
        )
        if used or await open_twin(db, tool, draft.target, now) is not None:
            return None
        try:
            async with db.begin_nested():
                step = await add_step(
                    db,
                    run_id,
                    StepDraft(
                        tool.rule.name,
                        tool.rule.tier,
                        draft.title,
                        masker.args(draft.args),
                        "proposed",
                        draft.reason,
                        (),
                        shown(draft.target, masker),
                    ),
                    now,
                )
                row = proposal_row(
                    step,
                    ProposalSeed(
                        tool,
                        draft.reason,
                        draft.args,
                        draft.target,
                        draft.preview,
                        draft.evidence_needed,
                        draft.dedupe_key,
                        title=draft.title,
                    ),
                    now,
                    masker,
                )
                db.add(row)
                await db.flush()
        except IntegrityError:
            return None
        return proposal_view(row)


async def purge_undo_data(db: AsyncSession, now: datetime) -> None:
    """Drop text kept only for undo once a step is too old to be undone, which makes it not undoable."""
    _ = await db.execute(
        update(AgentStepRow)
        .where(
            AgentStepRow.undo_path.is_not(None),
            AgentStepRow.undo_until < now,
        )
        .values(undo_data=null(), undo_path=None),
    )


async def purge_old_undo(now: datetime) -> None:
    """Purge old undo text on its own, for the worker's tick."""
    async with transaction() as db:
        await purge_undo_data(db, now)
