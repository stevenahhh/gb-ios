"""Cancellation and quote-answer tools (T2); each needs the owner's current words."""

from typing import Annotated, Final, Literal

from pydantic import Field, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_toolkit import Definition, Located, ToolArgs, build, lock_row, name_confidence
from agent_tools_deals import Reference, booking_label
from agent_tools_orders import Match, claims_for, found_one
from agent_types import (
    BY_FULL_NAME,
    Claim,
    Outcome,
    TargetRef,
    Tool,
    ToolEnv,
    UndoInput,
    UndoTicket,
)
from b_k06_cancel import DecisionRequest, open_bookings, record_decision, revert_decision
from b_k14 import ORG_LABELS, OutcomeRequest, QuoteFields, save_outcome
from b_k14_models import OutreachQuoteRow
from display import won
from models import BookingRow, TaskRow

OPEN_QUOTES: Final = ("sent", "follow_up")

CANCEL_WORDS: Final = "취소|환불|이월"

DECISION_WORDS: Final = {"by_rule": "규정|규칙|정책", "carry_over": "이월", "full_refund": "전액"}

OUTCOME_WORDS: Final = {
    "accepted": "수락|확정|진행|계약|하기로|승낙",
    "accepted_adjusted": "조정|수정|변경|할인",
    "declined": "거절|취소|어렵|못 하|안 하",
    "no_reply": "답이 없|답 없|연락 없|무응답|무소식",
}

OUTCOME_LABELS: Final = {
    "accepted": "수락",
    "accepted_adjusted": "금액 바꿔 수락",
    "declined": "거절",
    "no_reply": "연락 없음",
}


class CancelArgs(ToolArgs):
    """A cancellation the owner decided."""

    booking: Reference = Field(description="취소할 예약의 손님 이름이나 수업 이름")
    decision: Literal["by_rule", "carry_over", "full_refund", "custom"] = Field(
        description="by_rule 규정대로, carry_over 이월, full_refund 전액 환불, custom 금액 지정",
    )
    refund_won: Annotated[int, Field(ge=0, description="custom일 때 환불 금액(원)")] | None = None
    reason: Annotated[str, Field(max_length=200, description="예외일 때 이유")] = ""


async def locate_cancel(db: AsyncSession, args: CancelArgs, env: ToolEnv) -> Located:
    """Find the one upcoming booking to cancel."""
    matches: list[Match] = []
    for booking, session, customer in await open_bookings(db, env.now):
        for label, value in (("손님", customer.name), ("수업", session.title)):
            score = name_confidence(args.booking, value, beside=(customer.name, session.title))
            if score is None:
                continue
            matches.append(
                Match(
                    TargetRef(
                        "booking",
                        booking.id,
                        booking_label(customer.name, session, booking.party_size),
                        booking.revision,
                    ),
                    score,
                    Claim(label, value if score >= BY_FULL_NAME else args.booking, "text"),
                ),
            )
            break
    claims: list[Claim] = [Claim("취소", CANCEL_WORDS, "words")]
    if args.decision == "custom":
        claims.append(Claim("돌려드릴 돈", str(args.refund_won or 0), "money"))
    else:
        claims.append(Claim("처리", DECISION_WORDS[args.decision], "words"))
    if args.reason:
        claims.append(Claim("이유", args.reason, "text"))
    decisions = {
        "by_rule": "규정대로",
        "carry_over": "이월",
        "full_refund": "전액 환불로 적기",
        "custom": f"돌려드릴 돈 {won(args.refund_won or 0)}으로 적어 두기",
    }
    preview = ()
    if len(matches) == 1:
        preview = (
            ("할 일", "예약 취소하기"),
            ("예약", matches[0].target.label),
            ("처리", decisions[args.decision]),
            *((("이유", args.reason),) if args.reason else ()),
        )
    located = found_one(matches, "취소할 예약이 안 보여요.")
    return Located(located.resolution, claims_for(matches, *claims), preview=preview)


