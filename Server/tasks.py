"""Owner tasks, including material orders and channel chores."""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import SessionCompletion
from common import Now, Session, invalid_transition, locked, matches
from contracts import Card, CardAction, CardUndo, Status
from display import relative_moment
from models import TaskRow

router = APIRouter()


def task_card(task: TaskRow, today: date) -> Card:
    """Present a chore with its completion action."""
    done = task.status == "done"
    return Card(
        id=task.id, kind="task", title=task.title, lines=[task.detail], tag="채널", revision=task.revision,
        status=Status(text="완료", tone="done") if done else None,
        deadline=None if done else f"{relative_moment(task.due_at, today)}까지",
        action=None if done else CardAction(code="completeTask", label="완료 표시"),
        undo=CardUndo(path=f"/tasks/{task.id}/undo") if done else None,
    )


async def open_channel_tasks(db: AsyncSession, today: date, text: str = "") -> list[Card]:
    """List unfinished channel chores by due time."""
    conditions = [TaskRow.kind == "channel", TaskRow.status == "open"]
    if text:
        conditions.append(matches(TaskRow.title, text))
    rows = await db.scalars(select(TaskRow).where(*conditions).order_by(TaskRow.due_at, TaskRow.id).limit(50))
    return [task_card(task, today) for task in rows]


@router.post("/tasks/{task_id}/completion")
async def set_task_completion(task_id: str, body: SessionCompletion, db: Session, now: Now) -> Card:
    """Complete a task or reopen it."""
    task = await locked(db, TaskRow, task_id, body.expected_revision)
    if (task.status == "done") == body.done:
        raise invalid_transition()
    task.status = "done" if body.done else "open"
    task.completed_at = now if body.done else None
    task.revision += 1
    await db.flush()
    return task_card(task, now.date())
