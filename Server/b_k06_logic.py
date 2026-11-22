"""Pure refund rules, message reading, and fixed wording; nothing here calls a model or a database."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_output import reply_problems
from contracts import ApiRequest
from display import clock, local, month_day, weekday, won

type Kind = Literal["cancel", "change", "question"]
type Decision = Literal["by_rule", "carry_over", "full_refund", "custom"]
type Category = Literal["health", "family", "schedule", "weather", "other"]
CUSTOMER_ALIAS: Final = "손님A"
DEFAULT_LATE_MINUTES: Final = 15
MAX_NOTE: Final = 200
MAX_DAYS: Final = 365
MAX_LATE: Final = 180
FULL: Final = 100
RECENT_PAST_DAYS: Final = 180


class Rule(ApiRequest):
    """One tier: cancelling this many days before, or more, refunds this share. None means undecided."""

    days_before: Annotated[int, Field(ge=0, le=MAX_DAYS)]
    refund_percent: Annotated[int, Field(ge=0, le=FULL)] | None = None
    deduct_material: bool = False
    carry_over_allowed: bool = False
    note: Annotated[str, Field(max_length=MAX_NOTE)] = ""


class LateRule(ApiRequest):
    """When a late guest counts as a no-show."""

    late_minutes: Annotated[int, Field(ge=1, le=MAX_LATE)]
    note: Annotated[str, Field(max_length=MAX_NOTE)] = ""


class ExtractedPolicy(BaseModel):
    """The JSON the model writes for an owner's rule text."""

    rules: list[Rule] = []
    late: LateRule | None = None
    unread: list[str] = []


class ExtractedMessage(BaseModel):
    """The JSON the model writes for a pasted customer message."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)
    day: Annotated[date | None, Field(alias="date")] = None
    kind: Kind


@dataclass(frozen=True, slots=True)
class Policy:
    """A rule table as the calculator reads it."""

    rules: tuple[Rule, ...]
    late: LateRule | None
    unread: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Payment:
    """What the customer paid and what the materials cost, in won."""

    paid: int
    material: int | None


@dataclass(frozen=True, slots=True)
class Quote:
    """A reference calculation; refund is None when the owner has to decide."""

    days_left: int
    rule: Rule | None
    refund: int | None


def days_left(starts_at: datetime, at: datetime) -> int:
    """Count calendar days in workshop time."""
    return (local(starts_at).date() - local(at).date()).days


def matched_rule(rules: Iterable[Rule], left: int) -> Rule | None:
    """Take the first tier, largest days first, that this many remaining days still reach."""
    ordered = sorted(rules, key=lambda rule: rule.days_before, reverse=True)
    return next((rule for rule in ordered if left >= rule.days_before), None)


def compute(rules: Iterable[Rule], starts_at: datetime, at: datetime, payment: Payment) -> Quote:
    """Apply the owner's tiers in whole won; a missing cost or tier is left to the owner."""
    left = days_left(starts_at, at)
    rule = matched_rule(rules, left)
    if rule is None or rule.refund_percent is None:
        return Quote(left, rule, None)
    refund = payment.paid * rule.refund_percent // FULL
    if rule.deduct_material and refund > 0:
        if payment.material is None:
            return Quote(left, rule, None)
        refund = max(refund - payment.material, 0)
    return Quote(left, rule, refund)


# Reading an owner's rule text without a model.

CLAUSE: Final = re.compile(r"[.\n,;]+|(?<=고)\s+(?=당일|전날|\d+일)")
DAYS: Final = re.compile(r"(\d{1,3})\s*일\s*전")
PERCENT: Final = re.compile(r"(\d{1,3})\s*(?:%|퍼센트|프로)")
MINUTES: Final = re.compile(r"(\d{1,3})\s*분")
NO_REFUND: Final = re.compile(r"환불\s*(?:은|이)?\s*(?:불가|없|안\s*[돼되]|어렵)|불가")
HALF: Final = re.compile(r"반액|절반")
DEDUCT: Final = re.compile(r"재료비.*(?:공제|제외|빼|차감)")
CARRY: Final = re.compile(r"이월|옮길|옮겨|변경\s*가능")


def squashed(text: str) -> str:
    """Compare wording without whitespace differences."""
    return re.sub(r"\s+", "", text)


