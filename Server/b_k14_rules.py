"""Plain-text rules for K14: who pays first, how many people in groups, and a written time range."""

import re
from dataclasses import dataclass
from typing import Final

CLAUSE: Final = re.compile(r"[.!?\n,]+")
# Nouns that already mean paying ahead; without any verb they still count.
STRONG_PAY: Final = re.compile(r"선입금|선결제|선납(?!품)|대납(?!품)")
# These also appear in ordinary procurement text, so they count only when the owner is asked to act.
WEAK_PAY: Final = re.compile(
    (
        r"선지급|(?:계약|이행|입찰|하자|예치)?\s*보증금|예치금|"
        r"(?:계약금|예약금|대금|금액|비용|돈)[을를은]?\s*먼저\s*보내|"
        r"(?:먼저|미리)\s*[^.]{0,8}?(?:입금|결제|송금|납부|지불|구매|구입|이체)"
        r"(?=\s*[을를]?\s*(?:해|하|부탁|후|주|바랍|바라|요청))"
    ),
)
PROXY: Final = re.compile(r"대리\s*구매|대신\s*(?:구매|구입|주문|사\s*(?:주|달))")
DESIGNATED: Final = re.compile(r"지정(?:한|된|해\s*드린)?\s*(?:업체|거래처)")
PAYER: Final = re.compile(
    (
        r"(?:저희|우리|본교|학교|기관|시청|구청|회사|센터|복지관|행정실)\s*(?:쪽|측|학교|회사|기관)?"
        r"(?:에서|가|이)\s*(?:먼저|미리|전액|직접)?\s*$"
    ),
)
DEMAND: Final = re.compile(r"\s*[을를은]?\s*(?:요청|부탁|요구|받|해?\s*주(?:시|셔|세|십))")
NEGATED: Final = re.compile(
    (
        r"[은는이가도]?\s*(?:전혀|따로|별도로?)?\s*(?:없(?!이|으면)|없이(?!.{0,15}(?:어렵|불가|안|못))|"
        r"받지\s*않|안\s*받|필요\s*없|불필요|면제|어렵|힘들|불가|안\s*됩|요구하지\s*않)"
    ),
)
INSURED: Final = re.compile(r".{0,12}(?:보증보험|증권|지급각서|면제)")
ASKS_ACCOUNT: Final = re.compile(r"\s*(?:할|용)?\s*계좌\s*(?:번호)?[를은]?\s*(?:알려|보내)\s*주")
OWNER_ACTS: Final = re.compile(
    (
        r"주시|주셔|주세|주십|(?<!원)하셔|(?<!원)하시|하세|하십|내셔|내시|두시|부탁|바랍|바라|요청|요구|필요|"
        r"가능하신|가능하실"
    ),
)
PAYER_ACTS: Final = re.compile(r"드리|드릴|드립|드려|하겠|할게|할께|가능|받으시|되나|될까|싶")

KOREAN_COUNTS: Final = {
    "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
}
UNIT: Final = r"(?:반|팀|조(?!원)|회차|회(?![가-힣]|의)|회(?=당|별|마다|로|에|씩)|학급|그룹|모둠)"
GROUPS: Final = re.compile(
    rf"(?<![가-힣\d])(?:(\d{{1,2}})\s*(?:개\s*)?|({'|'.join(KOREAN_COUNTS)})\s*(?:개\s*)?){UNIT}(?!\s*(?:당|별|마다))",
)
CLASS_NAME: Final = re.compile(r"학년\s*\d{1,2}\s*반")
AMOUNT: Final = r"(?:약|최대|대략)?\s*(\d+)\s*(?:명\s*)?(?:[~-]\s*(\d+)\s*)?명"
PER_GROUP: Final = re.compile(
    (
        rf"(?:각각|각\s*(?:반|팀|조|회차|학급)?(?:에)?|{UNIT}\s*(?:당|별|마다)(?:로)?|"
        rf"한\s*{UNIT}(?:에|에는|은)?)\s*{AMOUNT}|"
        r"(\d+)\s*(?:[~-]\s*(\d+)\s*)?명\s*씩"
    ),
)
TOTAL: Final = re.compile(
    r"(?:총|모두|합계|전체|총인원|합쳐서?)\s*(?:인원)?[은는]?\s*(?:약\s*)?(\d+)\s*(?:[~-]\s*(\d+)\s*)?명(?!\s*씩)",
)
PEOPLE: Final = re.compile(r"(\d+)\s*(?:명\s*)?(?:[~-]\s*(\d+)\s*)?명")

