"""Pure refund rules, message reading, and fixed wording; nothing here calls a model or a database."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Annotated, ClassVar, Final, Literal
from unicodedata import normalize

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


def overreaches(rule: Rule, tiers: Sequence[Rule], left: int) -> bool:
    """Tell when only a late tier exists, so it must not speak for an earlier cancellation."""
    earliest = max(tier.days_before for tier in tiers)
    speaks_late = rule.refund_percent != FULL and (rule.days_before == 0 or rule.refund_percent == 0)
    return rule.days_before == earliest and left > rule.days_before and speaks_late


def compute(rules: Iterable[Rule], starts_at: datetime, at: datetime, payment: Payment) -> Quote:
    """Apply the owner's tiers in whole won; a missing cost or tier is left to the owner."""
    left = days_left(starts_at, at)
    tiers = tuple(rules)
    rule = matched_rule(tiers, left)
    if rule is None or rule.refund_percent is None or overreaches(rule, tiers, left):
        return Quote(left, rule, None)
    refund = payment.paid * rule.refund_percent // FULL
    if rule.deduct_material and refund > 0:
        if payment.material is None:
            return Quote(left, rule, None)
        refund = max(refund - payment.material, 0)
    return Quote(left, rule, refund)


# Reading an owner's rule text. A sentence becomes a number only when all of it fits a known plain form;
# anything else is undecided or unread, because a wrong refund costs more than a question.

DAY_WORDS: Final = {
    "당일": 0, "전날": 1, "전일": 1, "하루전": 1, "이틀전": 2, "사흘전": 3, "나흘전": 4, "닷새전": 5,
    "열흘전": 10,
    "일주일전": 7, "한주전": 7, "두주전": 14, "세주전": 21, "네주전": 28,
}
DAY: Final = (
    r"(?:당일|전날|전일|(?:하루|이틀|사흘|나흘|닷새|열흘|일주일|(?:한|두|세|네)\s*주)\s*전"
    r"|\d{1,3}\s*(?:일|주일?)\s*전)"
)
DAY_PATTERN: Final = re.compile(DAY)
PERCENT: Final = re.compile(r"(?<![\d.])(\d{1,3})\s*(?:%|퍼센트|프로)")
MINUTES: Final = re.compile(r"(\d{1,3})\s*분")
REFUSED: Final = r"환불\s*(?:은|이|도)?\s*(?:불가능?|없|안\s*[돼되됩]|되지\s*않)"
PLAIN_TEXT: Final = (
    rf"(?:(?:수업|클래스|체험|예약일?)\s*(?:시작\s*)?)?(?P<day>{DAY})\s*(?P<until>까지)?(?:는|은|에는|에)?\s*"
    r"(?:취소\s*(?:는|시|시에는|하면|하시면|하실\s*경우)?)?\s*"
    r"(?:"
    r"(?P<percent>\d{1,3})\s*(?:%|퍼센트|프로)\s*(?:를|을)?\s*(?P<refund>환불)?"
    r"|(?P<material>재료비(?:를)?\s*(?:공제|제외|차감)\s*(?:후|하고)?\s*)?"
    r"(?P<full>전액)\s*(?:을\s*)?환불"
    r"|(?P<half>반액|절반)\s*(?:을\s*)?환불"
    r"|(?P<none>환불\s*(?:은|이|도)?\s*"
    r"(?:불가능?|없음|없어요|없습니다|안\s*돼요|안\s*됩니다|되지\s*않(?:아요|습니다)))"
    r")\s*(?:이고|이며|되고|하고|돼요|됩니다|가능(?:해요|합니다)?|해\s*드려요|해\s*드립니다"
    r"|해요|합니다|이에요|예요|입니다)?"
)
PLAIN: Final = re.compile(PLAIN_TEXT)
FEE: Final = re.compile(r"공제|차감|위약금|수수료|취소료|제외|빼|떼")
DOUBTFUL_TEXT: Final = (
    r"공제|차감|위약금|수수료|취소료|제외|빼|떼|부터|이후|이내|이하|이상|최대|최소|안에|내에|내로|미만|초과|지나|넘"
    r"|영업일|평일|근무일|주말|공휴|시간|변경|이월|연기|단[,\s]|다만|예외|협의|상황|사유|정규|단체"
    r"|회원|수강권|또는"
    r"|[~()\d]\s*원|[~()]|않|못|어렵|어려|\d\s*에서"
)
DOUBTFUL: Final = re.compile(DOUBTFUL_TEXT)
MONEY_TEXT: Final = (
    r"환불|취소|재료비|위약금|수수료|공제|차감|돌려|전액|반액|절반|영업일|평일|근무일|예외|제외|협의|%"
    r"|\d\s*(?:만|천)?\s*원"
)
MONEY: Final = re.compile(MONEY_TEXT)
EXCEPTION: Final = re.compile(r"^(?:단|다만|그러나|하지만|그런데)(?=[\s,])|^(?:단|다만)(?=[가-힣])")
CHANGE: Final = re.compile(r"변경|이월|연기|보강|옮")
JOINED: Final = re.compile(rf"(?<=[고며])\s+(?={DAY})")


