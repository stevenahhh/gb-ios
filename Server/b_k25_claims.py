"""Pure comparison of the numbers in a reply draft with the workshop's own ledger.

Nothing here reads the database or calls the model. Values are parsed with regular
expressions, so one model answer never decides a lock by itself.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal, cast

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from display import local, month_day_weekday, won

type ClaimKind = Literal["price", "seats", "date", "deposit", "fact", "rule"]
type ClaimSource = Literal["ledger", "price_list", "fact_card", "owner_rule", "customer", "none"]
type ClaimStatus = Literal["matched", "mismatched", "unsupported", "unchecked"]
type Lock = Literal["clear", "locked", "unchecked"]

KINDS: Final[frozenset[str]] = frozenset({"price", "seats", "date", "deposit", "fact", "rule"})
UNASKED_PRICE: Final = "손님이 묻지 않은 가격이에요"
NOT_IN_LEDGER: Final = "장부에서 찾지 못했어요"
LABEL_LEDGER: Final = "예약 장부"
LABEL_PRICES: Final = "가격표"
LABEL_WORKSHOP: Final = "공방 안내"
LABEL_RULE: Final = "내 규칙"
LABEL_CUSTOMER: Final = "손님이 쓴 값"
LABEL_NONE: Final = "근거 없음"

NATIVE_COUNTS: Final[dict[str, int]] = {
    "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
}
COUNT: Final = rf"(?<![\d.,])(?:\d{{1,3}}|{'|'.join(NATIVE_COUNTS)})"
AMOUNT: Final = re.compile(
    (
        r"(?<![\d.,])(?:"
        r"(?P<man>\d+(?:\.\d+)?)\s*만(?:\s*(?P<cheon>\d)\s*천)?(?:\s*(?P<rest>\d{1,4}))?\s*원"
        r"|(?P<only>\d+)\s*천\s*원"
        r"|(?P<plain>\d{1,3}(?:,\d{3})+|\d+)\s*원)"
    ),
)
DEPOSIT_BEFORE: Final = re.compile(r"(?:예약금|보증금|계약금)[^.\n]{0,12}$")
DEPOSIT_AFTER: Final = re.compile(r"^\s*(?:을|를|이|가|은|는|으로|로)?\s*(?:예약금|보증금|계약금)")
DATE: Final = re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일")
WEEKDAY: Final = re.compile(r"(?:(?P<when>다음\s*주|이번\s*주)\s*)?(?P<day>[월화수목금토일])요일")
SEAT_UNIT: Final = re.compile(rf"(?P<n>{COUNT})\s*(?:자리|석)(?!\s*당)")
REMAINING: Final = re.compile(
    rf"(?:남은|잔여|빈)\s*(?:자리|좌석)?\s*(?:이|가|은|는|:)?\s*(?P<n>{COUNT})\s*(?:자리|석|명|개)",
)
EXACT_TAIL: Final = re.compile(r"^\s*(?:이|가|은|는|만)?\s*(?:정도)?\s*(?:남|밖에|뿐)")
DURATION: Final = re.compile(
    (
        r"(?P<h>\d+(?:\.\d+)?)\s*시간(?:\s*(?P<half>반)|\s*(?P<m>\d{1,2})\s*분)?"
        r"(?!\s*(?:전|후|뒤|이내|안에))"
        r"|(?<!\d)(?P<only>\d{2,3})\s*분(?!\s*(?:전|후|뒤|이내|안에|씩))"
    ),
)
DURATION_CONTEXT: Final = re.compile(r"수업|클래스|체험|과정|코스|진행|소요|걸리|걸려")
MIN_CLASS_MINUTES: Final = 30
CAPACITY: Final = re.compile(
    (
        r"(?:정원|최대\s*인원)\s*(?:은|는|이|가|:)?\s*(?:최대\s*)?(?P<n>\d{1,3})\s*명"
        r"|한\s*(?:회차|회|타임|수업)(?:에|당)?\s*(?:최대\s*)?(?P<n2>\d{1,3})\s*명"
    ),
)
PRICE_ASKED: Final = re.compile(r"가격|얼마|비용|요금|금액|견적|수업료|할인|단가|총액|예산|만\s*원|\d\s*원")
WEEKDAYS: Final = "월화수목금토일"
RELATIVE_DAYS: Final = (("오늘", 0), ("내일", 1), ("모레", 2))
SENTENCE_END: Final = re.compile(r"[.!?\n]")
DEFERRAL: Final = re.compile(r"확인(?:해서|하고|해\s*보고|\s*후)?\s*(?:다시\s*)?(?:알려|연락|안내|답)")
GENERIC: Final[frozenset[str]] = frozenset({
    "클래스", "수업", "체험", "원데이", "공방", "만들기", "나만의", "특강",
})
SUPPORT_RATIO: Final = 0.6
MIN_FACT_CHARS: Final = 4
JSON_ARRAY: Final = re.compile(r"\[.*\]", re.DOTALL)


@dataclass(frozen=True, slots=True)
class SessionFact:
    """One upcoming class from the ledger, with the seats it has left right now."""

    title: str
    starts_at: datetime
    capacity: int
    seats_left: int
    deposit_won: int
    duration_minutes: int

    @property
    def day(self) -> date:
        """Return the local calendar day of the class."""
        return local(self.starts_at).date()

    @property
    def label(self) -> str:
        """Name the class by its day, the way the owner says it."""
        moment = local(self.starts_at)
        return f"{month_day_weekday(self.day)}요일 {moment:%H:%M}"


@dataclass(frozen=True, slots=True)
class CardFact:
    """The facts the owner confirmed for one class; None is not evidence."""

    class_name: str
    duration_minutes: int | None = None
    capacity: int | None = None
    included_materials: str | None = None
    parking: str | None = None
    refund_policy: str | None = None
    price_won: int | None = None
    deposit_won: int | None = None

    @property
    def texts(self) -> tuple[str, ...]:
        """Return the free-text facts a draft may quote."""
        return tuple(value for value in (self.included_materials, self.parking, self.refund_policy) if value)


@dataclass(frozen=True, slots=True)
class RuleFact:
    """One reusable sentence the owner saved; no class means the whole workshop."""

    text: str
    class_name: str | None = None


@dataclass(frozen=True, slots=True)
class Ledger:
    """Everything a grounded reply to one inquiry may rely on."""

    today: date
    sessions: tuple[SessionFact, ...] = ()
    cards: tuple[CardFact, ...] = ()
    rules: tuple[RuleFact, ...] = ()
    facts: tuple[str, ...] = ()
    policies: tuple[str, ...] = ()
    question: str = ""
    asked: str = ""

    @property
    def class_names(self) -> tuple[str, ...]:
        """Return every class name in the ledger, once each."""
        names = [session.title for session in self.sessions] + [card.class_name for card in self.cards]
        return tuple(dict.fromkeys(names))

    def classes_named_in(self, draft: str) -> tuple[str, ...]:
        """Return the classes the question and draft talk about, or all when they name none."""
        text = f"{self.question}\n{draft}"
        named = tuple(name for name in self.class_names if mentions(text, name))
        return named or self.class_names

    def sessions_of(self, draft: str) -> tuple[SessionFact, ...]:
        """Return the sessions of the classes in question, whatever their day."""
        names = set(self.classes_named_in(draft))
        return tuple(session for session in self.sessions if session.title in names)

    def dated_sessions(self, draft: str) -> tuple[SessionFact, ...]:
        """Return sessions of the classes in question, on the days the draft names.

        A draft that says 내일 or 주말 in passing must not narrow the ledger, so those words count
        only in the customer's question, which decides the days when the draft names none.
        """
        days = days_named(draft, self.today, relative=False) or days_named(self.question, self.today)
        candidates = self.sessions_of(draft)
        return tuple(session for session in candidates if session.day in days) if days else candidates

    def cards_of(self, draft: str) -> tuple[CardFact, ...]:
        """Return the fact cards of the classes in question."""
        names = set(self.classes_named_in(draft))
        return tuple(card for card in self.cards if card.class_name in names)

    def rules_for(self, draft: str) -> tuple[RuleFact, ...]:
        """Return saved rules for the whole workshop or for the classes in question."""
        names = set(self.classes_named_in(draft))
        return tuple(rule for rule in self.rules if rule.class_name is None or rule.class_name in names)


@dataclass(frozen=True, slots=True)
class Claim:
    """One number or statement in a draft, and what the ledger says about it."""

    kind: ClaimKind
    text: str
    value: str
    source: ClaimSource
    source_label: str
    status: ClaimStatus
    ledger_value: str | None = None
    note: str | None = None
    replacement: str | None = None

    @property
    def match(self) -> bool:
        """True only when the ledger supports the statement."""
        return self.status == "matched"


@dataclass(frozen=True, slots=True)
class ModelClaim:
    """One statement the model found in a draft, kept only when the draft contains its exact text."""

    kind: ClaimKind
    text: str
    value: str


@dataclass(frozen=True, slots=True)
class Evaluation:
    """The claims of one draft and whether its approval must wait."""

    claims: tuple[Claim, ...]
    lock: Lock
    extraction_ok: bool


@dataclass(frozen=True, slots=True)
class Span:
    """A piece of draft text that states a number."""

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class AmountSpan(Span):
    """A won amount, and whether the text calls it a deposit."""

    won: int = 0
    is_deposit: bool = False


@dataclass(frozen=True, slots=True)
class NumberSpan(Span):
    """A whole number, such as seats, minutes, or people."""

    value: int = 0
    exact: bool = False


@dataclass(frozen=True, slots=True)
class DateSpan(Span):
    """A month and day written in the draft."""

    month: int = 0
    day: int = 0


def mentions(text: str, class_name: str) -> bool:
    """Tell whether a text talks about a class by its name or by a distinctive word of it."""
    words = [word for word in class_name.split() if word not in GENERIC and len(word) > 1]
    return class_name in text or any(word in text for word in (words or [class_name]))


def count_of(text: str) -> int:
    """Read 3 or 세 as a number."""
    return NATIVE_COUNTS.get(text) or int(text)


def written_days(text: str, today: date) -> set[date]:
    """Collect month-day dates, taking the nearest one that has not long passed."""
    days: set[date] = set()
    for match in DATE.finditer(text):
        month, day = int(match["m"]), int(match["d"])
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            if candidate >= today - timedelta(days=3):
                days.add(candidate)
                break
    return days


def weekday_days(text: str, today: date) -> set[date]:
    """Collect weekday names as their next day, or as next week's when the text says 다음 주."""
    days: set[date] = set()
    for match in WEEKDAY.finditer(text):
        index = WEEKDAYS.index(match["day"])
        if (match["when"] or "").startswith("다음"):
            days.add(today + timedelta(days=7 - today.weekday() + index))
        else:
            days.add(today + timedelta(days=(index - today.weekday()) % 7))
    return days


