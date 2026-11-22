"""Instagram API with Instagram Login: the owner's own media, comments, and account insights.

Official pages: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/get-started,
https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/comments, and
https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights.
The token comes only from the environment. There is no login automation and no stored session.
"""

import re
from datetime import datetime
from os import environ
from typing import Annotated, ClassVar, Final, override

from pydantic import BaseModel, Field, ValidationError

from collectors.base import (
    CollectedItem,
    Collector,
    JsonObject,
    NeedsConnectionError,
    SourceConfig,
    SourceId,
    Window,
)
from collectors.http import OK, HttpSession, Reply, parsed
from collectors.text import MAX_BODY, MAX_TITLE, bounded_id, plain_text, safe_url

API: Final = "https://graph.instagram.com/v27.0"
MISSING: Final = "인스타그램 계정을 연결해 주세요."
EXPIRED: Final = "인스타그램 연결이 만료됐어요. 다시 연결해 주세요."
USER_ID: Final = re.compile(r"[0-9]{1,30}")
TOKEN_CODES: Final = frozenset({102, 190})
DENIED: Final = frozenset({401, 403})
MEDIA_LIMIT: Final = 25
COMMENTED_LIMIT: Final = 10
METRICS: Final = {"views": "조회", "reach": "도달", "total_interactions": "반응"}


class InstagramConfig(SourceConfig):
    """The account name shown to the owner; it grants nothing."""

    username: Annotated[str, Field(pattern=r"^[A-Za-z0-9._]{1,30}$")] | None = None


class GraphError(BaseModel):
    """The code of a Graph API error; its message is not kept."""

    code: int = 0


class GraphFailure(BaseModel):
    """A Graph API error body."""

    error: GraphError


class Media(BaseModel):
    """One of the owner's posts."""

    id: str
    caption: str = ""
    media_type: str = ""
    permalink: str | None = None
    timestamp: datetime
    username: str | None = None
    comments_count: int = 0
    like_count: int = 0


class MediaPage(BaseModel):
    """Newest media first."""

    data: list[Media]


class Comment(BaseModel):
    """One top-level comment."""

    id: str
    text: str = ""
    timestamp: datetime
    username: str | None = None


class CommentPage(BaseModel):
    """Newest comments first, at most 50."""

    data: list[Comment]


class InsightTotal(BaseModel):
    """A metric total."""

    value: int


class Insight(BaseModel):
    """One account metric."""

    name: str
    total_value: InsightTotal | None = None


class InsightPage(BaseModel):
    """Account metrics of the last day."""

    data: list[Insight]


def media_item(media: Media) -> CollectedItem:
    """Turn a post into a collected item."""
    caption = plain_text(media.caption, MAX_BODY)
    raw: JsonObject = {
        "id": media.id, "media_type": media.media_type, "comments_count": media.comments_count,
        "like_count": media.like_count,
    }
    return CollectedItem(
        external_id=bounded_id(f"media:{media.id}"), kind="post",
        title=caption.partition("\n")[0][:MAX_TITLE], body=caption, author=media.username,
        url=safe_url(media.permalink), published_at=media.timestamp, raw=raw,
    )


def comment_item(comment: Comment, media: Media) -> CollectedItem:
    """Turn a comment into a collected item that remembers its post and the account that owns it."""
    raw: JsonObject = {"id": comment.id, "media_id": media.id, "owner": media.username}
    return CollectedItem(
        external_id=bounded_id(f"comment:{comment.id}"), kind="comment", title="인스타그램 댓글",
        body=plain_text(comment.text, MAX_BODY), author=comment.username, url=safe_url(media.permalink),
        published_at=comment.timestamp, raw=raw,
    )


def refuse_expired(reply: Reply) -> None:
    """Report a rejected token as a connection problem."""
    if reply.status == OK:
        return
    try:
        code = GraphFailure.model_validate_json(reply.content).error.code
    except ValidationError:
        code = 0
    if reply.status in DENIED or code in TOKEN_CODES:
        raise NeedsConnectionError(EXPIRED)


class InstagramCollector(Collector[InstagramConfig]):
    """Read what the owner's own account allows."""

    source_id: ClassVar[SourceId] = "instagram"
    display_name: ClassVar[str] = "인스타그램"
    min_interval: ClassVar[float] = 0.5

    @classmethod
    @override
    def config_model(cls) -> type[InstagramConfig]:
        return InstagramConfig

    @override
    def connection_problem(self) -> str | None:
        user_id = environ.get("INSTAGRAM_USER_ID", "")
        ready = environ.get("INSTAGRAM_ACCESS_TOKEN") and USER_ID.fullmatch(user_id)
        return None if ready else MISSING

    @override
    async def collect(self, window: Window) -> list[CollectedItem]:
        user_id = environ["INSTAGRAM_USER_ID"]
        async with self.gateway.connect(self.min_interval) as http:
            page = parsed(MediaPage, (await self.read(http, f"{user_id}/media", {
                "fields": "id,caption,media_type,permalink,timestamp,username,comments_count,like_count",
                "limit": str(MEDIA_LIMIT),
            })).expect_ok())
            items = [media_item(media) for media in page.data]
            commented = [media for media in page.data if media.comments_count and media.id.isalnum()]
            for media in commented[:COMMENTED_LIMIT]:
                items += await self.comments(http, media)
            return items + await self.insights(http, user_id, window)

    async def read(self, http: HttpSession, path: str, params: dict[str, str]) -> Reply:
        """Call one Graph API path with the token the documentation places in the query."""
        reply = await http.get(
            f"{API}/{path}", {**params, "access_token": environ["INSTAGRAM_ACCESS_TOKEN"]},
        )
        refuse_expired(reply)
        return reply

    async def comments(self, http: HttpSession, media: Media) -> list[CollectedItem]:
        """Read the newest comments of one post."""
        reply = await self.read(
            http, f"{media.id}/comments", {"fields": "id,text,timestamp,username", "limit": "50"},
        )
        return [comment_item(entry, media) for entry in parsed(CommentPage, reply.expect_ok()).data]

    async def insights(self, http: HttpSession, user_id: str, window: Window) -> list[CollectedItem]:
        """Read daily totals; an account without insights simply has none."""
        reply = await self.read(http, f"{user_id}/insights", {
            "metric": ",".join(METRICS), "period": "day", "metric_type": "total_value",
        })
        if reply.status != OK:
            return []
        values = {
            entry.name: entry.total_value.value
            for entry in parsed(InsightPage, reply.content).data if entry.total_value is not None
        }
        if not values:
            return []
        raw: JsonObject = dict(values.items())
        shown = [f"{label} {values[name]:,}" for name, label in METRICS.items() if name in values]
        return [CollectedItem(
            external_id=f"insight:{window.now.date().isoformat()}", kind="insight",
            title="인스타그램 하루 지표", body=" · ".join(shown), author=None,
            url=None, published_at=window.now, raw=raw,
        )]
