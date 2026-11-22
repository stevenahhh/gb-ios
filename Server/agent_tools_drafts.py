"""Content and reply draft tools (T1); nothing is published or sent."""

from datetime import datetime
from typing import Annotated, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_toolkit import (
    Definition,
    Located,
    RevisionConflictError,
    TargetGoneError,
    ToolArgs,
    build,
    clipped,
    lock_row,
    name_confidence,
    named_in,
)
from agent_tools_desk import Reference, owner_claims
from agent_types import (
    BY_IDENTIFIER,
    Outcome,
    Resolution,
    TargetRef,
    Tool,
    ToolEnv,
    UndoInput,
    UndoTicket,
)
from b_k25_replies import GroundedDraft, write_draft
from b_k25_tables import GroundedEventRow, GroundingRow, JudgmentRow
from common import required_text
from database import transaction
from display import masked
from drafts import save_text
from inquiries import save_reply_text
from models import ChannelRow, ContentDraftRow, InquiryRow

ASKS_CONTENT: Final = "초안|글|홍보|게시물|고쳐|수정|바꿔|저장|써|다듬"
ASKS_REPLY: Final = "답장|답변|회신"


class ContentArgs(ToolArgs):
    """New text for a pending promotion draft."""

    draft: Reference = Field(description="고칠 홍보 초안 제목이나 채널 이름")
    text: Annotated[str, Field(min_length=1, max_length=4000, description="새 본문")]


async def locate_content(db: AsyncSession, args: ContentArgs, env: ToolEnv) -> Located:
    """Find the one draft that is still being written."""
    del env
    rows = (
        await db.execute(
            select(ContentDraftRow, ChannelRow.name)
            .join(ChannelRow, ChannelRow.id == ContentDraftRow.channel_id)
            .where(ContentDraftRow.status == "draft")
            .order_by(ContentDraftRow.id),
        )
    ).tuples().all()
    found = [
        (row, channel, score)
        for row, channel in rows
        if (score := name_confidence(args.draft, row.title, channel)) is not None
    ]
    preview = (("초안", found[0][0].title), ("새 글", clipped(args.text, 200))) if len(found) == 1 else ()
    return Located(
        Resolution(
            tuple(
                TargetRef("content", row.id, f"{channel} · {row.title}", row.revision)
                for row, channel, _ in found
            ),
            max((score for *_, score in found), default=BY_IDENTIFIER),
            "살펴보는 중인 초안이 없어요.",
        ),
        claims=owner_claims(ASKS_CONTENT, named_in("초안", args.draft), only=len(rows) == 1),
        preview=preview,
    )


