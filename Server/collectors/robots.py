"""Robots exclusion (RFC 9309): decide whether a feed may be read before it is requested."""

from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote, urlsplit

from collectors.http import OK, PRODUCT, HttpSession

ABSENT: Final = frozenset({404, 410})
MAX_ROBOTS: Final = 500 * 1024


@dataclass(frozen=True, slots=True)
class Rule:
    """One allow or disallow line."""

    allow: bool
    pattern: str


def matches(pattern: str, path: str) -> bool:
    """Match a robots pattern with * and a final $, without backtracking."""
    anchored = pattern.endswith("$")
    first, *rest = pattern.removesuffix("$").split("*")
    if not path.startswith(first):
        return False
    position = len(first)
    if not rest:
        return not anchored or position == len(path)
    *middle, last = rest
    for part in middle:
        found = path.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    if anchored:
        return len(path) - len(last) >= position and path.endswith(last)
    return path.find(last, position) >= 0


def rules_for(text: str, product: str) -> list[Rule]:
    """Collect the rules of this product's groups, or of the * groups when it has none."""
    named: list[Rule] = []
    general: list[Rule] = []
    agents: list[str] = []
    has_named = reading_rules = False
    for line in text.removeprefix("\ufeff").splitlines():
        key, separator, value = line.partition("#")[0].partition(":")
        if not separator:
            continue
        field, value = key.strip().lower(), value.strip()
        if field == "user-agent":
            if reading_rules:
                agents, reading_rules = [], False
            agents.append(value.partition("/")[0].strip().lower())
            has_named = has_named or agents[-1] == product.lower()
        elif field in {"allow", "disallow"}:
            reading_rules = True
            rule = Rule(field == "allow", unquote(value))
            if value and product.lower() in agents:
                named.append(rule)
            if value and "*" in agents:
                general.append(rule)
    return named if has_named else general


def allows(text: str, path: str) -> bool:
    """Apply the longest matching rule; a tie refuses."""
    found = [rule for rule in rules_for(text, PRODUCT) if matches(rule.pattern, unquote(path))]
    longest = max((len(rule.pattern) for rule in found), default=0)
    return all(rule.allow for rule in found if len(rule.pattern) == longest)


async def may_read(http: HttpSession, url: str) -> bool:
    """Read the host's robots.txt first; only a readable one that allows, or an absent one, permits."""
    parts = urlsplit(url)
    reply = await http.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
    if reply.status in ABSENT:
        return True
    if reply.status != OK or len(reply.content) > MAX_ROBOTS:
        return False
    path = f"{parts.path or '/'}?{parts.query}" if parts.query else parts.path or "/"
    return allows(reply.content.decode("utf-8", "replace"), path)
