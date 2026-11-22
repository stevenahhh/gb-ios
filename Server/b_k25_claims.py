"""Pure comparison of the numbers in a reply draft with the workshop's own ledger.

Nothing here reads the database or calls the model. The numbers come from b_k25_numbers, so one
model answer never decides a lock by itself.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Final, Literal, cast

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from b_k25_numbers import (
    CLAUSE_BREAK,
    COUNT,
    DAY_MINUTES,
    HOUR_MINUTES,
    NOON,
    AmountSpan,
    DateSpan,
    LengthSpan,
    NumberSpan,
    Reading,
    Span,
    TimeSpan,
    Topic,
    TopicSpan,
    amount_spans,
    amounts_in,
    around,
    date_spans,
    days_named,
    days_near,
    headcounts_in,
    headcounts_near,
    is_denied,
    mentions_topic,
    names_a_day,
    overlaps,
    people_spans,
    quantities_in,
    read,
    time_spans,
    times_near,
    topics_at,
    whole_number,
)
from display import local, month_day, month_day_weekday, weekday, won

type ClaimKind = Literal["price", "seats", "date", "time", "deposit", "fact", "rule"]
type ClaimSource = Literal["ledger", "price_list", "fact_card", "owner_rule", "customer", "none"]
type ClaimStatus = Literal["matched", "mismatched", "unsupported", "unchecked"]
type Lock = Literal["clear", "locked", "unchecked"]

KINDS: Final[frozenset[str]] = frozenset({"price", "seats", "date", "time", "deposit", "fact", "rule"})
NUMBER_KINDS: Final[frozenset[str]] = frozenset({"price", "seats", "date", "time", "deposit"})
UNASKED_PRICE: Final = "손님이 묻지 않은 가격이에요"
NOT_IN_LEDGER: Final = "장부에서 찾지 못했어요"
LABEL_LEDGER: Final = "예약 장부"
LABEL_PRICES: Final = "가격표"
LABEL_WORKSHOP: Final = "공방 안내"
LABEL_RULE: Final = "내 규칙"
LABEL_CUSTOMER: Final = "손님이 쓴 값"
LABEL_NONE: Final = "근거 없음"
NAME_PRICE: Final = "가격"
NAME_DEPOSIT: Final = "예약금"
NAME_DATE: Final = "날짜"
NAME_TIME: Final = "시각"
NAME_SEATS: Final = "남은 자리"
NAME_LENGTH: Final = "수업 길이"
NAME_CAPACITY: Final = "정원"
TOPIC_NAMES: Final[dict[Topic, str]] = {
    "parking": "주차", "refund": "환불", "materials": "재료", "discount": "할인",
}

PRICE_ASKED: Final = re.compile(r"가격|얼마|비용|요금|금액|견적|수업료|할인|단가|총액|예산|만\s*원|\d\s*원")
RULE_MINIMUM: Final = re.compile(rf"(?P<n>{COUNT})\s*(?:명|인|분|사람)\s*(?:부터|이상)")
QUOTED: Final = re.compile(
    r"말씀|문의\s*(?:하신|주신)|물어보|여쭤|요청하신|원하시는|원하신|희망하시|생각하신|예산",
)
ACCEPTS: Final = re.compile(r"가능|괜찮|좋아|좋습|맞아|맞습|받아|받고|받습|드릴게|드려|드립|잡아|뵐|뵙|만나")
CONDITIONAL: Final = re.compile(r"\s*(?:이면|이시면|이라면|라면|정도면)")
CONTACT: Final = re.compile(
    r"연락|전화|답장|답변|회신|문의|상담|알려|안내\s*드|입금|이체|송금|카톡|메시지|영업|운영|오픈",
)
CLASS_TIME: Final = re.compile(r"수업|클래스|체험|시작|진행|오시|오세요|와\s*주|도착|입장|예약|만나|뵐|뵙")
ARRIVAL: Final = re.compile(r"오시|오세요|오셔|와\s*주|도착|입장|모이|모여")
RANGE: Final = re.compile(r"부터|[~\u223c\uff5e\u2013-]|에서|끝|마[치친칠]|종료")
UNTIL: Final = re.compile(r"\s*까지")
EARLY_MINUTES: Final = 30
ENDS: Final = re.compile(r"\s*(?:쯤|경)?\s*(?:에|이면)?\s*(?:끝|마[치칩쳐칠친]|종료)")
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

    @property
    def clock(self) -> tuple[int, int]:
        """Return the minutes of the day the class starts and ends."""
        moment = local(self.starts_at)
        start = moment.hour * HOUR_MINUTES + moment.minute
        return start, (start + self.duration_minutes) % DAY_MINUTES

    @property
    def hours(self) -> str:
        """Name the class by its day and hours."""
        return f"{self.label}~{clock_text(self.clock[1])}"


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

    def topic_text(self, topic: Topic) -> str | None:
        """Return the column the owner filled in for a topic."""
        match topic:
            case "parking":
                return self.parking
            case "refund":
                return self.refund_policy
            case "materials":
                return self.included_materials
            case "discount":
                return None


@dataclass(frozen=True, slots=True)
class RuleFact:
    """One reusable sentence the owner saved; no class means the whole workshop."""

    text: str
    class_name: str | None = None


@dataclass(frozen=True, slots=True)
class OwnerText:
    """Something the owner wrote, and the name its chip shows."""

    source: ClaimSource
    label: str
    body: str


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

    def sessions_at(self, draft: str, position: int) -> tuple[SessionFact, ...]:
        """Return the sessions a number at a position is about, by the day and hour its sentence names."""
        days = days_near(draft, position, self.today)
        sessions = self.dated_sessions(draft)
        if days:
            sessions = tuple(session for session in self.sessions_of(draft) if session.day in days)
        for minutes in times_near(draft, position):
            same = tuple(session for session in sessions if session.clock[0] in minutes)
            if same:
                return same
        return sessions

    def cards_of(self, draft: str) -> tuple[CardFact, ...]:
        """Return the fact cards of the classes in question."""
        names = set(self.classes_named_in(draft))
        return tuple(card for card in self.cards if card.class_name in names)

    def rules_for(self, draft: str) -> tuple[RuleFact, ...]:
        """Return saved rules for the whole workshop or for the classes in question."""
        names = set(self.classes_named_in(draft))
        return tuple(rule for rule in self.rules if rule.class_name is None or rule.class_name in names)

    def class_values(
        self, draft: str, of_session: Callable[[SessionFact], int], of_card: Callable[[CardFact], int | None],
    ) -> frozenset[int]:
        """Return a value of the classes in question; a card counts only for a class without sessions."""
        values: set[int] = set()
        for name in self.classes_named_in(draft):
            listed = {of_session(session) for session in self.sessions if session.title == name}
            written = {of_card(card) for card in self.cards if card.class_name == name}
            values |= listed or {value for value in written if value is not None}
        return frozenset(values)

    def owner_texts(self, draft: str) -> tuple[OwnerText, ...]:
        """Return everything the owner wrote that a reply may rest on."""
        rules = [OwnerText("owner_rule", LABEL_RULE, rule.text) for rule in self.rules_for(draft)]
        cards = [
            OwnerText("fact_card", card_label(card), value)
            for card in self.cards_of(draft) for value in card.texts
        ]
        notes = [OwnerText("fact_card", LABEL_WORKSHOP, note) for note in (*self.facts, *self.policies)]
        return (*rules, *cards, *notes)

    def topic_texts(self, topic: Topic, draft: str) -> tuple[OwnerText, ...]:
        """Return a topic's card column first, then every other owner text that mentions the topic."""
        columns = [
            OwnerText("fact_card", card_label(card), value)
            for card in self.cards_of(draft) if (value := card.topic_text(topic))
        ]
        return (*columns, *(
            text for text in self.owner_texts(draft)
            if text not in columns and mentions_topic(text.body, topic)
        ))


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
    """The claims of one draft, whether its approval must wait, and the kinds of number compared."""

    claims: tuple[Claim, ...]
    lock: Lock
    extraction_ok: bool
    checked: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Found:
    """One checked number, where it stands, and what the screen calls its kind."""

    start: int
    name: str
    claim: Claim