async def save_content(db: AsyncSession, args: ContentArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Replace a pending draft's text; nothing is published."""
    del env
    row = await lock_row(db, ContentDraftRow, target.id, target.revision)
    previous = row.body
    save_text(row, args.text)
    await db.flush()
    return Outcome(
        f"저장해 둔 홍보 글: {row.title}",
        TargetRef("content", row.id, row.title, row.revision),
        UndoTicket(f"/assistant-drafts/content/{row.id}/draft", {"body": previous}),
    )


async def undo_content(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Put a draft's earlier text back."""
    row = await lock_row(db, ContentDraftRow, undo.target.id, undo.target.revision)
    save_text(row, required_text(str(undo.data["body"])))
    await db.flush()
    return Outcome(f"되돌린 홍보 글: {row.title}")


class ReplyArgs(ToolArgs):
    """One customer inquiry waiting for a reply."""

    inquiry: Reference = Field(description="손님 이름이나 문의 제목")


async def locate_inquiry(db: AsyncSession, args: ReplyArgs, env: ToolEnv) -> Located:
    """Find the pending inquiry to draft."""
    del env
    query = select(InquiryRow).where(InquiryRow.status == "pending").order_by(InquiryRow.received_at.desc())
    rows = list(await db.scalars(query))
    found = [
        (row, score)
        for row in rows
        if (score := name_confidence(args.inquiry, row.customer, row.subject)) is not None
    ]
    preview = (
        (("손님", masked(found[0][0].customer)), ("문의", found[0][0].subject)) if len(found) == 1 else ()
    )
    return Located(
        Resolution(
            tuple(
                TargetRef("inquiry", row.id, f"{masked(row.customer)} · {row.subject}", row.revision)
                for row, _ in found
            ),
            max((score for _, score in found), default=BY_IDENTIFIER),
            "답장 안 한 문의 목록엔 없어요.",
        ),
        claims=owner_claims(ASKS_REPLY, named_in("문의", args.inquiry), only=len(rows) == 1),
        preview=preview,
    )


async def save_reply(db: AsyncSession, args: ReplyArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Write a grounded draft and keep it on the inquiry; the owner still sends it and the lock stays on."""
    del args
    await require_unchanged(db, target)
    earlier = await earlier_reply(db, target.id)
    written = await write_draft(target.id, env.now)
    try:
        row = await lock_row_inquiry(db, target)
    except RevisionConflictError:
        await drop_written(target.id, written, earlier, env.now)
        raise
    if written.judgment is not None:
        return Outcome("비서가 답하기 애매한 문의예요. 사장님 판단이 필요해서 앱에 올려 뒀어요.", target)
    previous = row.draft
    save_reply_text(row, written.draft)
    await db.flush()
    lock_note = "" if written.lock != "locked" else " 장부와 숫자가 달라요. 한 번 봐 주세요."
    return Outcome(
        f"답장 초안 저장 끝.{lock_note} 손님께 가기 전에 한 번 읽어 주세요.",
        TargetRef("inquiry", row.id, target.label, row.revision),
        UndoTicket(
            f"/inquiries/{row.id}/draft",
            {"draft": previous, "earlier": earlier.model_dump(mode="json")},
        ),
    )


class EarlierCheck(BaseModel):
    """The check stored with an inquiry before a new draft replaced it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    ab_arm: str
    lock_state: str
    claims_json: list[dict[str, JsonValue]]
    generated_draft: str | None
    generated_at: datetime | None
    extraction_ok: bool
    override_reason: str | None


class EarlierReply(BaseModel):
    """What the reply engine held for an inquiry before a new draft: its check, judgment, and last event."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    check: EarlierCheck | None
    judgment: str | None
    last_event: int


async def require_unchanged(db: AsyncSession, target: TargetRef) -> None:
    """Stop before the model is asked when the inquiry moved; a lock here would block the engine's writes."""
    revision = await db.scalar(select(InquiryRow.revision).where(InquiryRow.id == target.id))
    if revision is None:
        raise TargetGoneError
    if target.revision is not None and revision != target.revision:
        raise RevisionConflictError


async def earlier_reply(db: AsyncSession, inquiry_id: str) -> EarlierReply:
    """Remember what the engine holds, so an undo or a late conflict can put it back."""
    stored = await db.get(GroundingRow, inquiry_id, populate_existing=True)
    judgment = await db.scalar(
        select(JudgmentRow.id).where(JudgmentRow.inquiry_id == inquiry_id, JudgmentRow.status == "open"),
    )
    last_event = await db.scalar(
        select(func.max(GroundedEventRow.id)).where(GroundedEventRow.inquiry_id == inquiry_id),
    )
    return EarlierReply(
        check=None if stored is None else EarlierCheck.model_validate(stored),
        judgment=judgment,
        last_event=last_event or 0,
    )


async def restore_check(db: AsyncSession, inquiry_id: str, written: str, earlier: EarlierReply) -> None:
    """Put the earlier check and judgment back, unless another draft was written since.

    Only rows that hang off the inquiry change, so this never waits for a lock on the inquiry itself.
    """
    stored = await db.get(GroundingRow, inquiry_id, with_for_update=True, populate_existing=True)
    if stored is None or stored.generated_draft != (written or None):
        return
    ours = await db.scalar(select(exists().where(
        GroundedEventRow.inquiry_id == inquiry_id, GroundedEventRow.id > earlier.last_event,
        GroundedEventRow.kind == "judgment_dismissed", GroundedEventRow.data.contains({"by": "redraft"}),
    )))
    if ours and not await open_judgment_of(db, inquiry_id):
        _ = await db.execute(
            update(JudgmentRow)
            .where(JudgmentRow.id == earlier.judgment, JudgmentRow.status == "dismissed")
            .values(status="open"),
        )
    if earlier.check is None:
        await db.delete(stored)
    else:
        _ = await db.execute(
            update(GroundingRow)
            .where(GroundingRow.inquiry_id == inquiry_id)
            .values(**earlier.check.model_dump()),
        )
    await db.flush()


async def open_judgment_of(db: AsyncSession, inquiry_id: str) -> bool:
    """Tell whether an inquiry has a question waiting; only one may be open."""
    return bool(await db.scalar(select(exists().where(
        JudgmentRow.inquiry_id == inquiry_id, JudgmentRow.status == "open",
    ))))


async def drop_written(
    inquiry_id: str, written: GroundedDraft, earlier: EarlierReply, now: datetime,
) -> None:
    """Drop what the engine stored for a draft nobody will use; an approval made meanwhile is kept.

    It commits by itself, because the conflict that follows rolls the caller's savepoint back.
    """
    async with transaction() as db:
        since = (GroundedEventRow.inquiry_id == inquiry_id, GroundedEventRow.id > earlier.last_event)
        kept = exists().where(*since, GroundedEventRow.kind.in_(("approved", "override")))
        if await db.scalar(select(kept)):
            return
        if written.judgment is not None and written.judgment.id != earlier.judgment:
            _ = await db.execute(
                delete(JudgmentRow)
                .where(JudgmentRow.id == written.judgment.id, JudgmentRow.status == "open"),
            )
        await restore_check(db, inquiry_id, written.draft, earlier)
        _ = await db.execute(
            delete(GroundedEventRow).where(
                *since,
                GroundedEventRow.created_at == now,
                GroundedEventRow.kind.in_(("draft", "judgment_opened", "judgment_dismissed")),
            ),
        )


async def lock_row_inquiry(db: AsyncSession, target: TargetRef) -> InquiryRow:
    """Lock an inquiry at the revision the call was planned with."""
    row = await db.scalar(
        select(InquiryRow)
        .where(InquiryRow.id == target.id)
        .with_for_update()
        .execution_options(populate_existing=True),
    )
    if row is None:
        raise TargetGoneError
    if target.revision is not None and row.revision != target.revision:
        raise RevisionConflictError
    return row


async def undo_reply(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Put an inquiry's earlier draft back."""
    row = await lock_row_inquiry(db, undo.target)
    written = row.draft
    save_reply_text(row, str(undo.data["draft"]))
    await restore_check(db, row.id, written, EarlierReply.model_validate(undo.data["earlier"]))
    await db.flush()
    return Outcome("예전 답장 초안으로 돌렸어요.")


DRAFTS: Final[tuple[Tool, ...]] = (
    build(
        Definition(
            "save_content_draft",
            "T1",
            "none",
            "홍보 초안 저장",
            "검토 중인 홍보 초안의 본문을 저장합니다. 게시하지 않습니다.",
            ContentArgs,
            locate_content,
            save_content,
            undo_content,
        ),
    ),
    build(
        Definition(
            "save_reply_draft",
            "T1",
            "none",
            "답장 초안 저장",
            "문의 답장 초안을 저장합니다. 보내지 않고 숫자 확인 규칙을 지킵니다.",
            ReplyArgs,
            locate_inquiry,
            save_reply,
            undo_reply,
            calls_model=True,
        ),
    ),
)