HALF_DAY: Final = r"(오전|오후|낮|저녁)?\s*"
MINUTES: Final = r"(?::([0-5]\d)|\s*시(?!간)(?:\s*([0-5]?\d)\s*분|\s*(반))?)"
TIMES: Final = re.compile(
    (
        rf"(?<!\d){HALF_DAY}(\d{{1,2}}){MINUTES}?\s*(?:부터|에서|[~-]|\u301c|\uff5e)\s*"
        rf"{HALF_DAY}(\d{{1,2}}){MINUTES}"
    ),
)
NOON: Final = 12
LAST_HOUR: Final = 23
EARLIEST_PLAIN_HOUR: Final = 8
HALF: Final = 30


@dataclass(frozen=True, slots=True)
class People:
    """People stated in the text; `grouped` means per-group wording decides, even when it stays unknown."""

    low: int | None
    high: int | None
    grouped: bool


def asks_owner(clause: str, match: re.Match[str], *, by_default: bool) -> bool:
    """Tell whether this pay-ahead wording asks the workshop, not the institution, to pay."""
    before, after = clause[:match.start()], clause[match.end():]
    if NEGATED.match(after) or ASKS_ACCOUNT.match(after):
        return False
    if "보증금" in match.group() and INSURED.match(after):
        return False
    if PAYER.search(before) and not DEMAND.match(after):
        return False
    owner, payer = OWNER_ACTS.search(after), PAYER_ACTS.search(after)
    if owner is not None:
        return payer is None or owner.start() <= payer.start()
    return by_default and payer is None


def owner_pays_first(text: str) -> bool:
    """Find a demand that the workshop pays before it is paid."""
    return any(
        asks_owner(clause, match, by_default=by_default)
        for clause in CLAUSE.split(text)
        for pattern, by_default in ((STRONG_PAY, True), (WEAK_PAY, False))
        for match in pattern.finditer(clause)
    )


def owner_buys_for_them(text: str) -> bool:
    """Find a request to buy goods on the institution's behalf."""
    return DESIGNATED.search(text) is not None or any(
        asks_owner(clause, match, by_default=True)
        for clause in CLAUSE.split(text)
        for match in PROXY.finditer(clause)
    )


def group_count(text: str) -> int | None:
    """Return the number of groups only when the text states exactly one count."""
    found = list(GROUPS.finditer(CLASS_NAME.sub(" ", text)))
    if len(found) != 1:
        return None
    digits, word = found[0].groups()
    return int(digits) if digits else KOREAN_COUNTS[word]


def bounds(low: str, high: str | None) -> tuple[int, int]:
    """Read one number or a range in ascending order."""
    first, second = int(low), int(high or low)
    return min(first, second), max(first, second)


def people_in(text: str) -> People:
    """Multiply groups by people per group, and leave an unclear headcount to the owner."""
    per_group = list(PER_GROUP.finditer(text))
    grouped = bool(per_group) or GROUPS.search(CLASS_NAME.sub(" ", text)) is not None
    total = TOTAL.search(text)
    if total is not None:
        low, high = bounds(total.expand(r"\1"), total.expand(r"\2") or None)
        return People(low, high, grouped)
    if grouped:
        count = group_count(text)
        if len(per_group) != 1 or count is None:
            return People(None, None, grouped=True)
        first, last, each, each_last = per_group[0].groups()
        low, high = bounds(first or each, last or each_last)
        return People(low * count, high * count, grouped=True)
    stated = {bounds(match.expand(r"\1"), match.expand(r"\2") or None) for match in PEOPLE.finditer(text)}
    if len(stated) != 1:
        return People(None, None, grouped=False)
    low, high = stated.pop()
    return People(low or None, high or None, grouped=False)


def hour_of(half_day: str, hour: int) -> int:
    """Turn a 12-hour reading into a 24-hour one."""
    if half_day in {"오후", "낮", "저녁"} and hour < NOON:
        return hour + NOON
    return hour


def written_time_range(text: str) -> str | None:
    """Read one start and end time; an hour that could be morning or afternoon stays unread."""
    for match in TIMES.finditer(text):
        half, hour, colon, minute, halfway, half2, hour2, colon2, minute2, halfway2 = match.groups()
        start_half, end_half = half or "", half2 or half or ""
        start, end = hour_of(start_half, int(hour)), hour_of(end_half, int(hour2))
        if not start_half and start < EARLIEST_PLAIN_HOUR:
            continue
        first = start * 60 + int(colon or minute or (HALF if halfway else 0))
        last = end * 60 + int(colon2 or minute2 or (HALF if halfway2 else 0))
        if last <= first and not half2 and not colon2 and int(hour2) < NOON:
            last = (int(hour2) + NOON) * 60 + last % 60
        if first < last and max(start, last // 60) <= LAST_HOUR:
            return f"{first // 60:02}:{first % 60:02}-{last // 60:02}:{last % 60:02}"
    return None
