"""Naver Blog feed adapter, off by default.

The owner must turn it on, and the generic feed collector still reads robots.txt before every run and never
requests the feed while robots.txt disallows it. There is no login, mirror, or browser fallback.
"""

from typing import Annotated, ClassVar, Final, override

from pydantic import Field

from collectors.base import SourceConfig, SourceId
from collectors.feed import FeedCollector

OFF: Final = "지금은 네이버 블로그 글을 자동으로 안 가져와요."
MISSING: Final = "아이디 칸이 비어 있어요. 블로그 아이디를 넣어 주세요."


class BlogConfig(SourceConfig):
    """The public blog and whether the owner turned collection on."""

    blog_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{2,40}$")] | None = None
    enabled: bool = False


class NaverBlogCollector(FeedCollector[BlogConfig]):
    """Read a public blog feed only when its host allows it."""

    source_id: ClassVar[SourceId] = "naver_blog"
    display_name: ClassVar[str] = "네이버 블로그"

    @classmethod
    @override
    def config_model(cls) -> type[BlogConfig]:
        return BlogConfig

    @override
    def connection_problem(self) -> str | None:
        if not self.config.enabled:
            return OFF
        return None if self.config.blog_id else MISSING

    @override
    def feed_url(self) -> str:
        return f"https://rss.blog.naver.com/{self.config.blog_id}.xml"
