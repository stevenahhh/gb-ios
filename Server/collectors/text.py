"""Make external text and JSON safe to store: bounded, without markup, valid for PostgreSQL."""

import json
import re
from hashlib import sha256
from html.parser import HTMLParser
from typing import Final, override
from urllib.parse import urlsplit

from pydantic import JsonValue

MAX_TITLE: Final = 200
MAX_BODY: Final = 4000
MAX_URL: Final = 1000
MAX_ID: Final = 200
MAX_RAW: Final = 32 * 1024
HIDDEN: Final = frozenset({"script", "style"})
BREAKS: Final = frozenset({"br", "p", "div", "li"})
SPACES: Final = re.compile(r"[ \t\r\f\v]+")
BLANK_LINES: Final = re.compile(r"\s*\n\s*")


class TextExtractor(HTMLParser):
    """Keep visible text and drop tags, scripts, and styles."""

    def __init__(self) -> None:
        """Start empty; character references become characters."""
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: int = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in HIDDEN:
            self.hidden += 1
        elif tag in BREAKS:
            self.parts.append("\n")

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in HIDDEN and self.hidden:
            self.hidden -= 1
        elif tag in BREAKS:
            self.parts.append("\n")

    @override
    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def storable(value: str) -> str:
    """Remove NUL and lone surrogates, which PostgreSQL rejects."""
    return value.replace("\x00", "").encode("utf-8", "replace").decode()


def plain_text(value: str, limit: int) -> str:
    """Strip markup and escape any angle bracket that is left, so stored text is never live HTML."""
    extractor = TextExtractor()
    extractor.feed(storable(value))
    extractor.close()
    text = BLANK_LINES.sub("\n", SPACES.sub(" ", "".join(extractor.parts))).strip()
    return text[:limit].replace("<", "&lt;").replace(">", "&gt;")


def safe_url(value: str | None) -> str | None:
    """Keep only bounded web links."""
    if value is None or len(value) > MAX_URL:
        return None
    try:
        parts = urlsplit(storable(value.strip()))
    except ValueError:
        return None
    return parts.geturl() if parts.scheme in {"https", "http"} and parts.netloc else None


def bounded_id(value: str) -> str:
    """Shorten an oversized external identifier without losing uniqueness."""
    text = storable(value.strip())
    return text if len(text) <= MAX_ID else sha256(text.encode()).hexdigest()


def clean_json(value: JsonValue) -> JsonValue:
    """Make every string in a JSON value storable."""
    if isinstance(value, str):
        return storable(value)
    if isinstance(value, list):
        return [clean_json(entry) for entry in value]
    if isinstance(value, dict):
        return {storable(key): clean_json(entry) for key, entry in value.items()}
    return value


def clean_raw(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Keep the source JSON unless it is too large to be useful."""
    cleaned = {storable(key): clean_json(entry) for key, entry in value.items()}
    return cleaned if len(json.dumps(cleaned)) <= MAX_RAW else {"truncated": True}
