"""The owner's answers to proposals, and undoing a finished step."""

from collections.abc import Mapping
from datetime import datetime
from typing import Final

from fastapi import HTTPException
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_mask import Masker
from agent_perform import GONE, READ_TARGET
from agent_settings import stop_requested
from agent_store import (
    RESULT_CHARS,
    UNDO_KEPT_FOR,
    expire_proposals,
    policy_settings,
    proposal_view,
    step_view,
    undo_closed,
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
from agent_tools_read import customer_names
from agent_types import (
    Outcome,
    ProposalView,
    TargetKind,
    TargetRef,
    Tool,
    ToolEnv,
    UndoInput,
    UndoResult,
)
from database import transaction

LOCK_NOT_AVAILABLE: Final = "55P03"
HELD: Final = "다른 곳에서 처리하고 있어요. 잠시 뒤 다시 확인해 주세요."
STORED_ARGS: Final = TypeAdapter(dict[str, JsonValue])
CLOSED: Final[Mapping[str, str]] = {
    "approved": "이미 승인한 제안이에요.",
    "dismissed": "이미 하지 않기로 한 제안이에요.",
    "expired": "승인할 수 있는 시간이 지난 제안이에요.",
}
TARGET_KIND: Final[TypeAdapter[TargetKind]] = TypeAdapter(TargetKind)


async def require_on(db: AsyncSession) -> None:
    """Refuse an action while the owner has the assistant off."""
    if await stop_requested(db):
        raise HTTPException(409, "비서가 꺼져 있어요.")


async def require_tool_on(db: AsyncSession, tool: str) -> None:
    """Refuse an approval of a tool the owner switched off after it was proposed."""
    if (await policy_settings(db)).per_tool.get(tool) == "off":
        raise HTTPException(409, "꺼 두신 일이에요. 설정에서 켠 뒤 다시 승인해 주세요.")


async def open_proposal(db: AsyncSession, proposal_id: str, now: datetime) -> AgentProposalRow:
    """Lock a proposal and require that it is still open; a held one answers at once, so no caller waits."""
    await expire_proposals(db, now)
    try:
        row = await db.scalar(
            select(AgentProposalRow)
            .where(AgentProposalRow.id == proposal_id)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True),
        )
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
            raise
        raise HTTPException(409, HELD) from None
    if row is None:
        raise HTTPException(404, "제안을 찾지 못했어요.")
    if row.state != "open":
        raise HTTPException(409, CLOSED[row.state])
    return row


def pinned_target(row: AgentProposalRow) -> TargetRef | None:
    """Rebuild the target a proposal was raised for."""
    if row.target_kind is None:
        return None
    return TargetRef(
        TARGET_KIND.validate_python(row.target_kind),
        row.target_id or "",
        row.target_label or "",
        row.expected_revision,
    )


async def approve(proposal_id: str, expected_revision: int | None, now: datetime) -> ProposalView:
    """Run an open proposal exactly as it was shown; a changed row stops it and it stays open."""
    async with transaction() as db:
        await require_on(db)
        row = await open_proposal(db, proposal_id, now)
        await require_tool_on(db, row.tool)
        if expected_revision != row.expected_revision:
            raise HTTPException(409, "그사이 내용이 바뀌었어요. 다시 확인해 주세요.")
        tool = TOOLS[row.tool]
        step = await db.get_one(AgentStepRow, row.step_id, with_for_update=True)
        outcome = await approved_outcome(db, row, tool, now)
        text = Masker.of(await customer_names(db)).text(outcome.summary)
        row.state, row.decided_at, row.result = "approved", now, text
        settled(step, outcome, text, now)
        await db.flush()
    return proposal_view(row, step)


async def approved_outcome(
    db: AsyncSession,
    row: AgentProposalRow,
    tool: Tool,
    now: datetime,
) -> Outcome:
    """Run the proposal's stored call against its own target, in Korean errors only."""
    payload = STORED_ARGS.validate_python(row.args)
    stored_args, owner_text = payload.get("args"), payload.get("owner_text")
    env = ToolEnv(
        now=now,
        pinned=pinned_target(row),
        owner_text=owner_text if isinstance(owner_text, str) else None,
    )
    try:
        plan = await tool.plan(db, stored_args if isinstance(stored_args, dict) else {}, env)
        async with db.begin_nested():
            return await plan.execute(db, env.pinned or READ_TARGET)
    except ToolArgsError:
        raise HTTPException(409, "제안을 실행할 수 없어요. 빠진 값을 말씀해 주세요.") from None
    except RevisionConflictError:
        raise HTTPException(409, "그사이 바뀌어서 처리하지 못했어요. 다시 확인해 주세요.") from None
    except TargetGoneError:
        raise HTTPException(404, GONE) from None
    except ToolRefusedError as error:
        raise HTTPException(409, error.reason) from None
    except HTTPException as error:
        raise HTTPException(409, refusal_text(error)) from None


def settled(step: AgentStepRow, outcome: Outcome, result: str, now: datetime) -> None:
    """Record on the step what the approval did, so it can be undone."""
    step.result = result[:RESULT_CHARS]
    if outcome.target is not None:
        step.target_kind, step.target_id = outcome.target.kind, outcome.target.id
        step.target_label, step.revision_after = outcome.target.label, outcome.target.revision
    if outcome.undo is not None:
        step.undo_path, step.undo_data = outcome.undo.path, dict(outcome.undo.data)
        step.undo_until = now + UNDO_KEPT_FOR


async def dismiss(proposal_id: str, now: datetime) -> ProposalView:
    """Set a proposal aside; nothing runs."""
    async with transaction() as db:
        row = await open_proposal(db, proposal_id, now)
        row.state, row.decided_at = "dismissed", now
        await db.flush()
    return proposal_view(row)


async def undo_step(step_id: str, now: datetime) -> UndoResult:
    """Reverse one finished step when nothing changed it since."""
    async with transaction() as db:
        step = await db.scalar(
            select(AgentStepRow)
            .where(AgentStepRow.id == step_id)
            .with_for_update()
            .execution_options(populate_existing=True),
        )
        if step is None:
            raise HTTPException(404, "그 일의 기록을 찾지 못했어요.")
        if step.undone_at is not None:
            raise HTTPException(409, "이미 되돌렸어요.")
        if undo_closed(step, now):
            raise HTTPException(409, "되돌릴 수 있는 시간이 지났어요.")
        tool = TOOLS.get(step.tool)
        if step.undo_path is None or tool is None or tool.undo is None or step.target_kind is None:
            raise HTTPException(409, "되돌릴 수 없는 일이에요.")
        target = TargetRef(
            TARGET_KIND.validate_python(step.target_kind),
            step.target_id or "",
            step.target_label or "",
            step.revision_after,
        )
        try:
            async with db.begin_nested():
                outcome = await tool.undo(db, UndoInput(target, step.undo_data or {}, now))
        except RevisionConflictError:
            raise HTTPException(409, "그사이 바뀌어서 되돌릴 수 없어요.") from None
        except TargetGoneError:
            raise HTTPException(404, "되돌릴 대상이 없어졌어요.") from None
        except ToolRefusedError as error:
            raise HTTPException(409, error.reason) from None
        except HTTPException as error:
            raise HTTPException(409, refusal_text(error)) from None
        masker = Masker.of(await customer_names(db))
        step.undone_at, step.undo_data = now, None
        await db.flush()
        return UndoResult(step=step_view(step), summary=masker.text(outcome.summary))