def relative_days(text: str, today: date) -> set[date]:
    """Collect 오늘, 내일, 모레, and 주말 as days."""
    days = {today + timedelta(days=offset) for word, offset in RELATIVE_DAYS if word in text}
    if "주말" in text:
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        days |= {saturday, saturday + timedelta(days=1)}
    return days


def days_named(text: str, today: date, *, relative: bool = True) -> frozenset[date]:
    """Collect the days a text names; a draft's 오늘/내일/주말 can be skipped."""
    days = written_days(text, today) | weekday_days(text, today)
    return frozenset(days | (relative_days(text, today) if relative else set()))


def amount_spans(text: str) -> list[AmountSpan]:
    """Find won amounts, including Korean units such as 3만 8천 원."""
    spans: list[AmountSpan] = []
    for match in AMOUNT.finditer(text):
        if match["man"] is not None:
            value = round(float(match["man"]) * 10_000)
            value += int(match["cheon"] or 0) * 1_000 + int(match["rest"] or 0)
        elif match["only"] is not None:
            value = int(match["only"]) * 1_000
        else:
            value = int(match["plain"].replace(",", ""))
        before = text[max(0, match.start() - 16):match.start()]
        after = text[match.end():match.end() + 12]
        is_deposit = bool(DEPOSIT_BEFORE.search(before)) or bool(DEPOSIT_AFTER.search(after))
        spans.append(AmountSpan(match.start(), match.end(), match.group(), value, is_deposit))
    return spans