async def cancel(db: AsyncSession, args: CancelArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Record the owner's cancellation decision; no money moves and nothing is sent."""
    _ = await lock_row(db, BookingRow, target.id, target.revision)
    view = await record_decision(
        db,
        target.id,
        DecisionRequest(
            decision=args.decision,
            reason=args.reason,
            refund_won=args.refund_won,
            expected_revision=0 if target.revision is None else target.revision,
        ),
        env.now,
    )
    revised = await db.get_one(BookingRow, target.id, populate_existing=True)
    refund = (
        f"돌려드릴 돈은 {won(view.refund)}으로 적어 뒀어요. 돈을 돌려드리는 건 사장님이 해 주세요. "
        if view.refund > 0
        else ""
    )
    return Outcome(
        f"취소 끝. {refund}손님 쪽으로는 아무 연락도 안 갔어요.",
        TargetRef("booking", target.id, target.label, revised.revision),
        UndoTicket(f"/cancellations/cases/{view.case_id}/undo", {"case_id": view.case_id}),
    )


async def undo_cancel(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Give a cancelled booking its seats back."""
    _ = await lock_row(db, BookingRow, undo.target.id, undo.target.revision)
    _ = await revert_decision(db, str(undo.data["case_id"]))
    return Outcome("취소했던 예약을 되살렸어요.")


class QuoteArgs(ToolArgs):
    """How an institution answered a quote."""

    quote: Reference = Field(description="기관 이름")
    outcome: Literal["accepted", "accepted_adjusted", "declined", "no_reply"] = Field(
        description="accepted 수락, accepted_adjusted 조정 후 수락, declined 거절, no_reply 무응답",
    )
    final_total_krw: (
        Annotated[int, Field(gt=0, description="최종 금액. 조정 후 수락이면 꼭 있어야 함.")] | None
    ) = None


def quote_title(row: OutreachQuoteRow) -> str:
    """Name a quote by its institution."""
    fields = QuoteFields.model_validate(row.fields)
    return fields.org_name or f"{ORG_LABELS[fields.org_type]} 출장 수업"


async def locate_quote(db: AsyncSession, args: QuoteArgs, env: ToolEnv) -> Located:
    """Find the one open quote of the institution."""
    del env
    rows = await db.scalars(
        select(OutreachQuoteRow)
        .where(
            OutreachQuoteRow.outcome.is_(None),
            OutreachQuoteRow.status.in_(OPEN_QUOTES),
        )
        .order_by(OutreachQuoteRow.created_at.desc()),
    )
    matches: list[Match] = []
    for row in rows:
        title = quote_title(row)
        score = name_confidence(args.quote, title)
        if score is not None:
            matches.append(
                Match(
                    TargetRef("quote", row.id, title, row.revision),
                    score,
                    Claim("기관", title if score >= BY_FULL_NAME else args.quote, "text"),
                ),
            )
    claims = [Claim("결과", OUTCOME_WORDS[args.outcome], "words")]
    if args.final_total_krw is not None:
        claims.append(Claim("금액", str(args.final_total_krw), "money"))
    preview = ()
    if len(matches) == 1:
        amount = "" if args.final_total_krw is None else f" · {won(args.final_total_krw)}"
        preview = (
            ("할 일", "견적 답변 적기"),
            ("기관", matches[0].target.label),
            ("결과", OUTCOME_LABELS[args.outcome] + amount),
        )
    located = found_one(matches, "그런 견적은 답 기다리는 목록에 없어요.")
    return Located(located.resolution, claims_for(matches, *claims), preview=preview)


def previous_outcome(row: OutreachQuoteRow, task: TaskRow | None) -> dict[str, JsonValue]:
    """Keep what undo needs to restore."""
    return {
        "status": row.status,
        "outcome": row.outcome,
        "final_total_krw": row.final_total_krw,
        "task_id": task.id if task is not None and task.status == "open" else None,
    }


async def record_outcome(db: AsyncSession, args: QuoteArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Record the institution's answer; nothing is sent."""
    row = await lock_row(db, OutreachQuoteRow, target.id, target.revision)
    task = await db.get(TaskRow, row.follow_up_task_id) if row.follow_up_task_id else None
    before = previous_outcome(row, task)
    saved = await save_outcome(
        db,
        target.id,
        OutcomeRequest(outcome=args.outcome, final_total_krw=args.final_total_krw),
        env.now,
    )
    return Outcome(
        f"기관 답변 기록: {target.label} · {OUTCOME_LABELS[args.outcome]}",
        TargetRef("quote", saved.id, target.label, saved.revision),
        UndoTicket("/agent/undo/record_quote_outcome", before),
    )


async def undo_outcome(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Put a quote's earlier state back and reopen the reminder it closed."""
    row = await lock_row(db, OutreachQuoteRow, undo.target.id, undo.target.revision)
    recorded_at = row.outcome_at
    row.status = str(undo.data["status"])
    row.outcome = None if undo.data["outcome"] is None else str(undo.data["outcome"])
    final = undo.data["final_total_krw"]
    row.final_total_krw = final if isinstance(final, int) else None
    row.outcome_at = None if row.outcome is None else row.outcome_at
    row.revision += 1
    task_id = undo.data["task_id"]
    task = await db.get(TaskRow, task_id) if isinstance(task_id, str) else None
    if task is not None and task.status == "done" and task.completed_at == recorded_at:
        task.status, task.completed_at = "open", None
        task.revision += 1
    await db.flush()
    return Outcome("적어 둔 견적 답변을 지웠어요.")


CASES: Final[tuple[Tool, ...]] = (
    build(
        Definition(
            "decide_cancellation",
            "T2",
            "propose",
            "예약 취소 처리",
            "사장님이 정한 취소 결정을 기록합니다. 환불을 실행하지 않습니다.",
            CancelArgs,
            locate_cancel,
            cancel,
            undo_cancel,
        ),
    ),
    build(
        Definition(
            "record_quote_outcome",
            "T2",
            "propose",
            "견적 답변 기록",
            "기관이 출강 견적에 어떻게 답했는지 기록합니다.",
            QuoteArgs,
            locate_quote,
            record_outcome,
            undo_outcome,
        ),
    ),
)
