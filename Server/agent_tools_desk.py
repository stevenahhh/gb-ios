"""Internal, reversible tools (T1): the owner's calendar, tasks, content drafts, and reply drafts."""

from datetime import datetime, time, timedelta
from typing import Annotated, Final

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_toolkit import (
    Definition,
    Located,
    ToolArgs,
    ToolArgsError,
    build,
    local_clock,
    local_date,
    lock_row,
    name_confidence,
    named_in,
)
from agent_tools_read import DateText
from agent_types import (
    BY_IDENTIFIER,
    Claim,
    Outcome,
    Resolution,
    TargetRef,
    Tool,
    ToolEnv,
    UndoInput,
    UndoTicket,
)
from display import SEOUL, clock_or_all_day, is_all_day, local, month_day_weekday
from models import CalendarEventRow, TaskRow
from schedule import EventCreate, add_owner_event, reschedule
from tasks import set_done

EVENTS_FROM: Final = timedelta(days=1)


ALL_DAY: Final = time(23, 59, 59)


NEW: Final = "new"


ASKS_ADD: Final = "일정|캘린더|넣|추가|잡아|등록|적어|메모|알림"


ASKS_MOVE: Final = "옮|미뤄|미루|당겨|당기|바꿔|바꾸|변경|연기|조정"


ASKS_COMPLETE: Final = "끝|완료|마쳤|마무리|했|됐|처리|체크"


ASKS_REOPEN: Final = "다시|되돌|열어|미완료"