def date_spans(text: str) -> list[DateSpan]:
    """Find written month-day dates."""
    return [
        DateSpan(m.start(), m.end(), m.group(), int(m["m"]), int(m["d"])) for m in DATE.finditer(text)
    ]


def seat_spans(text: str) -> list[NumberSpan]:
    """Find seat counts and whether the draft states the number left rather than a possible number."""
    spans: list[NumberSpan] = [
        NumberSpan(m.start(), m.end(), m.group(), count_of(m["n"]), exact=True)
        for m in REMAINING.finditer(text)
    ]
    for match in SEAT_UNIT.finditer(text):
        if any(span.start < match.end() and match.start() < span.end for span in spans):
            continue
        exact = bool(EXACT_TAIL.search(text[match.end():match.end() + 8]))
        spans.append(NumberSpan(match.start(), match.end(), match.group(), count_of(match["n"]), exact))
    return sorted(spans, key=lambda span: span.start)


def in_class_sentence(text: str, position: int) -> bool:
    """Tell whether the sentence around a position talks about the class itself."""
    start = max((m.end() for m in SENTENCE_END.finditer(text, 0, position)), default=0)
    end_match = SENTENCE_END.search(text, position)
    end = end_match.start() if end_match else len(text)
    return bool(DURATION_CONTEXT.search(text[start:end]))