def day_of(clause: str) -> int | None:
    """Read how many days before class a clause speaks about."""
    if match := DAYS.search(clause):
        return int(match.group(1))
    named = {"일주일 전": 7, "일주일전": 7, "전날": 1, "하루 전": 1, "당일": 0}
    return next((days for word, days in named.items() if word in clause), None)


def percent_of(clause: str) -> int | None:
    """Read a refund share; a refusal wins over 전액."""
    if match := PERCENT.search(clause):
        value = int(match.group(1))
        return value if value <= FULL else None
    if NO_REFUND.search(clause):
        return 0
    if HALF.search(clause):
        return 50
    return FULL if "전액" in clause else None


def parse_policy(text: str) -> ExtractedPolicy:
    """Read the plain clauses of a rule text; anything unclear goes to unread."""
    rules: list[Rule] = []
    unread: list[str] = []
    late: LateRule | None = None
    for part in CLAUSE.split(text):
        clause = part.strip()[:MAX_NOTE]
        if not clause:
            continue
        minutes = MINUTES.search(clause)
        if minutes and ("지각" in clause or "노쇼" in clause or "늦" in clause):
            value = int(minutes.group(1))
            if late is None and 1 <= value <= MAX_LATE:
                late = LateRule(late_minutes=value, note=clause)
            continue
        days, percent = day_of(clause), percent_of(clause)
        if days is None and percent is None and not re.search(r"환불|취소|이월|재료비", clause):
            continue
        if days is None or percent is None or days > MAX_DAYS:
            unread.append(clause)
            continue
        rules.append(Rule(
            days_before=days, refund_percent=percent, deduct_material=bool(DEDUCT.search(clause)),
            carry_over_allowed=bool(CARRY.search(clause)), note=clause,
        ))
    return ExtractedPolicy(rules=rules, late=late, unread=unread)


def checked_policy(raw: ExtractedPolicy, source: str) -> Policy:
    """Keep only rows quoting the source, one per day; unread day conditions become undecided rows."""
    original = squashed(source)
    rules: dict[int, Rule] = {}
    unread = list(raw.unread)
    for rule in raw.rules:
        quoted = bool(rule.note.strip()) and squashed(rule.note) in original
        if quoted and rule.days_before not in rules:
            rules[rule.days_before] = rule
        else:
            unread.append(rule.note.strip() or f"{day_label(rule.days_before)} 조건")
    for phrase in unread:
        days = day_of(phrase)
        if days is not None and days not in rules:
            rules[days] = Rule(days_before=days, note=phrase[:MAX_NOTE])
    late = raw.late if raw.late and squashed(raw.late.note) in original else None
    ordered = tuple(sorted(rules.values(), key=lambda rule: rule.days_before, reverse=True))
    return Policy(ordered, late, tuple(dict.fromkeys(unread)))


def policy_problems(text: str) -> list[str]:
    """Report model output that is not the rule JSON."""
    try:
        _ = ExtractedPolicy.model_validate_json(text)
    except ValidationError:
        return ["정해진 JSON 형식이 아님"]
    return []


def message_problems(text: str) -> list[str]:
    """Report model output that is not the message JSON."""
    try:
        _ = ExtractedMessage.model_validate_json(text)
    except ValidationError:
        return ["정해진 JSON 형식이 아님"]
    return []


# Reading a pasted customer message without a model.

PHONE: Final = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")
MONTH_DAY: Final = re.compile(r"(\d{1,2})\s*(?:월|/)\s*(\d{1,2})\s*일?")
WEEKDAY: Final = re.compile(r"(이번\s*주|다음\s*주|담주)?\s*([월화수목금토일])요일")
CANCELS: Final = re.compile(r"취소|환불|못\s*(?:가|갈|갑|오)|불참|안\s*될\s*것|어려울\s*것")
CHANGES: Final = re.compile(r"변경|바꾸|바꿀|옮기|옮길|미루|미룰|다른\s*날")
CATEGORY_WORDS: Final[tuple[tuple[Category, re.Pattern[str]], ...]] = (
    ("health", re.compile(r"아프|아파|아픈|병원|감기|독감|코로나|열이|수술|입원|다쳤|다쳐|몸이")),
    ("family", re.compile(r"가족|부모|아이|장례|상을|결혼|어머니|아버지")),
    ("schedule", re.compile(r"일정|출장|회사|야근|회의|출근|약속|시험")),
    ("weather", re.compile(r"태풍|폭설|폭우|눈이|비가|날씨")),
)


