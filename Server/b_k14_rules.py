"""Plain-text rules for K14: who pays first, kickbacks, people in groups, budgets, and written times."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

# A separator inside a number does not end a clause.
CLAUSE: Final = re.compile(r"[!?\n]+|[.,](?!\d)")
# Nouns that already mean paying ahead; without any verb they still count.
STRONG_PAY: Final = re.compile(r"선\s*입금|선\s*결제|선납(?!품)|대납(?!품)")
# These also appear in ordinary procurement text, so they count only when the owner is asked to act.
WEAK_PAY: Final = re.compile(
    (
        r"선지급|(?:대금|금액|비용|돈|재료비|물품값)[을를은]?\s*먼저\s*보내|"
        r"(?:먼저|미리)\s*[^.]{0,8}?(?:입금|결제|송금|납부|지불|구매|구입|이체)"
        r"(?=\s*[을를]?\s*(?:해|하|부탁|후|주|바랍|바라|요청))"
    ),
)
# Money asked up front under its own name, together with the verb that moves it.
UPFRONT_NAME: Final = (
    r"(?:착수금|계약금|(?:계약|이행|입찰|하자|예치)?\s*보증금|예치금|증거금|공탁금|선금|선수금|예약금|"
    r"등록비|가입비|대행비)"
)
UPFRONT_GAP: Final = (
    r"(?:(?!받|영수|계산서|증빙|서류|증권|보험|견적|청구|면제|반환|환불|문의|관련|상담|설명|여부|안내(?!한|된|드린)|확인|없|필요하)"
    r"[^.\n]){0,20}?"
)
UPFRONT_VERB: Final = (
    r"(?:입금|송금|납부|이체|결제|지불|예치|보내|부쳐|준비|"
    r"(?=내(?:셔|시|야|\s?주)|부탁|바랍|필요(?:합|해|하며)|있어야))"
)
UPFRONT_ASKED: Final = r"[을를은]?\s*(?=해\s*주|주시|주셔|주세|하셔야|하시면|하고\s|요청|요구)"
UPFRONT: Final = re.compile(rf"{UPFRONT_NAME}(?:{UPFRONT_ASKED}|{UPFRONT_GAP}{UPFRONT_VERB})")
# "대신 사용", "대신 사진" and similar nouns are not buying; every other form of 사다 is.
PROXY: Final = re.compile(
    (
        r"대리\s*구매|대신\s*(?:구매|구입|주문|결제|지불|송금|입금|납부|"
        r"사(?![용진람장과무업회전고인실정항]))"
    ),
)
# The workshop named as the one who pays first; with 께 or no particle the verb still decides.
OWNER_NAMED: Final = re.compile(
    r"(?:공방|사장님|선생님|강사님)[^.\n]{0,10}(?:먼저|선)\s*(?:입금|결제|송금|구매)",
)
OWNER_PAYS: Final = re.compile(
    r"(?:공방|사장님|선생님|강사님)(?:이|가|께서|에서|측에서)\s*[^.\n]{0,10}?(?:먼저|미리|선)\s*(?:입금|결제|송금|구매)",
)
DESIGNATED: Final = re.compile(r"지정(?:한|된|해\s*드린)?\s*(?:업체|거래처)")
PAYER: Final = re.compile(
    (
        r"(?:저희|우리|본교|학교|기관|시청|구청|회사|센터|복지관|행정실)\s*(?:쪽|측|학교|회사|기관)?"
        r"(?:에서|가|이)\s*(?:먼저|미리|전액|직접)?\s*$"
    ),
)
PAYER_INSIDE: Final = re.compile(
    (
        r"(?:저희|우리|본교|학교|기관|시청|구청|회사|센터|복지관|행정실)\s*(?:쪽|측|학교|회사|기관)?"
        r"(?:에서|가|이)(?!\s*(?:지정|안내|알려|말씀|드린|요청|정한|보낸))"
    ),
)
DEMAND: Final = re.compile(
    (
        r"\s*[을를은]?\s*(?:다가?|서)?\s*(?:해|하여)?\s*"
        r"(?:요청|부탁|요구|받|바랍|바라|주(?:시|실|셔|세|십)|하(?:시|실|셔|세|십)|이?\s*가능(?:한가|하신|하실))"
    ),
)
NEGATED: Final = re.compile(
    (
        r"[은는이가도]?\s*(?:전혀|따로|별도로?)?\s*(?:없(?!이|으면)|없이(?!.{0,15}(?:어렵|불가|안|못))|"
        r"받지\s*않|안\s*받|필요\s*없|불필요|면제|어렵|힘들|불가|안\s*됩|요구하지\s*않)"
    ),
)
INSURED: Final = re.compile(r".{0,12}(?:보증보험|증권|지급각서|면제)")
ASKS_ACCOUNT: Final = re.compile(
    r"\s*(?:할|용)?\s*(?:계좌|링크|방법)\s*(?:번호)?[를을은]?\s*(?:알려|보내)\s*주",
)
OWNER_ACTS: Final = re.compile(
    (
        r"주시|주실|주셔|주세|주십|(?<!원)하셔|(?<!원)하시|하세|하십|내셔|내시|두시|부탁|바랍|바라|요청|요구|필요|"
        r"가능하신|가능하실"
    ),
)
# Only the verb of the payment itself names the payer; a promise later in the sentence does not.
PAYER_ACTS: Final = re.compile(
    (
        r"\s*[을를은는도]?\s*(?:으로|로)?\s*(?:먼저|미리|바로|전액)?\s*"
        r"(?:해|하|진행|처리|지급|진행해|처리해|지급해)?\s*"
        r"(?:예정|완료했|했습니다|했어요|됐|되었|은?\s*(?:언제|어떻게|어디)|드리|드릴|드립|드려|하?겠|할게|할께|가능(?:합|해요|하며|하고)|받으시|하?고\s*싶)"
    ),
)

MARGIN: Final = re.compile(r"차액|마진")
KICKBACK: Final = re.compile(r"커미션|리베이트|페이백|뒷돈")
KICKBACK_DENIED: Final = re.compile(r"(?:(?!문제)[^.\n]){0,8}?(?:없|안\s*받|받지\s*않|금지)")
REWARD: Final = re.compile(r"(?<!우수\s)사례\s*(?:하겠|할게|해\s*드)")
FEE_OFFER: Final = re.compile(
    (
        r"수수료[를은]?\s*(?:드|지급|챙)|(?:수수료|사례비|사례금|소개비|알선료|중개료)"
        r"(?:(?!안내|관련|연락|문의|여쭤|말씀|확인|계산서|청구|부담|면제|제외|규정|없)[^.\n]){0,15}?"
        r"(?:드리|드려|드릴|드립|드림|드린|드(?=[\s.,]|$)|지급|챙|제공|나눠|돌려|얹|있(?:습니다|어요))"
    ),
)
ORDINARY_FEE: Final = re.compile(
    (
        r"(?:카드|결제|이체|송금|플랫폼|예약|취소|환불|은행|계좌|대관|강사|강의|강연|수업|출강|특강|초청|자문)"
        r"님?(?:께|의)?\s*$"
    ),
)

UNITS: Final = {
    "억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000, "천": 1_000, "백": 100, "": 1,
}
WON: Final = (
    r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|만|천)?(?:(?<=[억만])\s*(\d[\d,]*)\s*(천|백)?)?"
    r"\s*(?:원|(?<=[억만천백]))"
)
MONEY: Final = re.compile(WON)
TOTAL_BUDGET: Final = re.compile(rf"(?:예산|금액|총액)\D{{0,10}}{WON}")
EACH: Final = (
    r"(?:(?<!\d)1\s*(?:인|명)|(?<![\d가-힣])(?:인|명|인원|개인)|한\s*(?:명|사람|분)|학생|참가자|참여자)"
    r"\s*(?:당|별|마다|기준)"
)
PER_PERSON: Final = re.compile(
    (
        rf"{EACH}(?P<what>[^\d.\n,]{{0,12}}){WON}|"
        rf"(?<!\d)1\s*인\s*(?:예산|금액|단가|비용|수강료|참가비)?\s*[은는이:]?\s*(?:약\s*)?{WON}|"
        rf"{WON}\s*(?:/\s*1?\s*(?:인|명)|\(\s*(?:1\s*)?인당?\s*\))"
    ),
)
PER_PERSON_RANGE: Final = re.compile(rf"{EACH}[^\d.\n,]{{0,12}}\d[\d,]*\s*[만천]?\s*원?\s*[~-]\s*\d")
# Group 1 is the words between; each alternative then captures the four parts of its amount.
PRICE_GROUPS: Final = range(2, 14)
NOT_A_BUDGET: Final = re.compile(r"(?:재료|교재|간식|식비|다과|기념품)(?!.*포함)")
NOT_A_BUDGET_BEFORE: Final = re.compile(r"(?:재료비?|교재비?|간식비?|식비|다과비?|기념품)[은는이가]?\s*$")

# Each payment wording, and whether it counts without a verb that asks the owner.
PAY_PATTERNS: Final = ((STRONG_PAY, True), (OWNER_NAMED, True), (UPFRONT, True), (WEAK_PAY, False))

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
PEOPLE: Final = re.compile(r"(\d+)\s*(?:명\s*)?(?:[~-]\s*(\d+)\s*)?명(?!\s*(?:당|별|마다))")

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


@dataclass(frozen=True, slots=True)
class Budget:
    """Money stated in the text; a per-person price is never the total by itself."""

    total: int | None
    per_person: bool
    consistent: bool
    other_amounts: frozenset[int]


def asks_owner(clause: str, match: re.Match[str], *, by_default: bool) -> bool:
    """Tell whether this pay-ahead wording asks the workshop, not the institution, to pay."""
    before, after = clause[:match.start()], clause[match.end():]
    if NEGATED.match(after) or ASKS_ACCOUNT.match(after):
        return False
    if "보증금" in match.group() and INSURED.match(after):
        return False
    paid_by_them = PAYER.search(before) or PAYER_INSIDE.search(match.group())
    if paid_by_them and not DEMAND.match(after):
        return False
    if PAYER_ACTS.match(after):
        return False
    return by_default or OWNER_ACTS.search(after) is not None


def owner_pays_first(text: str) -> bool:
    """Find a demand that the workshop pays before it is paid."""
    return OWNER_PAYS.search(text) is not None or any(
        asks_owner(clause, match, by_default=by_default)
        for clause in CLAUSE.split(text)
        for pattern, by_default in PAY_PATTERNS
        for match in pattern.finditer(clause)
    )


def owner_buys_for_them(text: str) -> bool:
    """Find a request to buy goods on the institution's behalf."""
    return DESIGNATED.search(text) is not None or any(
        asks_owner(clause, match, by_default=True)
        for clause in CLAUSE.split(text)
        for match in PROXY.finditer(clause)
    )