@dataclass(frozen=True, slots=True)
class PriceSource:
    """Where a price may come from: its amounts, and the ones that count for each person."""

    source: ClaimSource
    label: str
    amounts: frozenset[int]
    per_person: frozenset[int] = frozenset()

    def allows(self, span: AmountSpan, heads: frozenset[int]) -> bool:
        """Tell whether an amount is one of these prices, or one of them for the people named."""
        products = {price * people for price in self.per_person for people in heads}
        match span.role:
            case "each":
                return span.won in self.amounts
            case "total":
                fixed = self.amounts - self.per_person if heads else self.amounts
                return span.won in products or span.won in fixed
            case "any":
                return span.won in products or span.won in self.amounts


def mentions(text: str, class_name: str) -> bool:
    """Tell whether a text talks about a class by its name or by a distinctive word of it."""
    words = [word for word in class_name.split() if word not in GENERIC and len(word) > 1]
    return class_name in text or any(word in text for word in (words or [class_name]))


def card_label(card: CardFact) -> str:
    """Name a fact card on a chip."""
    return f"사실 카드: {card.class_name}"


def clock_text(minutes: int) -> str:
    """Write a minute of the day as 24-hour time."""
    return f"{minutes // HOUR_MINUTES:02d}:{minutes % HOUR_MINUTES:02d}"


