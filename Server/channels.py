"""Channels and promotional drafts."""

from datetime import date
from typing import Annotated, Literal, assert_never

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bookings import ExpectedRevision
from collectors.mapping import recent_posts
from common import (
    LongText,
    Now,
    PageQuery,
    Session,
    invalid_transition,
    locked,
    matches,
    required_text,
)
from contracts import ApiModel, Card, CardAction, Metric, Page, Status
from display import count, day_start, next_day_start, won
from draft_contracts import draft_reference
from drafts import sync_linked
from inquiries import Inquiry
from metrics import Counts, channel_metric, counted, load_counts, metric
from models import (
    ChannelRow,
    ContentDraftRow,
    CustomerRow,
    InquiryRow,
    OrderRow,
)
from tasks import open_channel_tasks

router = APIRouter()
type ChannelFilter = Literal["all", "channels", "inquiries", "content"]


class ChannelPage(Page):
    """Channel area page; inquiries keep their established JSON shape."""

    inquiries: list[Inquiry]


class ContentDetail(ApiModel):
    """A draft opened for review."""

    id: str
    title: str
    channel: str
    body: str
    is_reviewed: bool
    revision: int


class ContentReview(ExpectedRevision):
    """The final text the owner approved."""

    body: Annotated[LongText, Field(min_length=1)]


def channel_metrics(counts: Counts) -> list[Metric]:
    """Summarize channel work from rows."""
    return [
        channel_metric(counts.channels),
        metric("pendingInquiries", "답변 기다리는 문의", counts.pending_inquiries),
        metric("drafts", "홍보 글 초안", counts.drafts),
    ]


async def channel_cards(db: AsyncSession, today: date, text: str = "") -> list[Card]:
    """Show each channel's real integration state and its own activity."""
    begin, end = day_start(today), next_day_start(today)
    today_orders = (
        OrderRow.channel_id == ChannelRow.id,
        OrderRow.status != "cancelled",
        OrderRow.ordered_at >= begin,
        OrderRow.ordered_at < end,
    )
    statement = select(
        ChannelRow,
        counted(OrderRow, *today_orders),
        select(func.coalesce(func.sum(OrderRow.amount_won), 0)).where(*today_orders).scalar_subquery(),
        counted(
            ContentDraftRow, ContentDraftRow.channel_id == ChannelRow.id, ContentDraftRow.status == "draft",
        ),
        counted(InquiryRow, InquiryRow.channel_id == ChannelRow.id, InquiryRow.status == "pending"),
    ).order_by(ChannelRow.sort_order, ChannelRow.id)
    if text:
        statement = statement.where(or_(matches(ChannelRow.name, text), matches(ChannelRow.handle, text)))
    cards: list[Card] = []
    posts = await recent_posts(db, today)
    for channel, orders, amount, drafts, inquiries in (await db.execute(statement)).tuples():
        connected = channel.connection == "connected"
        lines = [channel.handle or channel.name, f"오늘 들어온 주문 {count(orders)} · 받은 돈 {won(amount)}"]
        if drafts:
            lines.append(f"올릴 글 초안 {count(drafts)}")
        if channel.id in posts:
            lines.append(f"7일 동안 올린 글 {posts[channel.id]:,}개")
        cards.append(
            Card(
                id=channel.id,
                kind="channel",
                title=channel.name,
                lines=lines,
                tag="채널",
                status=Status(text="연결됨", tone="done")
                if connected
                else Status(text="아직 연결 안 됨", tone="neutral"),
                deadline=f"문의 {count(inquiries)}이 답을 기다려요" if inquiries else None,
                revision=channel.revision,
            ),
        )
    return cards


def content_card(draft: ContentDraftRow, channel: ChannelRow) -> Card:
    """Present a draft; reviewing does not publish it."""
    reviewed = draft.status == "reviewed"
    pending = draft.status == "draft"
    closing = f"{channel.name}에 올리는 건 사장님 몫이에요." if reviewed else draft.summary
    return Card(
        id=draft.id,
        kind="content",
        title=draft.title,
        tag="콘텐츠",
        revision=draft.revision,
        status=Status(text="다 읽어 봄", tone="done")
        if reviewed
        else Status(text="초안 있음", tone="progress") if pending
        else Status(text="쓰지 않기로 함", tone="neutral"),
        lines=[f"{channel.name} 올릴 글", closing],
        action=CardAction(code="reviewContent", label="홍보 글 읽어 보기") if pending else None,
        draft=draft_reference(draft),
    )