def offers_margin(text: str) -> bool:
    """Find a kickback: a fee handed to the workshop, not an ordinary charge or the instructor's own pay."""
    if MARGIN.search(text) or REWARD.search(text):
        return True
    return any(
        KICKBACK_DENIED.match(text[match.end():]) is None for match in KICKBACK.finditer(text)
    ) or any(
        ORDINARY_FEE.search(text[:match.start()]) is None for match in FEE_OFFER.finditer(text)
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


def won_of(groups: Sequence[str | None]) -> int:
    """Add up one amount such as 3만 5천, given its four captured parts."""
    value, unit, value2, unit2 = groups
    amount = float((value or "0").replace(",", "")) * UNITS[unit or ""]
    return round(amount + float((value2 or "0").replace(",", "")) * UNITS[unit2 or ""])


def amounts_in(text: str) -> set[int]:
    """Collect every written amount of money."""
    return {won_of(match.groups()) for match in MONEY.finditer(text)}


def budget_in(text: str) -> Budget:
    """Separate a total budget from per-person prices, multiplying only with a certain headcount."""
    prices: set[int] = set()
    others: set[int] = set()
    spans: list[tuple[int, int]] = []
    for match in PER_PERSON.finditer(text):
        groups = [match.group(index) for index in PRICE_GROUPS]
        price = next(
            won_of(groups[start:start + 4]) for start in range(0, len(groups), 4) if groups[start] is not None
        )
        spans.append(match.span())
        extra = NOT_A_BUDGET.search(match.group("what") or "") or NOT_A_BUDGET_BEFORE.search(
            text[:match.start()],
        )
        (others if extra else prices).add(price)
    per_person = bool(prices) or PER_PERSON_RANGE.search(text) is not None
    total = next(
        (
            won_of(match.groups()) for match in TOTAL_BUDGET.finditer(text)
            if not any(match.start() < end and start < match.end() for start, end in spans)
        ),
        None,
    )
    people = people_in(text)
    product = None
    if len(prices) == 1 and not PER_PERSON_RANGE.search(text) and people.low and people.low == people.high:
        product = next(iter(prices)) * people.low
    return Budget(
        total=product if total is None else total, per_person=per_person,
        consistent=total is None or product is None or product == total, other_amounts=frozenset(others),
    )


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