def squashed(text: str) -> str:
    """Compare wording without whitespace differences."""
    return re.sub(r"\s+", "", normalize("NFKC", text))


def clauses(source: str) -> list[str]:
    """Split at sentence ends and commas, but never inside a number or a bracket."""
    text = normalize("NFKC", source)
    parts: list[str] = [""]
    depth = 0
    for index, char in enumerate(text):
        depth = max(depth + (char == "(") - (char == ")"), 0)
        around = text[index - 1:index] + text[index + 1:index + 2]
        inside_number = char in ".," and len(around) > 1 and around.isdigit()
        if char in "\n;" or (char in ".,!" and depth == 0 and not inside_number):
            parts.append("")
        else:
            parts[-1] += char
    joined = [piece for part in parts for piece in JOINED.split(part)]
    return [piece.strip()[:MAX_NOTE] for piece in joined if piece.strip()]


def days_of(clause: str) -> list[int]:
    """List every day count a clause names."""
    days: list[int] = []
    for match in DAY_PATTERN.finditer(clause):
        word = squashed(match.expand(r"\g<0>"))
        named = DAY_WORDS.get(word)
        if named is None:
            number = int(re.sub(r"\D", "", word))
            named = number * 7 if "주" in word else number
        days.append(named)
    return [day for day in dict.fromkeys(days) if day <= MAX_DAYS]


def blocking(line: str) -> bool:
    """Tell whether an unread line may change a refund; a rule only about changing dates does not."""
    return MONEY.search(line) is not None or EXCEPTION.search(line) is not None or (
        bool(days_of(line)) and CHANGE.search(line) is None
    )


def plain_rule(clause: str, *, fees: bool) -> Rule | None:
    """Read a clause only when every word of it fits; fees marks text where a bare percent may be a fee."""
    match = PLAIN.fullmatch(clause)
    days = days_of(clause)
    if match is None or len(days) != 1:
        return None
    found = match.groupdict()
    if found["percent"] is not None:
        percent = int(found["percent"])
        if percent > FULL or (fees and found["refund"] is None):
            return None
    else:
        percent = FULL if found["full"] else 50 if found["half"] else 0
    if found["none"] and found["until"] and days[0] > 0:
        return None
    return Rule(
        days_before=days[0], refund_percent=percent, note=clause,
        deduct_material=found["material"] is not None,
    )


def late_of(clause: str) -> LateRule | None:
    """Read a no-show threshold."""
    minutes = [int(match.expand(r"\1")) for match in MINUTES.finditer(clause)]
    if len(minutes) != 1 or not re.search(r"지각|노쇼|늦", clause) or not 1 <= minutes[0] <= MAX_LATE:
        return None
    return LateRule(late_minutes=minutes[0], note=clause)


def shares_of(clause: str) -> set[int]:
    """List every refund share a clause could mean."""
    shares = {int(match.expand(r"\1")) for match in PERCENT.finditer(clause)}
    if "전액" in clause:
        shares.add(FULL)
    if re.search(r"반액|절반|반만", clause):
        shares.add(50)
    if re.search(REFUSED, clause):
        shares.add(0)
    return shares


