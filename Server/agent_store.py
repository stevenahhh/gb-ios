"""Store and read the agent's runs, steps, proposals, and switches, and hold the owner's lock."""

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import uuid4

from fastapi import HTTPException
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_settings import load_settings
from agent_tables import AgentProposalRow, AgentRunRow, AgentStepRow
from agent_types import (
    Decision,
    EvidenceItem,
    EvidenceView,
    PolicySettings,
    PreviewLine,
    ProposalState,
    ProposalView,
    RunSource,
    RunStatus,
    RunView,
    StepView,
    TargetKind,
    TargetRef,
    TargetView,
    Tier,
    UndoTicket,
)
from database import get_engine
from display import day_start, local
from prompts import Intent

LOCK_CLASS: Final = 0x61676E74
"""Advisory lock class of the assistant; the schema name picks the lock within it."""
BUSY: Final = "앞선 요청을 처리하고 있어요. 끝나면 다시 말씀해 주세요."
UNAVAILABLE: Final = "지금은 처리할 수 없어요. 잠시 뒤 다시 시도해 주세요."
NO_ANSWER: Final = "지금은 답할 수 없어요. 잠시 뒤 다시 시도해 주세요."
RESULT_CHARS: Final = 500
TARGET_KIND: Final[TypeAdapter[TargetKind]] = TypeAdapter(TargetKind)
DECISION: Final[TypeAdapter[Decision]] = TypeAdapter(Decision)
STATUS: Final[TypeAdapter[RunStatus]] = TypeAdapter(RunStatus)
SOURCE: Final[TypeAdapter[RunSource]] = TypeAdapter(RunSource)
STATE: Final[TypeAdapter[ProposalState]] = TypeAdapter(ProposalState)
INTENT: Final[TypeAdapter[Intent]] = TypeAdapter(Intent)
EVIDENCE: Final = TypeAdapter(list[EvidenceView])


class AgentBusyError(Exception):
    """Another run holds the owner's lock."""


@dataclass(frozen=True, slots=True)
class RunEnd:
    """How a run ended: its status, the owner's answer, a short error code, and the turn's intent."""

    status: RunStatus
    answer: str | None = None
    error: str | None = None
    intent: Intent | None = None


@dataclass(frozen=True, slots=True)
class StepDraft:
    """One recorded step; every personal value in it is already masked."""

    tool: str
    tier: Tier
    title: str
    args: dict[str, JsonValue]
    decision: Decision
    reason: str
    evidence: tuple[EvidenceItem, ...] = ()
    target: TargetRef | None = None
    result: str | None = None
    revision_after: int | None = None
    undo: UndoTicket | None = None


@asynccontextmanager
async def owner_lock() -> AsyncGenerator[None]:
    """Hold the owner's lock for one run; a busy lock raises at once so nobody waits behind a run."""
    try:
        async with get_engine().connect() as connection, connection.begin():
            held = await connection.scalar(
                select(func.pg_try_advisory_xact_lock(LOCK_CLASS, func.hashtext(func.current_schema()))),
            )
            if not held:
                raise AgentBusyError
            yield
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        raise HTTPException(503, UNAVAILABLE) from error


async def policy_settings(db: AsyncSession) -> PolicySettings:
    """Read the owner's switches; a missing row is treated as off."""
    stored = await load_settings(db)
    if stored is None:
        return PolicySettings(mode="off")
    return PolicySettings(mode=stored.mode, per_tool=dict(stored.per_tool), daily_cap=stored.daily_cap)