def spoken_time(minutes: int) -> str:
    """Write a minute of the day the way a reply says it."""
    hour, minute = divmod(minutes, HOUR_MINUTES)
    half = "오전" if hour < NOON else "오후"
    return f"{half} {hour % NOON or NOON}시" + (f" {minute}분" if minute else "")


def length_text(minutes: int) -> str:
    """Write a length in hours and minutes."""
    hours, rest = divmod(minutes, HOUR_MINUTES)
    return " ".join([*([f"{hours}시간"] if hours else []), *([f"{rest}분"] if rest else [])])


def clause_of(draft: str, span: Span) -> str:
    """Return the clause a number stands in."""
    first, last = around(draft, span.start, span.end, CLAUSE_BREAK)
    return draft[first:last]


def quotes_customer(draft: str, span: Span) -> bool:
    """Tell whether a number only repeats or refuses what the customer said; agreeing needs the ledger."""
    if is_denied(draft, span.start, span.end):
        return True
    _, last = around(draft, span.start, span.end, CLAUSE_BREAK)
    quoted = QUOTED.search(clause_of(draft, span)) or CONDITIONAL.match(draft, span.end)
    return quoted is not None and not ACCEPTS.search(draft, span.end, last)


def price_label(amounts: Sequence[int] | frozenset[int]) -> str:
    """Join known prices for a mismatch hint."""
    return " 또는 ".join(won(amount) for amount in sorted(set(amounts)))


def only_won(amounts: Sequence[int] | frozenset[int]) -> str | None:
    """Offer the one known price as a fix; several prices leave the choice to the owner."""
    distinct = set(amounts)
    return won(distinct.pop()) if len(distinct) == 1 else None


def rule_covers(rule: str, heads: frozenset[int]) -> bool:
    """Tell whether a rule such as 6명부터 applies to the people named."""
    minimum = RULE_MINIMUM.search(rule)
    return minimum is None or not heads or max(heads) >= whole_number(minimum["n"])


def written_prices(source: ClaimSource, label: str, texts: Sequence[str]) -> PriceSource:
    """Collect the prices the owner wrote, apart from deposits."""
    spans = [span for text in texts for span in amount_spans(text) if not span.is_deposit]
    return PriceSource(
        source, label, frozenset(span.won for span in spans),
        frozenset(span.won for span in spans if span.role == "each"),
    )


def price_sources(
    span: AmountSpan, draft: str, ledger: Ledger, heads: frozenset[int],
) -> list[PriceSource]:
    """List what may back a price, in the order the chips prefer."""
    prices = frozenset(card.price_won for card in ledger.cards_of(draft) if card.price_won is not None)
    rules = [rule.text for rule in ledger.rules_for(draft) if rule_covers(rule.text, heads)]
    sources = [
        PriceSource("price_list", LABEL_PRICES, prices, prices),
        written_prices("owner_rule", LABEL_RULE, rules),
    ]
    if not span.is_price:
        deposits = frozenset(session.deposit_won for session in ledger.sessions_of(draft))
        sources.append(PriceSource("ledger", LABEL_LEDGER, deposits))
    sources.append(written_prices("fact_card", LABEL_WORKSHOP, [*ledger.facts, *ledger.policies]))
    if not prices and quotes_customer(draft, span):
        sources.append(PriceSource("customer", LABEL_CUSTOMER, amounts_in([ledger.question])))
    return sources


def topic_amount(span: AmountSpan, draft: str, ledger: Ledger) -> OwnerText | None:
    """Find the owner's text behind a fee that is not the class price, such as a parking fee."""
    texts = [
        text for topic in topics_at(draft, span.start) for text in ledger.topic_texts(topic, draft)
    ]
    return next((text for text in texts if span.won in amounts_in([text.body])), None)