type ClockText = Annotated[str, Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM (24시간)")]


type Reference = Annotated[str, Field(min_length=1, max_length=200)]


def when_text(moment: datetime) -> str:
    """Name a moment the way the owner reads it."""
    return f"{month_day_weekday(local(moment).date())} {clock_or_all_day(moment)}"


def moment_of(day_text: str, clock_text: str | None) -> datetime:
    """Turn a day and an optional time into a Seoul moment; no time means all day."""
    day = local_date(day_text)
    clock = local_clock(clock_text) if clock_text else ALL_DAY
    if day is None or clock is None:
        message = "unreadable day or time"
        raise ToolArgsError(message)
    return datetime.combine(day.date(), clock, SEOUL)


def owner_claims(asks: str, named: Claim, *, only: bool) -> tuple[Claim, ...]:
    """Require the owner to ask for the action and name the row; the only open row needs no name."""
    asked = Claim("요청", asks, "words")
    return (asked,) if only else (asked, named)


class EventArgs(ToolArgs):
    """A new calendar entry."""

    title: Annotated[str, Field(min_length=1, max_length=100, description="일정 제목")]
    day: DateText
    time: Annotated[ClockText | None, Field(description="시작 시각. 비우면 종일.")] = None
    detail: Annotated[str, Field(max_length=500, description="메모")] = ""


async def locate_new_event(db: AsyncSession, args: EventArgs, env: ToolEnv) -> Located:
    """Point at the entry that will be created."""
    del db, env
    moment = moment_of(args.day, args.time)
    return Located(
        Resolution((TargetRef("event", NEW, f"{args.title} · {when_text(moment)}"),), BY_IDENTIFIER),
        claims=owner_claims(ASKS_ADD, named_in("일정", args.title), only=False),
        preview=(("일정", args.title), ("때", when_text(moment)), ("메모", args.detail)),
    )


async def add_event(db: AsyncSession, args: EventArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Store a calendar entry the owner asked for."""
    del target, env
    event = await add_owner_event(
        db,
        EventCreate(
            title=args.title,
            kind="todo",
            detail=args.detail,
            starts_at=moment_of(args.day, args.time),
        ),
    )
    return Outcome(
        f"일정을 넣었어요: {event.title} · {when_text(event.starts_at)}",
        TargetRef("event", event.id, event.title, event.revision),
        UndoTicket("/calendar/events"),
    )


async def remove_event(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Take back an entry the assistant added, unless someone changed it since."""
    event = await lock_row(db, CalendarEventRow, undo.target.id, undo.target.revision)
    await db.delete(event)
    await db.flush()
    return Outcome(f"일정을 지웠어요: {event.title}")


class EventMoveArgs(ToolArgs):
    """Move an existing calendar entry."""

    event: Reference = Field(description="옮길 일정 제목")
    day: Annotated[DateText | None, Field(description="옮길 날짜. 비우면 같은 날.")] = None
    time: Annotated[ClockText | None, Field(description="옮길 시각. 비우면 같은 시각.")] = None


async def upcoming_events(db: AsyncSession, now: datetime) -> list[CalendarEventRow]:
    """Read entries from yesterday on, so a late one can still be moved."""
    rows = await db.scalars(
        select(CalendarEventRow)
        .where(CalendarEventRow.starts_at >= now - EVENTS_FROM)
        .order_by(CalendarEventRow.starts_at),
    )
    return list(rows)


def moved_moment(event: CalendarEventRow, args: EventMoveArgs) -> datetime:
    """Work out the new moment, keeping the part that was not given."""
    if args.day is None and args.time is None:
        message = "nothing to move"
        raise ToolArgsError(message)
    old = local(event.starts_at)
    day = args.day or old.date().isoformat()
    return moment_of(day, args.time or (None if is_all_day(old) else old.strftime("%H:%M")))


async def locate_event(db: AsyncSession, args: EventMoveArgs, env: ToolEnv) -> Located:
    """Find the one entry with this title."""
    rows = await upcoming_events(db, env.now)
    found = [
        (event, score)
        for event in rows
        if (score := name_confidence(args.event, event.title)) is not None
    ]
    candidates = tuple(TargetRef("event", event.id, event.title, event.revision) for event, _ in found)
    confidence = max((score for _, score in found), default=BY_IDENTIFIER)
    preview: tuple[tuple[str, str], ...] = ()
    if len(found) == 1:
        moment = moved_moment(found[0][0], args)
        preview = (
            ("일정", found[0][0].title),
            ("지금", when_text(found[0][0].starts_at)),
            ("옮길 때", when_text(moment)),
        )
    return Located(
        Resolution(candidates, confidence, "옮길 일정을 찾지 못했어요."),
        claims=owner_claims(ASKS_MOVE, named_in("일정", args.event), only=len(rows) == 1),
        preview=preview,
    )


async def move_event(db: AsyncSession, args: EventMoveArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Reschedule one calendar entry."""
    del env
    event = await lock_row(db, CalendarEventRow, target.id, target.revision)
    previous = event.starts_at
    reschedule(event, moved_moment(event, args))
    await db.flush()
    return Outcome(
        f"일정을 옮겼어요: {event.title} · {when_text(event.starts_at)}",
        TargetRef("event", event.id, event.title, event.revision),
        UndoTicket(f"/calendar/events/{event.id}/move", {"starts_at": previous.isoformat()}),
    )


async def move_event_back(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Return a moved entry to its earlier moment."""
    event = await lock_row(db, CalendarEventRow, undo.target.id, undo.target.revision)
    reschedule(event, datetime.fromisoformat(str(undo.data["starts_at"])))
    await db.flush()
    return Outcome(f"일정을 되돌렸어요: {event.title} · {when_text(event.starts_at)}")


class TaskArgs(ToolArgs):
    """One owner task, named by its title."""

    task: Reference = Field(description="할 일 제목")


def task_targets(found: list[tuple[TaskRow, float]]) -> Resolution:
    """Point at the tasks the reference names."""
    candidates = tuple(TargetRef("task", task.id, task.title, task.revision) for task, _ in found)
    return Resolution(
        candidates,
        max((score for _, score in found), default=BY_IDENTIFIER),
        "그 할 일을 찾지 못했어요.",
    )


async def locate_open_task(db: AsyncSession, args: TaskArgs, env: ToolEnv) -> Located:
    """Find the open task to complete."""
    del env
    query = select(TaskRow).where(TaskRow.status == "open").order_by(TaskRow.due_at)
    rows = list(await db.scalars(query))
    found = [(task, score) for task in rows if (score := name_confidence(args.task, task.title)) is not None]
    preview = (("할 일", found[0][0].title),) if len(found) == 1 else ()
    claims = owner_claims(ASKS_COMPLETE, named_in("할 일", args.task), only=len(rows) == 1)
    return Located(task_targets(found), claims=claims, preview=preview)


async def locate_done_task(db: AsyncSession, args: TaskArgs, env: ToolEnv) -> Located:
    """Find the completed task to open again, newest completions first."""
    del env
    query = select(TaskRow).where(TaskRow.status == "done").order_by(TaskRow.completed_at.desc())
    rows = list(await db.scalars(query))
    found = [(task, score) for task in rows if (score := name_confidence(args.task, task.title)) is not None]
    preview = (("할 일", found[0][0].title),) if len(found) == 1 else ()
    claims = owner_claims(ASKS_REOPEN, named_in("할 일", args.task), only=len(rows) == 1)
    return Located(task_targets(found), claims=claims, preview=preview)


async def complete_task(db: AsyncSession, args: TaskArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Mark a task done."""
    del args
    task = await lock_row(db, TaskRow, target.id, target.revision)
    set_done(task, env.now, done=True)
    await db.flush()
    return Outcome(
        f"할 일을 완료로 바꿨어요: {task.title}",
        TargetRef("task", task.id, task.title, task.revision),
        UndoTicket(f"/tasks/{task.id}/undo"),
    )


async def reopen_task(db: AsyncSession, args: TaskArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Open a completed task again."""
    del args
    task = await lock_row(db, TaskRow, target.id, target.revision)
    finished = task.completed_at or env.now
    set_done(task, env.now, done=False)
    await db.flush()
    return Outcome(
        f"할 일을 다시 열었어요: {task.title}",
        TargetRef("task", task.id, task.title, task.revision),
        UndoTicket(f"/tasks/{task.id}/completion", {"completed_at": finished.isoformat()}),
    )


async def undo_complete(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Open a task the assistant completed."""
    task = await lock_row(db, TaskRow, undo.target.id, undo.target.revision)
    set_done(task, undo.now, done=False)
    await db.flush()
    return Outcome(f"할 일을 다시 열었어요: {task.title}")


async def undo_reopen(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Complete a task the assistant reopened."""
    task = await lock_row(db, TaskRow, undo.target.id, undo.target.revision)
    set_done(task, datetime.fromisoformat(str(undo.data["completed_at"])), done=True)
    await db.flush()
    return Outcome(f"할 일을 완료로 바꿨어요: {task.title}")


DESK: Final[tuple[Tool, ...]] = (
    build(
        Definition(
            "add_event",
            "T1",
            "none",
            "일정 넣기",
            "캘린더에 새 일정을 넣습니다. 손님 예약에는 쓰지 않습니다.",
            EventArgs,
            locate_new_event,
            add_event,
            remove_event,
        ),
    ),
    build(
        Definition(
            "move_event",
            "T1",
            "none",
            "일정 옮기기",
            "사장님이 넣은 일정의 날짜나 시각을 바꿉니다.",
            EventMoveArgs,
            locate_event,
            move_event,
            move_event_back,
        ),
    ),
    build(
        Definition(
            "complete_task",
            "T1",
            "none",
            "할 일 완료",
            "할 일을 완료로 바꿉니다.",
            TaskArgs,
            locate_open_task,
            complete_task,
            undo_complete,
        ),
    ),
    build(
        Definition(
            "reopen_task",
            "T1",
            "none",
            "할 일 다시 열기",
            "완료한 할 일을 다시 엽니다.",
            TaskArgs,
            locate_done_task,
            reopen_task,
            undo_reopen,
        ),
    ),
)