async def auto_count(db: AsyncSession, now: datetime) -> int:
    """Count today's automatic internal and work actions, in workshop time."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(AgentStepRow)
            .where(
                AgentStepRow.decision == "auto",
                AgentStepRow.tier != "T0",
                AgentStepRow.created_at >= day_start(local(now).date()),
            ),
        )
        or 0
    )


def new_run(source: RunSource, question: str, status: RunStatus, now: datetime) -> AgentRunRow:
    """Prepare a run row; `question` must already be masked."""
    return AgentRunRow(
        id=f"run-{uuid4().hex}",
        source=source,
        question=question,
        status=status,
        created_at=now,
        started_at=now if status == "running" else None,
    )


async def open_run(
    db: AsyncSession,
    row: AgentRunRow,
    request_id: str | None,
    request: dict[str, JsonValue] | None,
) -> tuple[str, bool]:
    """Insert a run once per request id; the same id returns the run that already answers it."""
    if request_id is None:
        row.request = request
        db.add(row)
        await db.flush()
        return row.id, True
    created = await db.scalar(
        insert(AgentRunRow)
        .values(
            id=row.id,
            request_id=request_id,
            source=row.source,
            question=row.question,
            request=request,
            status=row.status,
            created_at=row.created_at,
            started_at=row.started_at,
        )
        .on_conflict_do_nothing(index_elements=[AgentRunRow.request_id])
        .returning(AgentRunRow.id),
    )
    if created is not None:
        return created, True
    existing = await db.scalar(select(AgentRunRow.id).where(AgentRunRow.request_id == request_id))
    if existing is None:
        raise HTTPException(503, UNAVAILABLE)
    return existing, False


UNDO_KEPT_FOR: Final = timedelta(hours=48)


async def add_step(db: AsyncSession, run_id: str, draft: StepDraft, now: datetime) -> AgentStepRow:
    """Record one step at the end of its run."""
    latest = await db.scalar(
        select(func.max(AgentStepRow.seq)).where(AgentStepRow.run_id == run_id),
    )
    row = AgentStepRow(
        id=f"step-{uuid4().hex}",
        run_id=run_id,
        seq=(latest or 0) + 1,
        tool=draft.tool,
        tier=draft.tier,
        title=draft.title,
        args=draft.args,
        decision=draft.decision,
        reason=draft.reason,
        evidence=[{"kind": item.kind, "excerpt": item.excerpt} for item in draft.evidence],
        target_kind=None if draft.target is None else draft.target.kind,
        target_id=None if draft.target is None else draft.target.id,
        target_label=None if draft.target is None else draft.target.label,
        result=draft.result,
        revision_before=None if draft.target is None else draft.target.revision,
        revision_after=draft.revision_after,
        undo_path=None if draft.undo is None else draft.undo.path,
        undo_data=None if draft.undo is None else dict(draft.undo.data),
        undo_until=None if draft.undo is None else now + UNDO_KEPT_FOR,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return row


def undo_closed(row: AgentStepRow, now: datetime) -> bool:
    """Tell whether the time to take a step back has passed."""
    return row.undo_until is not None and now > row.undo_until


def target_view(kind: str | None, target_id: str | None, label: str | None) -> TargetView | None:
    """Present a stored target."""
    if kind is None or target_id is None:
        return None
    return TargetView(kind=TARGET_KIND.validate_python(kind), id=target_id, label=label or "")


def step_view(row: AgentStepRow, now: datetime | None = None) -> StepView:
    """Present a recorded step; without `now` it has just run."""
    return StepView(
        id=row.id,
        tool=row.tool,
        title=row.title,
        decision=DECISION.validate_python(row.decision),
        reason=row.reason,
        target=target_view(row.target_kind, row.target_id, row.target_label),
        evidence=EVIDENCE.validate_python(row.evidence),
        undoable=row.undo_path is not None
        and row.undone_at is None
        and (now is None or not undo_closed(row, now)),
        undone=row.undone_at is not None,
    )


def proposal_view(
    row: AgentProposalRow, step: AgentStepRow | None = None, now: datetime | None = None,
) -> ProposalView:
    """Present a stored proposal, with the step it became once the owner approved it."""
    return ProposalView(
        id=row.id,
        step_id=row.step_id,
        step=None if step is None or row.state != "approved" else step_view(step, now),
        title=row.title,
        reason=row.reason,
        preview=[PreviewLine.model_validate(line) for line in row.preview],
        evidence_needed=row.evidence_needed,
        expires_at=local(row.expires_at).isoformat(timespec="seconds"),
        expected_revision=row.expected_revision,
        tool=row.tool,
        state=STATE.validate_python(row.state),
        target=target_view(row.target_kind, row.target_id, row.target_label),
    )


def moment_text(moment: datetime | None) -> str | None:
    """Format a stored moment for the client."""
    return None if moment is None else local(moment).isoformat(timespec="seconds")


def run_view(
    row: AgentRunRow,
    steps: Sequence[AgentStepRow] = (),
    proposals: Sequence[AgentProposalRow] = (),
    now: datetime | None = None,
) -> RunView:
    """Present a stored run; a proposal the owner approved carries the step it became."""
    by_id = {step.id: step for step in steps}
    return RunView(
        id=row.id,
        status=STATUS.validate_python(row.status),
        source=SOURCE.validate_python(row.source),
        question=row.question,
        answer=row.answer,
        intent=None if row.intent is None else INTENT.validate_python(row.intent),
        model_calls=row.model_calls,
        tokens=row.tokens,
        error=row.error,
        created_at=moment_text(row.created_at) or "",
        started_at=moment_text(row.started_at),
        ended_at=moment_text(row.ended_at),
        steps=[step_view(step, now) for step in steps],
        proposals=[proposal_view(found, by_id.get(found.step_id), now) for found in proposals],
    )


async def run_views(db: AsyncSession, rows: Sequence[AgentRunRow], now: datetime) -> list[RunView]:
    """Present runs with their steps and proposals, loaded once per table rather than once per run."""
    ids = [row.id for row in rows]
    steps: dict[str, list[AgentStepRow]] = {}
    found_steps = await db.scalars(
        select(AgentStepRow).where(AgentStepRow.run_id.in_(ids)).order_by(AgentStepRow.seq),
    )
    for step in found_steps:
        steps.setdefault(step.run_id, []).append(step)
    proposals: dict[str, list[AgentProposalRow]] = {}
    pairs = await db.execute(
        select(AgentStepRow.run_id, AgentProposalRow)
        .join(AgentProposalRow, AgentProposalRow.step_id == AgentStepRow.id)
        .where(AgentStepRow.run_id.in_(ids)).order_by(AgentStepRow.seq),
    )
    for run_id, proposal in pairs.tuples():
        proposals.setdefault(run_id, []).append(proposal)
    return [run_view(row, steps.get(row.id, ()), proposals.get(row.id, ()), now) for row in rows]


async def steps_of(db: AsyncSession, run_id: str) -> list[AgentStepRow]:
    """Read a run's steps in order."""
    return list(
        await db.scalars(
            select(AgentStepRow).where(AgentStepRow.run_id == run_id).order_by(AgentStepRow.seq),
        ),
    )


