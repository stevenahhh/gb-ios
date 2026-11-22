"""Parcel carriers the app offers, their number formats, and the adapter seam for a real carrier API.

Names are the exact values the app stores and shows (GongbangAssistant/Shared/ActionSheets.swift).
No check-digit rule is documented in this repository, so every format check is length and digits
only and is labelled ``format_only``; a carrier's published specification would tighten it.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol

type FormatCheck = Literal["format_only"]
type Certainty = Literal["known", "guessed"]
type ProvenanceKind = Literal["carrier_api", "test_fake"]
SUFFIXES: Final = ("택배", "텍배", "택베", "택빼")
WORD_END: Final = (
    r"(?:택배)?(?:(?:으로|로)(?!\s*\d{1,3}(?!\d))|이에요|예요|입니다)?"
    r"(?=\d{4}|\W|$)(?!\s*\d{1,4}(?:동|호|차|단지|층))"
)
MIN_DIGITS: Final = 9
MAX_DIGITS: Final = 14


@dataclass(frozen=True, slots=True)
class Carrier:
    """One carrier: the stored name, how owners write it, and the number lengths it prints."""

    name: str
    aliases: tuple[str, ...]
    lengths: frozenset[int]
    check: FormatCheck = "format_only"


CARRIERS: Final = (
    Carrier("CJ대한통운", ("cj대한통운", "대한통운", "cj", "씨제이"), frozenset({10, 12})),
    Carrier("우체국택배", ("우체국택배", "우체국", "우편", "epost"), frozenset({13})),
    Carrier("한진택배", ("한진택배", "한진", "hanjin"), frozenset({10, 12})),
    Carrier("롯데택배", ("롯데택배", "롯데글로벌로지스", "롯데", "lotte"), frozenset({12})),
    Carrier("로젠택배", ("로젠택배", "로젠", "logen"), frozenset({11})),
)


@dataclass(frozen=True, slots=True)
class CarrierMention:
    """A carrier the owner named, where, and whether it was spelled exactly."""

    carrier: Carrier
    certainty: Certainty
    start: int


def carrier_named(name: str) -> Carrier | None:
    """Return the carrier whose stored name is exactly this one."""
    return next((carrier for carrier in CARRIERS if carrier.name == name), None)


def edit_distance(left: str, right: str) -> int:
    """Count single-letter edits between two short words."""
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def stem(word: str) -> tuple[str, bool]:
    """Drop a parcel suffix such as 택배 and say whether one was there."""
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix):
            return word.removesuffix(suffix), True
    return word, False


def fuzzy_carrier(word: str) -> Carrier | None:
    """Read a one-letter typo of a Korean carrier name, such as 대한퉁운 or 로잰택배."""
    base, suffixed = stem(word)
    if len(base) < (2 if suffixed else 3):
        return None
    close = {
        carrier for carrier in CARRIERS for alias in (stem(name)[0] for name in carrier.aliases)
        if not alias.isascii() and len(alias) == len(base) and edit_distance(alias, base) == 1
    }
    return close.pop() if len(close) == 1 else None


def find_carriers(text: str) -> list[CarrierMention]:
    """Find every carrier named in lower-cased text, exact spellings first, then one-letter typos."""
    found: list[CarrierMention] = []
    taken: list[range] = []
    for carrier in CARRIERS:
        for alias in carrier.aliases:
            for match in re.finditer(rf"(?<![^\W\d]){re.escape(alias)}{WORD_END}", text):
                start = match.start()
                span = range(start, start + len(alias))
                if not any(start in other for other in taken):
                    found.append(CarrierMention(carrier, "known", start))
                    taken.append(span)
    offset = 0
    for word in text.split():
        start = text.index(word, offset)
        offset = start + len(word)
        guess = fuzzy_carrier(word)
        if guess is not None and not any(start in other for other in taken):
            found.append(CarrierMention(guess, "guessed", start))
    return sorted(found, key=lambda mention: mention.start)


def carriers_for_length(length: int) -> tuple[Carrier, ...]:
    """List carriers that print numbers of this many digits."""
    return tuple(carrier for carrier in CARRIERS if length in carrier.lengths)


def has_valid_format(carrier: Carrier | None, digits: str) -> bool:
    """Check digits and length against the carrier, or the general range when it is unknown."""
    if not digits.isdigit():
        return False
    if carrier is None:
        return MIN_DIGITS <= len(digits) <= MAX_DIGITS
    return len(digits) in carrier.lengths


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a carrier fact came from; only ``carrier_api`` may count as evidence."""

    kind: ProvenanceKind
    adapter: str
    reference: str
    fetched_at: datetime

    @property
    def is_evidence(self) -> bool:
        """Tell whether the agent policy may act on this fact without the owner."""
        return self.kind == "carrier_api"