def duration_spans(text: str) -> list[NumberSpan]:
    """Find class lengths in minutes; a bare count of minutes needs a class around it."""
    spans: list[NumberSpan] = []
    for match in DURATION.finditer(text):
        if match["h"] is not None:
            minutes = round(float(match["h"]) * 60)
            minutes += 30 if match["half"] else int(match["m"] or 0)
        else:
            minutes = int(match["only"])
            if minutes < MIN_CLASS_MINUTES:
                continue
        if in_class_sentence(text, match.start()):
            spans.append(NumberSpan(match.start(), match.end(), match.group(), minutes))
    return spans


def capacity_spans(text: str) -> list[NumberSpan]:
    """Find stated class capacities."""
    return [
        NumberSpan(m.start(), m.end(), m.group(), int(m["n"] or m["n2"])) for m in CAPACITY.finditer(text)
    ]


def amounts_in(texts: Sequence[str]) -> frozenset[int]:
    """Collect the amounts written in any of several texts."""
    return frozenset(span.won for text in texts for span in amount_spans(text))


def number_tokens(text: str) -> frozenset[str]:
    """Normalize the numbers in a sentence so a rewrite can be compared with its source."""
    amounts = amount_spans(text)
    plain = re.sub(AMOUNT, " ", text)
    digits = re.findall(r"\d+(?:\.\d+)?", plain)
    return frozenset([f"{span.won}원" for span in amounts] + digits)


def signature(text: str) -> frozenset[tuple[str, int, int]]:
    """Every number a draft states that the ledger check compares, as comparable values."""
    values: set[tuple[str, int, int]] = {("won", span.won, 0) for span in amount_spans(text)}
    values |= {("date", span.month, span.day) for span in date_spans(text)}
    values |= {("seats", span.value, 0) for span in seat_spans(text)}
    return frozenset(values)


def agrees(draft: str, model_claims: Sequence[ModelClaim]) -> bool:
    """Check that the model's extraction and the regular expressions read the same numbers."""
    stated = frozenset(item for claim in model_claims for item in signature(claim.text))
    return stated == signature(draft)


class ExtractedItem(BaseModel):
    """One element of the extraction output; anything else in it is ignored."""

    kind: str = "fact"
    text: str = ""
    value: JsonValue = None


EXTRACTED: Final = TypeAdapter(list[ExtractedItem])


def parse_model_claims(raw: str, draft: str) -> tuple[ModelClaim, ...] | None:
    """Read the extraction output; statements whose text the draft does not contain are dropped."""
    found = JSON_ARRAY.search(raw)
    if found is None:
        return None
    try:
        items = EXTRACTED.validate_json(found.group())
    except ValidationError:
        return None
    claims: list[ModelClaim] = []
    for item in items:
        if not item.text.strip() or item.text not in draft:
            continue
        kind = cast("ClaimKind", item.kind) if item.kind in KINDS else "fact"
        claims.append(ModelClaim(kind, item.text, item.value if isinstance(item.value, str) else ""))
    return tuple(claims)


def price_label(amounts: Sequence[int]) -> str:
    """Join known prices for a mismatch hint."""
    return " 또는 ".join(won(amount) for amount in sorted(set(amounts)))


