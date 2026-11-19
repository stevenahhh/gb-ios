"""Assistant draft presentation shared by content and recommendation cards."""

from typing import Final, assert_never

from contracts import CardDraft, DraftStatus
from models import ContentDraftRow, RecommendationRow

STATUSES: Final[dict[str, DraftStatus]] = {
    "draft": "pending", "open": "pending",
    "reviewed": "approved", "acknowledged": "approved", "rejected": "rejected",
}


def draft_reference(row: ContentDraftRow | RecommendationRow) -> CardDraft:
    """Describe the persisted text and decision addressed by a card."""
    match row:
        case ContentDraftRow():
            kind = "content"
        case RecommendationRow():
            kind = "recommendation"
        case _:
            assert_never(row)
    return CardDraft(kind=kind, id=row.id, status=STATUSES[row.status], preview=row.body)