def category_of(text: str) -> Category | None:
    """Name the kind of reason, so only a label of a message is ever compared or kept."""
    return next((name for name, words in CATEGORY_WORDS if words.search(text)), None)


def kind_of(text: str) -> Kind:
    """Name what the customer asks for."""
    if CHANGES.search(text):
        return "change"
    return "cancel" if CANCELS.search(text) else "question"


def date_of(text: str, today: date) -> date | None:
    """Resolve an explicit or relative class date."""
    if match := MONTH_DAY.search(text):
        try:
            day = date(today.year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None
        return day.replace(year=day.year + 1) if (today - day).days > RECENT_PAST_DAYS else day
    for word, offset in (("오늘", 0), ("내일", 1), ("모레", 2)):
        if word in text:
            return today + timedelta(days=offset)
    if match := WEEKDAY.search(text):
        target = "월화수목금토일".index(match.group(2))
        monday = today - timedelta(days=today.weekday())
        week = match.group(1)
        if week is None:
            return today + timedelta(days=(target - today.weekday()) % 7)
        return monday + timedelta(days=target + (0 if week.startswith("이번") else 7))
    return None


def mentions(text: str, name: str) -> bool:
    """Tell whether a message names this customer by full or given name."""
    given = name[1:]
    return name in text or (len(given) > 1 and given in text)


def without_identity(text: str, names: Iterable[str]) -> str:
    """Replace phone numbers and known names before text leaves for the model."""
    masked = PHONE.sub("[번호]", text)
    for name in sorted(names, key=len, reverse=True):
        masked = masked.replace(name, CUSTOMER_ALIAS)
        if len(name[1:]) > 1:
            masked = masked.replace(name[1:], CUSTOMER_ALIAS)
    return masked


# Fixed wording.


def day_label(days: int) -> str:
    """Name a tier's days."""
    return "당일" if days == 0 else f"{days}일 전까지"


def percent_label(percent: int | None) -> str:
    """Name a tier's refund."""
    match percent:
        case None:
            return "정하지 않음"
        case 0:
            return "환불 없음"
        case 100:
            return "전액 환불"
        case _:
            return f"{percent}% 환불"


def rule_label(rule: Rule) -> str:
    """Write one tier on one line."""
    extras = [
        text for keep, text in (
            (rule.deduct_material, "재료비 공제"), (rule.carry_over_allowed, "이월 가능"),
        ) if keep
    ]
    return " · ".join([f"{day_label(rule.days_before)} {percent_label(rule.refund_percent)}", *extras])


def policy_summary(rules: Sequence[Rule], late: LateRule | None) -> str:
    """Write the two lines a confirmation reply carries."""
    lines = ["취소 규정: " + ", ".join(rule_label(rule) for rule in rules if rule.refund_percent is not None)]
    if late is not None:
        lines.append(f"지각 규정: {late.late_minutes}분 넘게 늦으시면 노쇼로 처리해요.")
    return "\n".join(lines)


def change_summary(before: Policy | None, after: Policy) -> str:
    """Say which tiers differ from the previous version."""
    if before is None:
        return "첫 규정"
    old = {rule.days_before: rule_label(rule) for rule in before.rules}
    new = {rule.days_before: rule_label(rule) for rule in after.rules}
    changed = [day for day in sorted({*old, *new}, reverse=True) if old.get(day) != new.get(day)]
    parts = [new.get(day, f"{day_label(day)} 삭제") for day in changed]
    if before.late != after.late:
        parts.append("지각 기준")
    return ", ".join(parts) or "바뀐 행 없음"


@dataclass(frozen=True, slots=True)
class ReplyFacts:
    """Everything a cancellation reply may state."""

    customer: str
    class_title: str
    class_when: str
    decision: Decision
    reason: str
    paid: int
    refund: int
    days: int
    version: int | None
    noticed: date | None

    @property
    def basis_phrase(self) -> str:
        """Name the rule version only when this customer was told about it."""
        if self.version is None or self.noticed is None:
            return "공방 규정"
        return f"{month_day(self.noticed)}에 안내드린 규정 {self.version}판"

    def lines(self) -> list[str]:
        """List the facts for the model; every number it may use is here."""
        outcome = {
            "by_rule": "규정대로 처리", "carry_over": "다음 회차로 1회 이월, 환불 없음",
            "full_refund": "이번만 전액 환불", "custom": "사장님이 정한 금액으로 처리",
        }[self.decision]
        refund = (
            f"환불액 {won(self.refund)}, 환불해 드릴게요" if self.refund
            else "이번 취소는 돌려드리는 금액 없음"
        )
        facts = [
            f"받는 사람: {CUSTOMER_ALIAS} 님",
            f"수업: {self.class_title}, {self.class_when}",
            f"근거: {self.basis_phrase}",
            f"취소 시점: {when_label(self.days)}",
            f"낸 예약금 {won(self.paid)}",
            f"사장님 결정: {outcome}",
            refund,
        ]
        if self.reason:
            facts.append(f"사장님이 적은 사유: {without_identity(self.reason, [self.customer])}")
        return facts


def when_text(moment: datetime) -> str:
    """Write a class start in plain words."""
    day = local(moment).date()
    return f"{month_day(day)} {weekday(day)}요일 {clock(moment)}"


def when_label(left: int) -> str:
    """Name how early the cancellation is."""
    return "당일" if left <= 0 else f"{left}일 전"


def fallback_reply(facts: ReplyFacts) -> str:
    """Write the reply without a model, from the same facts."""
    opening = f"{facts.customer} 님, 연락 주셔서 감사해요."
    account = "돌려받으실 계좌를 알려 주세요."
    when = when_label(facts.days)
    match facts.decision:
        case "by_rule" if facts.refund > 0:
            body = (
                f"{facts.basis_phrase}에 따라 {when} 취소는 예약금 {won(facts.paid)} 가운데 "
                f"{won(facts.refund)}을 돌려드려요. {account}"
            )
        case "by_rule":
            body = f"{facts.basis_phrase}에 따라 {when} 취소는 예약금을 돌려드리기 어려워요. 양해 부탁드려요."
        case "carry_over":
            body = "이번에는 다음 회차로 한 번 옮겨 드릴게요. 편한 날짜를 알려 주세요."
        case "full_refund":
            body = f"이번에는 예약금 {won(facts.refund)}을 모두 돌려드릴게요. {account}"
        case "custom" if facts.refund > 0:
            body = f"이번에는 {won(facts.refund)}을 돌려드릴게요. {account}"
        case "custom":
            body = "이번 취소는 예약금을 돌려드리기 어려워요. 양해 부탁드려요."
    return f"{opening} {body}"


NUMBER: Final = re.compile(r"\d[\d,]*")
WORDED_AMOUNT: Final = re.compile(r"[일이삼사오육칠팔구십백천만\d]\s*[십백천만]\s*원|[십백천만]\s*원")
LEGAL: Final = re.compile(r"법적|법률|의무|소송")
CARRY_PROMISE: Final = re.compile(r"이월|다음\s*회차|옮겨\s*드")


def numbers(text: str) -> set[str]:
    """Collect numbers with separators removed."""
    return {match.expand(r"\g<0>").replace(",", "") for match in NUMBER.finditer(text)}


def reply_check(text: str, facts: ReplyFacts) -> list[str]:
    """Refuse a reply whose numbers, decision, or tone differ from the facts."""
    basis = "\n".join(facts.lines())
    problems = reply_problems(text, basis=basis, question="")
    problems += [f"근거 없는 숫자 {value}" for value in sorted(numbers(text) - numbers(basis))]
    if WORDED_AMOUNT.search(text):
        problems.append("금액은 20,000원처럼 숫자로만 쓰기")
    if LEGAL.search(text):
        problems.append("법이나 의무라는 표현")
    if CUSTOMER_ALIAS not in text:
        problems.append(f"{CUSTOMER_ALIAS} 님으로 부르지 않음")
    if facts.refund and str(facts.refund) not in numbers(text):
        problems.append("환불액 누락")
    if "전액" in text and facts.refund != facts.paid:
        problems.append("전액이라는 표현")
    if (facts.decision == "carry_over") != bool(CARRY_PROMISE.search(text)):
        problems.append("이월 안내가 사장님 결정과 다름")
    return problems


def edited_characters(before: str, after: str) -> int:
    """Count the characters left between the shared start and end of two drafts."""
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    end = 0
    limit = min(len(before), len(after)) - start
    while end < limit and before[-1 - end] == after[-1 - end]:
        end += 1
    return max(len(before), len(after)) - start - end