def supported(rule: Rule, clause: str) -> bool:
    """Accept a model's row only when its whole sentence names that one day and that one share."""
    return (
        rule.refund_percent is not None and DOUBTFUL.search(clause) is None
        and days_of(clause) == [rule.days_before] and shares_of(clause) == {rule.refund_percent}
        and not rule.deduct_material
    )


class Reading:
    """Rows and unread lines gathered clause by clause; any contradiction makes a day undecided."""

    def __init__(self) -> None:
        """Start with nothing read."""
        self.rules: dict[int, Rule] = {}
        self.unread: list[str] = []
        self.late: LateRule | None = None

    def settle(self, rule: Rule) -> None:
        """Add a decided row unless the same day already says something else."""
        known = self.rules.get(rule.days_before)
        if known is None:
            self.rules[rule.days_before] = rule
        elif (known.refund_percent, known.deduct_material) != (rule.refund_percent, rule.deduct_material):
            self.doubt(rule.note or day_label(rule.days_before), [rule.days_before])

    def doubt(self, line: str, days: Iterable[int]) -> None:
        """Keep a line for the owner and take back any number its days had."""
        self.unread.append(line)
        for day in days:
            self.rules[day] = Rule(days_before=day, note=line[:MAX_NOTE])

    def read(self, clause: str, rows: Sequence[Rule], *, fees: bool) -> None:
        """Read one clause with whatever a model said about it."""
        late = late_of(clause)
        if late is not None and not re.search(r"환불|취소|%", clause):
            if self.late is None:
                self.late = late
            elif self.late.late_minutes != late.late_minutes:
                self.unread.append(clause)
            return
        own = plain_rule(clause, fees=fees)
        numbered = [row for row in rows if row.refund_percent is not None]
        if own is not None and all(
            (row.days_before, row.refund_percent) == (own.days_before, own.refund_percent) for row in numbered
        ):
            self.settle(own)
        elif own is None and len(numbered) == 1 and not fees and supported(numbered[0], clause):
            self.settle(numbered[0])
        elif blocking(clause):
            self.doubt(clause, [*days_of(clause), *(row.days_before for row in numbered)])
        elif days_of(clause) or CHANGE.search(clause):
            self.unread.append(clause)

    def finish(self) -> Policy:
        """Order the tiers; a later cancellation that refunds more than an earlier one is a misreading."""
        ordered = sorted(self.rules.values(), key=lambda rule: rule.days_before, reverse=True)
        decided = [rule for rule in ordered if rule.refund_percent is not None]
        for earlier, later in pairwise(decided):
            if (later.refund_percent or 0) > (earlier.refund_percent or 0):
                for rule in (earlier, later):
                    self.doubt(rule.note or day_label(rule.days_before), [rule.days_before])
        ordered = sorted(self.rules.values(), key=lambda rule: rule.days_before, reverse=True)
        return Policy(tuple(ordered), self.late, tuple(dict.fromkeys(self.unread)))


def checked_policy(raw: ExtractedPolicy, source: str) -> Policy:
    """Read every sentence of the source; the model may add a row only where its own sentence supports it."""
    reading = Reading()
    parts = clauses(source)
    fees = any(FEE.search(part) and "재료비" not in part for part in parts)
    used: set[int] = set()
    for part in parts:
        quoted = [
            (index, row) for index, row in enumerate(raw.rules)
            if squashed(row.note) and squashed(row.note) in squashed(part)
        ]
        used.update(index for index, _ in quoted)
        reading.read(part, [row for _, row in quoted], fees=fees)
    for index, row in enumerate(raw.rules):
        if index not in used:
            reading.doubt(row.note.strip() or f"{day_label(row.days_before)} 환불 조건", [row.days_before])
    known = {squashed(part) for part in parts}
    for line in raw.unread:
        if not any(squashed(line) in part for part in known):
            days = days_of(line) if blocking(line) else []
            reading.unread.append(line)
            for day in days:
                _ = reading.rules.setdefault(day, Rule(days_before=day, note=line[:MAX_NOTE]))
    return reading.finish()


def parse_policy(text: str) -> ExtractedPolicy:
    """Read a rule text without a model."""
    policy = checked_policy(ExtractedPolicy(), text)
    return ExtractedPolicy(rules=list(policy.rules), late=policy.late, unread=list(policy.unread))


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