def wrong_price(span: AmountSpan, prices: frozenset[int], heads: frozenset[int]) -> Claim:
    """Describe a price no source allows, with the price or the total it should be."""
    value = str(span.won)
    if not prices:
        return Claim("price", span.text, value, "none", LABEL_NONE, "mismatched", note=NOT_IN_LEDGER)
    totals = frozenset(price * people for price in prices for people in heads if people > 1)
    shown, fix = price_label(prices), only_won(prices)
    if totals and span.role == "total":
        shown, fix = f"{price_label(totals)} (1인 {shown})", only_won(totals)
    elif totals and span.role == "any":
        shown, fix = f"1인 {shown}, 합계 {price_label(totals)}", None
    return Claim("price", span.text, value, "price_list", LABEL_PRICES, "mismatched",
                 ledger_value=shown, replacement=fix)


def balances(draft: str, ledger: Ledger, heads: frozenset[int]) -> frozenset[int]:
    """Return what is left to pay after the deposit, for one person or for the people named."""
    prices = {card.price_won for card in ledger.cards_of(draft) if card.price_won is not None}
    deposits = {session.deposit_won for session in ledger.sessions_of(draft)}
    return frozenset(
        price * people - deposit for price in prices for people in heads or {1} for deposit in deposits
    )


def check_price(span: AmountSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a price with the price list, or with it times the people the draft or question names."""
    fee = topic_amount(span, draft, ledger)
    if fee is not None:
        return Claim("price", span.text, str(span.won), fee.source, fee.label, "matched")
    heads = headcounts_near(draft, span, amount_spans(draft)) or headcounts_in(ledger.question)
    sources = price_sources(span, draft, ledger, heads)
    rest = balances(draft, ledger, heads) if span.is_balance else frozenset[int]()
    if rest:
        status: ClaimStatus = "matched" if span.won in rest else "mismatched"
        return Claim("price", span.text, str(span.won), "price_list", LABEL_PRICES, status,
                     ledger_value=None if status == "matched" else price_label(rest),
                     replacement=None if status == "matched" else only_won(rest))
    unasked = PRICE_ASKED.search(ledger.asked) is None
    for found in sources:
        if found.allows(span, heads):
            if unasked and found.source in {"price_list", "owner_rule", "fact_card"}:
                return Claim("price", span.text, str(span.won), found.source, found.label, "mismatched",
                             note=UNASKED_PRICE)
            return Claim("price", span.text, str(span.won), found.source, found.label, "matched")
    if is_denied(draft, span.start, span.end):
        return Claim("price", span.text, str(span.won), "none", LABEL_NONE, "unsupported")
    return wrong_price(span, sources[0].amounts, heads)


def check_deposit(span: AmountSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a deposit with the ledger's deposit for that class."""
    value = str(span.won)
    deposits = [session.deposit_won for session in ledger.sessions_of(draft)]
    if not deposits:
        deposits = [card.deposit_won for card in ledger.cards_of(draft) if card.deposit_won is not None]
    if span.won in deposits:
        return Claim("deposit", span.text, value, "ledger", LABEL_LEDGER, "matched")
    for text in ledger.owner_texts(draft):
        if any(other.is_deposit and other.won == span.won for other in amount_spans(text.body)):
            return Claim("deposit", span.text, value, text.source, text.label, "matched")
    if deposits:
        return Claim("deposit", span.text, value, "ledger", LABEL_LEDGER, "mismatched",
                     ledger_value=price_label(deposits), replacement=only_won(deposits))
    return Claim("deposit", span.text, value, "none", LABEL_NONE, "mismatched", note=NOT_IN_LEDGER)


def check_seats(span: NumberSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a seat count with what the sessions it is about still have."""
    value = str(span.value)
    candidates = ledger.sessions_at(draft, span.start)

    def fits(session: SessionFact) -> bool:
        if span.exact:
            return session.seats_left == span.value
        return session.seats_left >= span.value or (span.is_limit and session.capacity == span.value)

    if any(fits(session) for session in candidates) != span.denied:
        return Claim("seats", span.text, value, "ledger", LABEL_LEDGER, "matched")
    if not candidates:
        return Claim("seats", span.text, value, "ledger", LABEL_LEDGER, "mismatched", note=NOT_IN_LEDGER)
    closest = min(candidates, key=lambda session: abs(session.seats_left - span.value))
    can_fix = len(candidates) == 1 and not span.denied
    return Claim("seats", span.text, value, "ledger", LABEL_LEDGER, "mismatched",
                 ledger_value=f"{closest.label} {closest.seats_left}자리",
                 replacement=span.with_value(closest.seats_left) if can_fix else None)


def date_support(span: DateSpan, draft: str, ledger: Ledger) -> tuple[ClaimSource, str] | None:
    """Find what else backs a date: the owner's notes, or a denial of what the customer asked."""
    def says(text: str) -> bool:
        return any((other.month, other.day) == (span.month, span.day) for other in date_spans(text))

    for text in ledger.owner_texts(draft):
        if says(text.body):
            return text.source, text.label
    if says(ledger.question) and quotes_customer(draft, span):
        return "customer", LABEL_CUSTOMER
    return ("ledger", LABEL_LEDGER) if span.denied else None


def refund_deadlines(span: DateSpan, draft: str, ledger: Ledger) -> list[date]:
    """Return the last refund days, for a date that stands in a sentence about refunds."""
    if "refund" not in topics_at(draft, span.start):
        return []
    texts = ledger.topic_texts("refund", draft)
    allowed = days_of([
        other for text in texts for other in quantities_in(text.body, "refund") if not other.denied
    ])
    return sorted({
        session.day - timedelta(days=round(days)) for session in ledger.sessions_of(draft) for days in allowed
    })


def check_date(span: DateSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a date, and the weekday beside it, with the days of the class."""
    value = f"{span.month:02d}-{span.day:02d}"
    days = sorted({session.day for session in ledger.sessions_of(draft)})
    deadlines = refund_deadlines(span, draft, ledger)
    same = [day for day in (*days, *deadlines) if span.names(day)]
    if any(span.weekday in {"", weekday(day)} for day in same):
        return Claim("date", span.text, value, "ledger", LABEL_LEDGER, "matched")
    support = None if same else date_support(span, draft, ledger)
    if support is not None:
        return Claim("date", span.text, value, *support, "matched")
    choices = same or deadlines or days
    if not choices:
        return Claim("date", span.text, value, "ledger", LABEL_LEDGER, "mismatched", note=NOT_IN_LEDGER)
    full = f"{month_day_weekday(choices[0])}요일"
    fix = full if span.weekday else month_day(choices[0])
    return Claim("date", span.text, value, "ledger", LABEL_LEDGER, "mismatched", ledger_value=full,
                 replacement=fix if len(choices) == 1 and not span.denied else None)


def is_end(span: TimeSpan, draft: str) -> bool:
    """Tell whether a time says when the class ends rather than when it starts."""
    first, _ = around(draft, span.start, span.end, CLAUSE_BREAK)
    ends = [other.end for other in time_spans(draft) if first <= other.start < span.start]
    earlier = max(ends, default=None)
    if earlier is not None and RANGE.search(draft, earlier, span.start):
        return True
    after = draft[span.end:]
    if ENDS.match(after):
        return True
    return UNTIL.match(after) is not None and not ARRIVAL.search(clause_of(draft, span))


def time_support(span: TimeSpan, draft: str, ledger: Ledger) -> tuple[ClaimSource, str] | None:
    """Find what else backs a time: the owner's notes on the same matter, or the customer's words."""
    def says(text: str) -> bool:
        return any(span.minutes & other.minutes for other in time_spans(text))

    about_class = CLASS_TIME.search(clause_of(draft, span)) is not None
    for text in ledger.owner_texts(draft):
        if says(text.body) and (not about_class or CLASS_TIME.search(text.body)):
            return text.source, text.label
    if says(ledger.question) and quotes_customer(draft, span):
        return "customer", LABEL_CUSTOMER
    return None


def comes_early(span: TimeSpan, clause: str, sessions: Sequence[SessionFact]) -> bool:
    """Tell whether a time only asks the customer to arrive a little before the class."""
    early = (session.clock[0] - minute for session in sessions for minute in span.minutes)
    return ARRIVAL.search(clause) is not None and any(0 < gap <= EARLY_MINUTES for gap in early)


def check_time(span: TimeSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a time of day with when the class starts or ends on the day it is about."""
    value = clock_text(min(span.minutes))
    sessions = ledger.sessions_at(draft, span.start)
    at_end = is_end(span, draft)
    known = {session.clock[1 if at_end else 0] for session in sessions}
    runs = not known.isdisjoint(span.minutes)
    if runs != span.denied:
        return Claim("time", span.text, value, "ledger", LABEL_LEDGER, "matched")
    support = None if runs else time_support(span, draft, ledger)
    if support is not None:
        return Claim("time", span.text, value, *support, "matched")
    clause = clause_of(draft, span)
    is_contact = CONTACT.search(clause) and not CLASS_TIME.search(clause)
    if not runs and (is_contact or comes_early(span, clause, sessions)):
        return Claim("time", span.text, value, "none", LABEL_NONE, "unsupported")
    if not sessions:
        return Claim("time", span.text, value, "ledger", LABEL_LEDGER, "mismatched", note=NOT_IN_LEDGER)
    nearest = min(sessions, key=lambda session: abs(session.clock[0] - min(span.minutes)))
    fix = None
    if len(known) == 1 and not span.denied:
        minutes = next(iter(known))
        fix = clock_text(minutes) if span.is_clock else spoken_time(minutes)
    return Claim("time", span.text, value, "ledger", LABEL_LEDGER, "mismatched",
                 ledger_value=nearest.hours, replacement=fix)


def check_length(span: LengthSpan, known: frozenset[int], *, in_ledger: bool) -> Claim:
    """Compare a class length with the known lengths of that class."""
    value = str(span.high)
    source, label = class_source(in_ledger=in_ledger)
    if not known:
        return Claim("fact", span.text, value, "none", LABEL_NONE, "unsupported")
    if any(span.low <= minutes <= span.high for minutes in known):
        return Claim("fact", span.text, value, source, label, "matched")
    fix = None
    if len(known) == 1:
        minutes = next(iter(known))
        fix = length_text(minutes) if span.in_hours else f"{minutes}분"
    return Claim("fact", span.text, value, source, label, "mismatched",
                 ledger_value=" 또는 ".join(f"{item}분" for item in sorted(known)), replacement=fix)


def check_capacity(span: NumberSpan, known: frozenset[int], *, in_ledger: bool) -> Claim:
    """Compare a stated capacity with the known capacities of that class."""
    value = str(span.value)
    source, label = class_source(in_ledger=in_ledger)
    if not known:
        return Claim("fact", span.text, value, "none", LABEL_NONE, "unsupported")
    if span.value in known:
        return Claim("fact", span.text, value, source, label, "matched")
    return Claim("fact", span.text, value, source, label, "mismatched",
                 ledger_value=" 또는 ".join(f"{item}명" for item in sorted(known)),
                 replacement=span.with_value(next(iter(known))) if len(known) == 1 else None)


def class_source(*, in_ledger: bool) -> tuple[ClaimSource, str]:
    """Say whether a class fact comes from the ledger or from a card."""
    return ("ledger", LABEL_LEDGER) if in_ledger else ("fact_card", LABEL_WORKSHOP)


def days_of(spans: Sequence[TopicSpan]) -> set[float]:
    """Collect the day counts among some quantities."""
    return {amount for span in spans for unit, amount in span.values if unit == "일"}


def topic_status(span: TopicSpan, written: Sequence[TopicSpan]) -> ClaimStatus:
    """Compare a quantity with the owner's text; a refusal is compared with the days that text allows."""
    same = [other for other in written if span.values & other.values]
    if not span.denied:
        return "matched" if same else "mismatched"
    if any(other.denied for other in same):
        return "matched"
    stated = days_of([span])
    allowed = days_of([other for other in written if not other.denied])
    if span.topic != "refund" or not (stated and allowed):
        return "matched" if same else "unsupported"
    return "matched" if max(stated) < max(allowed) else "mismatched"


def quantity_text(span: TopicSpan, unit: str, amount: float) -> str | None:
    """Write the owner's quantity in the place of the draft's own."""
    number = f"{amount:g}"
    if unit == "분":
        return length_text(round(amount))
    if unit == "일" and span.text in {"당일", "전날"}:
        return f"{number}일 전" if span.text == "전날" else None
    return f"{number}{unit}"


def topic_fix(span: TopicSpan, written: Sequence[TopicSpan]) -> str | None:
    """Offer the owner's quantity when the text has exactly one of the same unit."""
    units = {unit for unit, _ in span.values}
    known = {value for other in written if not other.denied for value in other.values if value[0] in units}
    if span.denied or len(known) != 1:
        return None
    return quantity_text(span, *known.pop())


def for_people(
    span: TopicSpan, written: Sequence[TopicSpan], draft: str, ledger: Ledger,
) -> list[TopicSpan]:
    """Allow two aprons for two people when the card says one."""
    if span.topic != "materials":
        return []
    heads = headcounts_near(draft, span, ()) or headcounts_in(ledger.question)
    return [
        replace(other, values=frozenset((unit, amount * people) for unit, amount in other.values))
        for other in written for people in heads
    ]


def check_topic(span: TopicSpan, draft: str, ledger: Ledger) -> Claim:
    """Compare a quantity about parking, refunds, or materials with what the owner wrote about it."""
    texts = ledger.topic_texts(span.topic, draft)
    read_texts = [(text, quantities_in(text.body, span.topic)) for text in texts]
    written = [quantity for _, quantities in read_texts for quantity in quantities]
    status = topic_status(span, [*written, *for_people(span, written, draft, ledger)])
    if not texts:
        return Claim("fact", span.text, span.text, "none", LABEL_NONE, status,
                     note=NOT_IN_LEDGER if status == "mismatched" else None)
    units = {unit for unit, _ in span.values}
    near = [
        text for text, quantities in read_texts
        if any(unit in units for other in quantities for unit, _ in other.values)
    ]
    shown = (near or list(texts))[0]
    if status == "unsupported":
        return Claim("fact", span.text, span.text, "none", LABEL_NONE, status)
    if status == "matched":
        return Claim("fact", span.text, span.text, shown.source, shown.label, status)
    return Claim("fact", span.text, span.text, shown.source, shown.label, status,
                 ledger_value=shown.body, replacement=topic_fix(span, written))


def find_numbers(draft: str, ledger: Ledger, reading: Reading) -> list[Found]:
    """Check every number the patterns read, in the order the draft states them."""
    in_ledger = bool(ledger.sessions_of(draft))
    lengths = ledger.class_values(
        draft, lambda session: session.duration_minutes, lambda card: card.duration_minutes,
    )
    capacities = ledger.class_values(draft, lambda session: session.capacity, lambda card: card.capacity)
    found = [
        Found(span.start, NAME_DEPOSIT, check_deposit(span, draft, ledger)) if span.is_deposit
        else Found(span.start, NAME_PRICE, check_price(span, draft, ledger))
        for span in reading.amounts
    ]
    found += [Found(span.start, NAME_DATE, check_date(span, draft, ledger)) for span in reading.dates]
    found += [Found(span.start, NAME_TIME, check_time(span, draft, ledger)) for span in reading.times]
    found += [Found(span.start, NAME_SEATS, check_seats(span, draft, ledger)) for span in reading.seats]
    found += [
        Found(span.start, NAME_LENGTH, check_length(span, lengths, in_ledger=in_ledger))
        for span in reading.lengths
    ]
    found += [
        Found(span.start, NAME_CAPACITY, check_capacity(span, capacities, in_ledger=in_ledger))
        for span in reading.capacities
    ]
    found += [
        Found(span.start, TOPIC_NAMES[span.topic], check_topic(span, draft, ledger))
        for span in reading.topics
    ]
    return sorted(found, key=lambda item: item.start)


def check_numbers(draft: str, ledger: Ledger) -> list[Claim]:
    """Check every number the patterns read and return what the ledger says about each."""
    return [item.claim for item in find_numbers(draft, ledger, read(draft))]


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


def places(draft: str, text: str) -> list[Span]:
    """Return every place a text stands in a draft."""
    return [Span(m.start(), m.end(), text) for m in re.finditer(re.escape(text), draft)]


def states_number(claim: ModelClaim) -> bool:
    """Tell whether the model says it found a number, rather than a word such as 무료."""
    digits = re.sub(r"\D", "", claim.value)
    has_number = bool(digits.strip("0")) or re.search(r"\d", claim.text) is not None
    return claim.kind in NUMBER_KINDS and has_number


def agrees(draft: str, reading: Reading, model_claims: Sequence[ModelClaim], today: date) -> bool:
    """Check that the model points at every price, seat, and date the patterns read, and at no other.

    A number only the model can read was not compared with anything, so the check did not see it.
    """
    pointed = [place for claim in model_claims for place in places(draft, claim.text)]
    if not all(overlaps(span, pointed) for span in (*reading.amounts, *reading.dates, *reading.seats)):
        return False
    readable = [*reading.spans, *people_spans(draft)]
    return all(
        names_a_day(claim.text, today)
        or any(overlaps(place, readable) for place in places(draft, claim.text))
        for claim in model_claims if states_number(claim)
    )


def bigrams(text: str) -> frozenset[str]:
    """Character pairs without spaces or punctuation, which survive Korean endings."""
    letters = re.sub(r"[\s\W_]+", "", text)
    return frozenset(letters[i:i + 2] for i in range(len(letters) - 1))


def support_of(text: str, ledger: Ledger) -> tuple[ClaimSource, str] | None:
    """Find the owner's text that a statement rests on, if it rests on one."""
    wanted = bigrams(text)
    if len(wanted) < MIN_FACT_CHARS - 1:
        return None
    sources = [*ledger.owner_texts(text), OwnerText("customer", LABEL_CUSTOMER, ledger.question)]
    best: tuple[float, ClaimSource, str] = (0.0, "none", LABEL_NONE)
    for source in sources:
        share = len(wanted & bigrams(source.body)) / len(wanted)
        if share > best[0]:
            best = (share, source.source, source.label)
    return (best[1], best[2]) if best[0] >= SUPPORT_RATIO else None


def is_number_check(text: str, draft: str, reading: Reading) -> bool:
    """Tell whether a statement stands on a number the check already covers."""
    return any(overlaps(place, reading.spans) for place in places(draft, text))


def check_statements(
    draft: str, ledger: Ledger, model_claims: Sequence[ModelClaim], reading: Reading,
) -> list[Claim]:
    """Report the model's facts and rules that no number check already covers."""
    claims: list[Claim] = []
    for claim in model_claims:
        if is_number_check(claim.text, draft, reading):
            continue
        support = support_of(claim.text, ledger)
        source, label = support or ("none", LABEL_NONE)
        kind: ClaimKind = "rule" if claim.kind == "rule" else "fact"
        claims.append(Claim(
            kind, claim.text, claim.value, source, label,
            "matched" if support else "unsupported",
        ))
    return claims


def evaluation(found: Sequence[Found], statements: Sequence[Claim], *, extraction_ok: bool) -> Evaluation:
    """Lock on any known mismatch; without an agreeing extraction the rest stays unchecked."""
    claims = (*(item.claim for item in found), *statements)
    compared = [item.name for item in found if item.claim.status in {"matched", "mismatched"}]
    if any(item.claim.status == "mismatched" for item in found):
        lock: Lock = "locked"
    else:
        lock = "clear" if extraction_ok else "unchecked"
    return Evaluation(claims, lock, extraction_ok, tuple(dict.fromkeys(compared)))


def evaluate(
    draft: str, ledger: Ledger, model_claims: Sequence[ModelClaim] | None,
) -> Evaluation:
    """Check one freshly written draft."""
    reading = read(draft)
    found = find_numbers(draft, ledger, reading)
    if model_claims is None:
        return evaluation(found, (), extraction_ok=False)
    statements = check_statements(draft, ledger, model_claims, reading)
    return evaluation(
        found, statements, extraction_ok=agrees(draft, reading, model_claims, ledger.today),
    )


def recheck(
    draft: str, ledger: Ledger, kept: Sequence[Claim], *, extraction_ok: bool,
) -> Evaluation:
    """Check a draft the owner changed, without asking the model again.

    Numbers are read again from the text; the model's earlier statements stay when their
    text is still in the draft. A draft whose extraction never agreed stays unchecked at best.
    """
    reading = read(draft)
    statements = [
        claim for claim in kept
        if claim.kind in {"fact", "rule"} and claim.text in draft
        and not is_number_check(claim.text, draft, reading)
    ]
    return evaluation(find_numbers(draft, ledger, reading), statements, extraction_ok=extraction_ok)


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
    read_claims: list[Claim] = []
    for item in items:
        kind, text, status = item.get("kind"), item.get("text"), item.get("status")
        source, label = item.get("source"), item.get("sourceLabel")
        if not (isinstance(text, str) and isinstance(status, str) and isinstance(source, str)):
            continue
        if not isinstance(kind, str) or kind not in KINDS:
            continue
        ledger_value, note, value = item.get("ledgerValue"), item.get("note"), item.get("value")
        replacement = item.get("replacement")
        read_claims.append(Claim(
            kind=cast("ClaimKind", kind), text=text, value=value if isinstance(value, str) else "",
            source=cast("ClaimSource", source),
            source_label=label if isinstance(label, str) else LABEL_NONE,
            status=cast("ClaimStatus", status),
            ledger_value=ledger_value if isinstance(ledger_value, str) else None,
            note=note if isinstance(note, str) else None,
            replacement=replacement if isinstance(replacement, str) else None,
        ))
    return tuple(read_claims)
