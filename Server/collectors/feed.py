"""Generic RSS collector: robots.txt decides first, then one request reads the feed."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar, Final, override
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from collectors.base import CollectedItem, Collector, JsonObject, NeedsConnectionError, SourceConfig, Window
from collectors.http import SourceError
from collectors.robots import may_read
from collectors.text import MAX_BODY, MAX_TITLE, bounded_id, plain_text, safe_url

REFUSED: Final = "이 사이트가 자동 읽기를 막아 둬서 글을 못 가져왔어요."
MAX_ITEMS: Final = 100


def published(value: str) -> datetime | None:
    """Parse an RSS date; a date without an offset is UTC."""
    try:
        moment = parsedate_to_datetime(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def feed_item(element: Element) -> CollectedItem | None:
    """Read one RSS item; an item without an identifier cannot be stored once."""
    fields = {child.tag: (child.text or "").strip() for child in element if not child.tag.startswith("{")}
    identifier = fields.get("guid") or fields.get("link")
    if not identifier:
        return None
    raw: JsonObject = dict(fields.items())
    return CollectedItem(
        external_id=bounded_id(identifier), kind="post",
        title=plain_text(fields.get("title", ""), MAX_TITLE),
        body=plain_text(fields.get("description", ""), MAX_BODY),
        author=plain_text(fields.get("author", ""), MAX_TITLE) or None,
        url=safe_url(fields.get("link")), published_at=published(fields.get("pubDate", "")), raw=raw,
    )


def parse_feed(content: bytes) -> list[CollectedItem]:
    """Parse RSS 2.0 without DTDs, entities, or external references."""
    code = "malformed"
    try:
        root: Element = fromstring(content, forbid_dtd=True)
    except (ParseError, DefusedXmlException, ValueError, LookupError):
        raise SourceError(code) from None
    if root.tag != "rss":
        raise SourceError(code)
    found = (feed_item(element) for element in root.iterfind("./channel/item"))
    return [item for item in found if item is not None][:MAX_ITEMS]


class FeedCollector[C: SourceConfig](Collector[C], ABC):
    """Any feed host goes through the same robots gate; there is no way around it."""

    min_interval: ClassVar[float] = 2.0

    @abstractmethod
    def feed_url(self) -> str:
        """Return the feed address built from validated setup values."""

    @override
    async def collect(self, window: Window) -> list[CollectedItem]:
        url = self.feed_url()
        async with self.gateway.connect(self.min_interval) as http:
            if not await may_read(http, url):
                raise NeedsConnectionError(REFUSED)
            return parse_feed((await http.get(url)).expect_ok())