def only_won(amounts: Sequence[int]) -> str | None:
    """Offer the one known price as a fix; several prices leave the choice to the owner."""
    distinct = set(amounts)
    return won(distinct.pop()) if len(distinct) == 1 else None


def with_number(text: str, value: int) -> str:
    """Put the ledger's number into the words the draft used."""
    return re.sub(r"\d+(?:\.\d+)?", str(value), text, count=1)


def check_price(span: AmountSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a price with the class's price list, then with what the owner wrote elsewhere."""
    known = [card.price_won for card in ledger.cards_of(draft) if card.price_won is not None]
    deposits = {session.deposit_won for session in ledger.sessions_of(draft)}
    value = str(span.won)
    unasked = PRICE_ASKED.search(ledger.asked) is None
    supports: list[tuple[ClaimSource, str, frozenset[int]]] = [
        ("price_list", LABEL_PRICES, frozenset(known)),
        ("owner_rule", LABEL_RULE, amounts_in([rule.text for rule in ledger.rules_for(draft)])),
        ("ledger", LABEL_LEDGER, frozenset(deposits)),
        ("fact_card", LABEL_WORKSHOP, amounts_in([*ledger.facts, *ledger.policies])),
    ]
    if not known:
        supports.append(("customer", LABEL_CUSTOMER, amounts_in([ledger.question])))
    for source, label, amounts in supports:
        if span.won in amounts:
            if unasked and source in {"price_list", "owner_rule", "fact_card"}:
                return Claim("price", span.text, value, source, label, "mismatched", note=UNASKED_PRICE)
            return Claim("price", span.text, value, source, label, "matched")
    if known:
        return Claim("price", span.text, value, "price_list", LABEL_PRICES, "mismatched",
                     ledger_value=price_label(known), replacement=only_won(known))
    return Claim("price", span.text, value, "none", LABEL_NONE, "mismatched", note=NOT_IN_LEDGER)


def check_deposit(span: AmountSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a deposit with the ledger's deposit for that class."""
    value = str(span.won)
    deposits = [session.deposit_won for session in ledger.sessions_of(draft)]
    if not deposits:
        deposits = [card.deposit_won for card in ledger.cards_of(draft) if card.deposit_won is not None]
    if span.won in deposits:
        return Claim("deposit", span.text, value, "ledger", LABEL_LEDGER, "matched")
    owner_texts = [*ledger.facts, *ledger.policies, *(rule.text for rule in ledger.rules_for(draft))]
    if span.won in amounts_in(owner_texts):
        return Claim("deposit", span.text, value, "fact_card", LABEL_WORKSHOP, "matched")
    if deposits:
        return Claim("deposit", span.text, value, "ledger", LABEL_LEDGER, "mismatched",
                     ledger_value=price_label(deposits), replacement=only_won(deposits))
    return Claim("deposit", span.text, value, "none", LABEL_NONE, "mismatched", note=NOT_IN_LEDGER)


def check_seats(span: NumberSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a seat count with what the named sessions still have."""
    value = str(span.value)
    candidates = ledger.dated_sessions(draft)
    if not candidates:
        return Claim("seats", span.text, value, "ledger", LABEL_LEDGER, "mismatched", note=NOT_IN_LEDGER)

    def fits(session: SessionFact) -> bool:
        return session.seats_left == span.value if span.exact else session.seats_left >= span.value

    if any(fits(session) for session in candidates):
        return Claim("seats", span.text, value, "ledger", LABEL_LEDGER, "matched")
    closest = min(candidates, key=lambda session: abs(session.seats_left - span.value))
    return Claim("seats", span.text, value, "ledger", LABEL_LEDGER, "mismatched",
                 ledger_value=f"{closest.label} {closest.seats_left}자리",
                 replacement=f"{closest.seats_left}자리" if len(candidates) == 1 else None)


def check_date(span: DateSpan, ledger: Ledger) -> Claim:
    """Compare a date with the ledger's class days, the owner's notes, and the customer's own words."""
    value = f"{span.month:02d}-{span.day:02d}"
    if any((session.day.month, session.day.day) == (span.month, span.day) for session in ledger.sessions):
        return Claim("date", span.text, value, "ledger", LABEL_LEDGER, "matched")
    owner_texts = [*ledger.facts, *ledger.policies]
    if any(value in {f"{d.month:02d}-{d.day:02d}" for d in date_spans(text)} for text in owner_texts):
        return Claim("date", span.text, value, "fact_card", LABEL_WORKSHOP, "matched")
    if any(span.text in rule.text for rule in ledger.rules):
        return Claim("date", span.text, value, "owner_rule", LABEL_RULE, "matched")
    if value in {f"{d.month:02d}-{d.day:02d}" for d in date_spans(ledger.question)}:
        return Claim("date", span.text, value, "customer", LABEL_CUSTOMER, "matched")
    days = sorted({session.day for session in ledger.sessions})
    upcoming = days[0] if days else None
    return Claim("date", span.text, value, "ledger", LABEL_LEDGER, "mismatched",
                 ledger_value=month_day_weekday(upcoming) + "요일" if upcoming else None,
                 note=None if upcoming else NOT_IN_LEDGER,
                 replacement=f"{upcoming.month}월 {upcoming.day}일" if upcoming and len(days) == 1 else None)


def check_number(
    span: NumberSpan, known: frozenset[int], unit: str, *, in_ledger: bool,
) -> Claim:
    """Compare a class fact such as a length or a capacity with the known values of that class."""
    source: ClaimSource = "ledger" if in_ledger else "fact_card"
    label = LABEL_LEDGER if in_ledger else LABEL_WORKSHOP
    value = str(span.value)
    if not known:
        return Claim("fact", span.text, value, "none", LABEL_NONE, "unsupported")
    if span.value in known:
        return Claim("fact", span.text, value, source, label, "matched")
    return Claim("fact", span.text, value, source, label, "mismatched",
                 ledger_value=" 또는 ".join(f"{item}{unit}" for item in sorted(known)),
                 replacement=with_number(span.text, min(known)) if len(known) == 1 else None)


def check_numbers(draft: str, ledger: Ledger) -> list[Claim]:
    """Check every number the regular expressions find, in the order the draft states them."""
    sessions = ledger.sessions_of(draft)
    cards = ledger.cards_of(draft)
    durations = frozenset(s.duration_minutes for s in sessions) | frozenset(
        c.duration_minutes for c in cards if c.duration_minutes is not None
    )
    capacities = frozenset(s.capacity for s in sessions) | frozenset(
        c.capacity for c in cards if c.capacity is not None
    )
    in_ledger = bool(sessions)
    found: list[tuple[int, Claim]] = []
    for span in amount_spans(draft):
        claim = check_deposit(span, draft, ledger) if span.is_deposit else check_price(span, draft, ledger)
        found.append((span.start, claim))
    found += [(span.start, check_date(span, ledger)) for span in date_spans(draft)]
    found += [(span.start, check_seats(span, draft, ledger)) for span in seat_spans(draft)]
    found += [
        (span.start, check_number(span, durations, "분", in_ledger=in_ledger))
        for span in duration_spans(draft)
    ]
    found += [
        (span.start, check_number(span, capacities, "명", in_ledger=in_ledger))
        for span in capacity_spans(draft)
    ]
    return [claim for _, claim in sorted(found, key=lambda item: item[0])]


def bigrams(text: str) -> frozenset[str]:
    """Character pairs without spaces or punctuation, which survive Korean endings."""
    letters = re.sub(r"[\s\W_]+", "", text)
    return frozenset(letters[i:i + 2] for i in range(len(letters) - 1))


def support_of(text: str, ledger: Ledger) -> tuple[ClaimSource, str] | None:
    """Find the owner's text that a statement rests on, if it rests on one."""
    wanted = bigrams(text)
    if len(wanted) < MIN_FACT_CHARS - 1:
        return None
    sources: list[tuple[ClaimSource, str, str]] = []
    sources.extend(("owner_rule", LABEL_RULE, rule.text) for rule in ledger.rules_for(text))
    sources.extend(
        ("fact_card", f"사실 카드: {card.class_name}", value)
        for card in ledger.cards_of(text) for value in card.texts
    )
    sources.extend(("fact_card", LABEL_WORKSHOP, fact) for fact in (*ledger.facts, *ledger.policies))
    sources.append(("customer", LABEL_CUSTOMER, ledger.question))
    best: tuple[float, ClaimSource, str] = (0.0, "none", LABEL_NONE)
    for source, label, body in sources:
        share = len(wanted & bigrams(body)) / len(wanted)
        if share > best[0]:
            best = (share, source, label)
    return (best[1], best[2]) if best[0] >= SUPPORT_RATIO else None


def check_statements(draft: str, ledger: Ledger, model_claims: Sequence[ModelClaim]) -> list[Claim]:
    """Report the model's facts and rules that no number check already covers."""
    spans: list[Span] = [*amount_spans(draft), *date_spans(draft), *seat_spans(draft)]
    spans += [*duration_spans(draft), *capacity_spans(draft)]
    checked = [(span.start, span.end) for span in spans]
    claims: list[Claim] = []
    for claim in model_claims:
        start = draft.find(claim.text)
        if any(start < end and begin < start + len(claim.text) for begin, end in checked):
            continue
        support = support_of(claim.text, ledger)
        source, label = support or ("none", LABEL_NONE)
        kind: ClaimKind = "rule" if claim.kind == "rule" else "fact"
        claims.append(Claim(
            kind, claim.text, claim.value, source, label,
            "matched" if support else "unsupported",
        ))
    return claims


def evaluate(
    draft: str, ledger: Ledger, model_claims: Sequence[ModelClaim] | None,
) -> Evaluation:
    """Check one freshly written draft; without an agreeing extraction the lock stays open."""
    numbers = check_numbers(draft, ledger)
    if model_claims is None:
        return Evaluation(tuple(numbers), "unchecked", extraction_ok=False)
    statements = check_statements(draft, ledger, model_claims)
    if not agrees(draft, model_claims):
        return Evaluation((*numbers, *statements), "unchecked", extraction_ok=False)
    lock: Lock = "locked" if any(claim.status == "mismatched" for claim in numbers) else "clear"
    return Evaluation((*numbers, *statements), lock, extraction_ok=True)


def recheck(
    draft: str, ledger: Ledger, kept: Sequence[Claim], *, extraction_ok: bool,
) -> Evaluation:
    """Check a draft the owner changed, without asking the model again.

    Numbers are read again from the text; the model's earlier statements stay when their
    text is still in the draft. A draft whose extraction never agreed stays unchecked.
    """
    numbers = check_numbers(draft, ledger)
    statements = [claim for claim in kept if claim.kind in {"fact", "rule"} and claim.text in draft]
    if not extraction_ok:
        return Evaluation((*numbers, *statements), "unchecked", extraction_ok=False)
    lock: Lock = "locked" if any(claim.status == "mismatched" for claim in numbers) else "clear"
    return Evaluation((*numbers, *statements), lock, extraction_ok=True)


def deferral_only(draft: str, claims: Sequence[Claim]) -> bool:
    """Tell whether a draft only promises to check and states nothing it can be held to."""
    return bool(DEFERRAL.search(draft)) and not claims


def claim_to_json(claim: Claim) -> dict[str, JsonValue]:
    """Store a claim on the inquiry's grounding row."""
    return {
        "kind": claim.kind, "text": claim.text, "value": claim.value, "source": claim.source,
        "sourceLabel": claim.source_label, "status": claim.status, "ledgerValue": claim.ledger_value,
        "note": claim.note, "replacement": claim.replacement,
    }


def claims_from_json(items: Sequence[dict[str, JsonValue]]) -> tuple[Claim, ...]:
    """Read claims back from a grounding row, skipping any an older release wrote differently."""
    read: list[Claim] = []
    for item in items:
        kind, text, status = item.get("kind"), item.get("text"), item.get("status")
        source, label = item.get("source"), item.get("sourceLabel")
        if not (isinstance(text, str) and isinstance(status, str) and isinstance(source, str)):
            continue
        if not isinstance(kind, str) or kind not in KINDS:
            continue
        ledger_value, note, value = item.get("ledgerValue"), item.get("note"), item.get("value")
        replacement = item.get("replacement")
        read.append(Claim(
            kind=cast("ClaimKind", kind), text=text, value=value if isinstance(value, str) else "",
            source=cast("ClaimSource", source),
            source_label=label if isinstance(label, str) else LABEL_NONE,
            status=cast("ClaimStatus", status),
            ledger_value=ledger_value if isinstance(ledger_value, str) else None,
            note=note if isinstance(note, str) else None,
            replacement=replacement if isinstance(replacement, str) else None,
        ))
    return tuple(read)