async def content_cards(db: AsyncSession, text: str, limit: int, offset: int) -> tuple[list[Card], int]:
    """Load a page of drafts, unreviewed first."""
    conditions = (
        [or_(matches(ContentDraftRow.title, text), matches(ContentDraftRow.summary, text))] if text else []
    )
    rows = await db.execute(
        select(ContentDraftRow, ChannelRow)
        .join(ChannelRow, ChannelRow.id == ContentDraftRow.channel_id)
        .where(*conditions)
        .order_by(ContentDraftRow.status, ContentDraftRow.created_at.desc(), ContentDraftRow.id)
        .limit(limit)
        .offset(offset),
    )
    total = await db.scalar(select(func.count()).select_from(ContentDraftRow).where(*conditions)) or 0
    return [content_card(draft, channel) for draft, channel in rows.tuples()], total


async def inquiry_page(db: AsyncSession, text: str, limit: int, offset: int) -> tuple[list[Inquiry], int]:
    """Search inquiries, pending first."""
    conditions: list[ColumnElement[bool]] = []
    if text:
        conditions.append(
            or_(
                matches(InquiryRow.subject, text),
                matches(InquiryRow.question, text),
                matches(InquiryRow.customer, text),
                matches(CustomerRow.phone, text),
            ),
        )
    joined = (
        select(InquiryRow).outerjoin(CustomerRow, CustomerRow.id == InquiryRow.customer_id).where(*conditions)
    )
    rows = await db.scalars(
        joined.order_by(InquiryRow.status != "pending", InquiryRow.received_at.desc(), InquiryRow.id)
        .limit(limit)
        .offset(offset),
    )
    total = await db.scalar(select(func.count()).select_from(joined.subquery())) or 0
    return [Inquiry.model_validate(row) for row in rows], total


@router.get("/channels")
async def channel_area(
    db: Session, now: Now, paging: PageQuery, section: ChannelFilter = "all",
) -> ChannelPage:
    """Return channels, inquiries, and content for one filter."""
    text, limit, offset, today = paging.text, paging.limit, paging.offset, now.date()
    fixed: list[Card] = []
    drafts: list[Card] = []
    inquiries: list[Inquiry] = []
    inquiry_total = draft_total = 0
    match section:
        case "all" | "channels" | "inquiries" | "content":
            if section in {"all", "channels"}:
                fixed = await channel_cards(db, today, text) + await open_channel_tasks(db, today, text)
            if section in {"all", "inquiries"}:
                inquiries, inquiry_total = await inquiry_page(db, text, limit, offset)
            if section in {"all", "content"}:
                drafts, draft_total = await content_cards(db, text, limit, offset)
        case _:
            assert_never(section)
    return ChannelPage(
        metrics=channel_metrics(await load_counts(db, today)),
        items=(fixed if offset == 0 else []) + drafts,
        inquiries=inquiries,
        total=len(fixed) + inquiry_total + draft_total,
        limit=limit,
        offset=offset,
        has_more=offset + limit < max(inquiry_total, draft_total),
    )


@router.get("/content-drafts/{draft_id}")
async def content_detail(draft_id: str, db: Session) -> ContentDetail:
    """Open a draft for review."""
    row = (
        (
            await db.execute(
                select(ContentDraftRow, ChannelRow)
                .join(ChannelRow, ChannelRow.id == ContentDraftRow.channel_id)
                .where(ContentDraftRow.id == draft_id),
            )
        )
        .tuples()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "resource not found")
    draft, channel = row
    return ContentDetail(
        id=draft.id,
        title=draft.title,
        channel=channel.name,
        body=draft.body,
        is_reviewed=draft.status == "reviewed",
        revision=draft.revision,
    )


@router.post("/content-drafts/{draft_id}/review")
async def review_content(draft_id: str, body: ContentReview, db: Session, now: Now) -> Card:
    """Save the approved text; publishing stays with the owner."""
    draft = await locked(db, ContentDraftRow, draft_id, body.expected_revision)
    if draft.status != "draft":
        raise invalid_transition()
    draft.body = required_text(body.body)
    draft.status = "reviewed"
    draft.reviewed_at = now
    draft.revision += 1
    await sync_linked(db, draft)
    await db.flush()
    return content_card(draft, await db.get_one(ChannelRow, draft.channel_id))
