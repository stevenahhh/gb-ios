"""HTTP of the assistant agent: runs, proposals, steps, settings, and notes; errors are Korean."""

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from agent_approvals import approve, dismiss, undo_step
from agent_hcx import ToolChat, hcx_tool_chat
from agent_memory import delete_memory, list_memories
from agent_run import kill_switch, queue_run, recent_runs, run_agent, run_detail
from agent_settings import DEFAULT_SETTINGS, load_settings
from agent_settings_edit import SettingsUpdate, SettingsView, settings_view, update_settings
from agent_store import open_proposals, proposal_view
from agent_types import (
    ApproveRequest,
    MemoryList,
    ProposalList,
    ProposalView,
    RunList,
    RunRequest,
    RunResponse,
    RunView,
    UndoResult,
)
from common import Now, Session
from database import transaction

router = APIRouter(prefix="/agent")


def tool_chat() -> ToolChat:
    """Provide the chat model that may ask for tools; tests replace it."""
    return hcx_tool_chat


Chat = Annotated[ToolChat, Depends(tool_chat)]


@router.post("/run")
async def run(body: RunRequest, now: Now, chat: Chat) -> RunResponse:
    """Answer the owner's message, or queue it when the app asks for a background run and it is on."""
    if body.background and not await kill_switch():
        return await queue_run(body, now)
    return await run_agent(body, now, chat)


@router.get("/runs")
async def runs(now: Now, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> RunList:
    """List recent runs, newest first."""
    return RunList(items=await recent_runs(limit, now))


@router.get("/runs/{run_id}")
async def run_status(run_id: str, now: Now) -> RunView:
    """Show one run's progress, steps, and proposals."""
    return await run_detail(run_id, now)


@router.get("/proposals")
async def proposals(now: Now) -> ProposalList:
    """List the proposals waiting for the owner."""
    async with transaction() as db:
        return ProposalList(items=[proposal_view(row) for row in await open_proposals(db, now)])


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, body: ApproveRequest, now: Now) -> ProposalView:
    """Run a proposal exactly as the owner saw it."""
    return await approve(proposal_id, body.expected_revision, now)


@router.post("/proposals/{proposal_id}/dismiss")
async def dismiss_proposal(proposal_id: str, now: Now) -> ProposalView:
    """Set a proposal aside."""
    return await dismiss(proposal_id, now)


@router.post("/steps/{step_id}/undo")
async def undo(step_id: str, now: Now) -> UndoResult:
    """Reverse a finished step if nothing changed it since."""
    return await undo_step(step_id, now)


@router.get("/settings")
async def settings() -> SettingsView:
    """Show the owner's switches; without a stored row every run is off, so the screen says off."""
    async with transaction() as db:
        stored = await load_settings(db)
    return settings_view(stored or replace(DEFAULT_SETTINGS, mode="off"))


@router.put("/settings")
async def save_settings(body: SettingsUpdate, now: Now) -> SettingsView:
    """Change the owner's switches."""
    async with transaction() as db:
        return settings_view(await update_settings(db, body, now))


@router.get("/memories")
async def memories(db: Session) -> MemoryList:
    """List the owner's own notes."""
    return MemoryList(items=await list_memories(db))


@router.delete("/memories/{memory_id}", status_code=204)
async def forget_memory(memory_id: str, db: Session, now: Now) -> Response:
    """Forget one note."""
    await delete_memory(db, memory_id, now)
    return Response(status_code=204)