async def proposals_of(db: AsyncSession, run_id: str) -> list[AgentProposalRow]:
    """Read the proposals a run raised, in step order."""
    return list(
        await db.scalars(
            select(AgentProposalRow)
            .join(AgentStepRow, AgentStepRow.id == AgentProposalRow.step_id)
            .where(AgentStepRow.run_id == run_id)
            .order_by(AgentStepRow.seq),
        ),
    )


async def expire_proposals(db: AsyncSession, now: datetime) -> None:
    """Close proposals whose time passed."""
    _ = await db.execute(
        update(AgentProposalRow)
        .where(AgentProposalRow.state == "open", AgentProposalRow.expires_at <= now)
        .values(state="expired", decided_at=now),
    )


async def open_proposals(db: AsyncSession, now: datetime) -> list[AgentProposalRow]:
    """Read the proposals still waiting, soonest to expire first."""
    await expire_proposals(db, now)
    return list(
        await db.scalars(
            select(AgentProposalRow)
            .where(AgentProposalRow.state == "open")
            .order_by(AgentProposalRow.expires_at, AgentProposalRow.created_at),
        ),
    )


async def finish(db: AsyncSession, run_id: str, end: RunEnd, now: datetime) -> None:
    """Close a run that is still queued or running; a finished run always has an answer to show."""
    _ = await db.execute(
        update(AgentRunRow)
        .where(AgentRunRow.id == run_id, AgentRunRow.status.in_(("queued", "running")))
        .values(
            status=end.status,
            ended_at=now,
            request=None,
            answer=end.answer or NO_ANSWER,
            error=end.error,
            intent=end.intent,
            started_at=func.coalesce(AgentRunRow.started_at, now),
        ),
    )
