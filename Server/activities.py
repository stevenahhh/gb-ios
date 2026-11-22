"""What the assistant did this week, read from the records it produced.

There is no separate log table: every entry is derived from a draft it wrote or a problem it detected,
so the list can only state work that exists. Sending, paying, and calling never appear here.
"""

from datetime import datetime, timedelta
from typing import Final, Literal

from fastapi import APIRouter
from sqlalchemy import func, select

from common import Now, Session
from contracts import ApiModel
from display import local
from metrics import to_send
from models import ContentDraftRow, InquiryRow
from shipments import ShipmentPage, shipment_cards

router = APIRouter()
WINDOW: Final = timedelta(days=7)
LIMIT: Final = 50
PICKUP_PAGE: Final = ShipmentPage("soonest", LIMIT, 0)

ActivityKind = Literal["inquiryReply", "contentDraft", "missedPickup"]


class Activity(ApiModel):
    """One thing the assistant did, with the facts it used."""

    id: str
    at: str
    kind: ActivityKind
    target_id: str
    summary: str
    status: str | None
    evidence: list[str]


async def reply_activities(db: Session, since: datetime) -> list[Activity]:
    """List reply drafts, written when an inquiry arrives from the workshop facts on it."""
    rows = await db.scalars(
        select(InquiryRow).where(InquiryRow.received_at >= since, func.btrim(InquiryRow.draft) != ""),
    )
    return [
        Activity(
            id=f"inquiry:{row.id}", kind="inquiryReply",
            at=local(row.received_at).isoformat(timespec="seconds"),
            target_id=row.id, summary=f"{row.customer} 님 문의에 답변을 써 뒀어요",
            status="확인 대기" if row.status == "pending" else None,
            evidence=[f"손님 문의 · {row.question}", *row.facts],
        )
        for row in rows
    ]


async def content_activities(db: Session, since: datetime) -> list[Activity]:
    """Post drafts carry their own summary as the reason they were written."""
    rows = await db.scalars(select(ContentDraftRow).where(ContentDraftRow.created_at >= since))
    return [
        Activity(
            id=f"content:{row.id}", kind="contentDraft",
            at=local(row.created_at).isoformat(timespec="seconds"),
            target_id=row.id, summary=f"홍보 글 \u2018{row.title}\u2019을 써 뒀어요",
            status="확인 대기" if row.status == "draft" else None, evidence=[row.summary],
        )
        for row in rows
    ]


async def pickup_activities(db: Session, now: datetime) -> list[Activity]:
    """List parcels whose pickup time passed while they were still here."""
    cards = await shipment_cards(db, list(to_send(now.date())), PICKUP_PAGE, now.date())
    return [
        Activity(
            id=f"pickup:{card.id}", at=card.due.at, kind="missedPickup", target_id=card.id,
            summary=f"수거를 놓친 택배를 찾았어요 · {card.title}", status="확인 필요",
            evidence=[*card.lines, f"수거 시각 {card.deadline}"] if card.deadline else list(card.lines),
        )
        for card in cards
        if card.due is not None and datetime.fromisoformat(card.due.at) < now
    ]


@router.get("/assistant/activities")
async def activities(db: Session, now: Now) -> list[Activity]:
    """Return the last seven days, newest first."""
    since = now - WINDOW
    found = await reply_activities(db, since) + await content_activities(db, since)
    found += await pickup_activities(db, now)
    return sorted(found, key=lambda activity: activity.at, reverse=True)[:LIMIT]