@dataclass(frozen=True, slots=True)
class ParcelOrder:
    """What a carrier needs to book a pickup; personal fields stay in memory only."""

    order_number: int
    recipient: str
    phone: str | None
    address: str | None
    product: str
    quantity: int


@dataclass(frozen=True, slots=True)
class Issued:
    """A number the carrier itself issued."""

    number: str
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class TrackEvent:
    """One scan the carrier reported."""

    at: datetime
    status: str
    place: str | None


@dataclass(frozen=True, slots=True)
class Tracked:
    """A carrier's own record of a number."""

    number: str
    delivered: bool
    events: tuple[TrackEvent, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class Unavailable:
    """The adapter could not answer; the reason is written for the owner in Korean."""

    reason: str


type IssueResult = Issued | Unavailable
type TrackResult = Tracked | Unavailable


class CarrierAdapter(Protocol):
    """A carrier API: book a pickup and read a number's scans."""

    @property
    def carrier(self) -> Carrier:
        """Return the carrier this adapter speaks for."""
        ...

    async def issue(self, order: ParcelOrder) -> IssueResult:
        """Ask the carrier to issue a tracking number for one parcel."""
        ...

    async def track(self, number: str) -> TrackResult:
        """Ask the carrier what happened to one number."""
        ...


@dataclass(frozen=True, slots=True)
class UnconfiguredCarrier:
    """The only production adapter today: it says so and never makes up a number."""

    carrier: Carrier

    def reason(self) -> str:
        """Explain in Korean why nothing can be fetched."""
        return f"{self.carrier.name} 연동이 아직 설정되지 않았어요. 송장번호를 직접 알려 주세요."

    async def issue(self, order: ParcelOrder) -> IssueResult:
        """Refuse to issue: no contract, no credentials."""
        del order
        return Unavailable(self.reason())

    async def track(self, number: str) -> TrackResult:
        """Refuse to track: no contract, no credentials."""
        del number
        return Unavailable(self.reason())


@dataclass(frozen=True, slots=True)
class FakeCarrier:
    """A scripted adapter for tests; its provenance is ``test_fake`` so it is never evidence."""

    carrier: Carrier
    numbers: Sequence[str]
    tracked: Sequence[Tracked]
    now: datetime

    def provenance(self, reference: str) -> Provenance:
        """Label a scripted answer."""
        return Provenance("test_fake", f"fake:{self.carrier.name}", reference, self.now)

    async def issue(self, order: ParcelOrder) -> IssueResult:
        """Hand out the next scripted number, or say none is left."""
        if not self.numbers:
            return Unavailable("테스트 송장번호가 남아 있지 않아요.")
        return Issued(self.numbers[0], self.provenance(f"order-{order.order_number}"))

    async def track(self, number: str) -> TrackResult:
        """Return the scripted record for a number, or say it is unknown."""
        record = next((item for item in self.tracked if item.number == number), None)
        return record or Unavailable("이 송장번호의 배송 기록을 찾지 못했어요.")


def adapter_for(carrier: Carrier) -> CarrierAdapter:
    """Return the configured adapter; no carrier contract exists yet, so every carrier is unconfigured."""
    return UnconfiguredCarrier(carrier)
