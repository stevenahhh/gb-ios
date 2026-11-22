"""Read the numbers a Korean reply states: amounts, days, times, seats, lengths, and people.

Only regular expressions over the text itself; b_k25_claims decides whether a number is right.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Literal

type AmountRole = Literal["each", "total", "any"]
type Topic = Literal["parking", "refund", "materials", "discount"]
type Quantity = tuple[str, float]

HOUR_MINUTES: Final = 60
DAY_MINUTES: Final = 1440
NOON: Final = 12
WEEKDAYS: Final = "월화수목금토일"

SINO: Final[dict[str, int]] = {
    "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9,
}
SINO_UNITS: Final[dict[str, int]] = {"십": 10, "백": 100, "천": 1_000}
NATIVE_ONES: Final[dict[str, int]] = {
    "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9,
}
NATIVE_TENS: Final[dict[str, int]] = {"열": 10, "스물": 20, "서른": 30, "마흔": 40, "쉰": 50}
NATIVE_COUNTS: Final[dict[str, int]] = {
    **NATIVE_ONES, **NATIVE_TENS, "스무": 20,
    **{ten + one: tens + ones for ten, tens in NATIVE_TENS.items() for one, ones in NATIVE_ONES.items()},
}
NATIVE: Final = "|".join(sorted(NATIVE_COUNTS, key=len, reverse=True))
DAY_WORDS: Final[dict[str, int]] = {
    "당일": 0, "전날": 1, "하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6,
    "일주일": 7, "열흘": 10, "보름": 15,
}

# A number in digits must not start inside another one, and a number word not inside another word.
DIGIT: Final = r"(?<!\d)(?<!\d[.,])"
WORD: Final = r"(?<![가-힣])"
SINO_ONE: Final = "[일이삼사오육칠팔구]"
SINO_TENS: Final = f"{SINO_ONE}?십{SINO_ONE}?"
SINO_MINUTES: Final = f"(?:{SINO_ONE}?백)?{SINO_TENS}|{SINO_ONE}?백"
COUNT: Final = rf"(?:{DIGIT}\d{{1,3}}|{WORD}(?:{NATIVE}|{SINO_TENS}))"
HOURS: Final = rf"(?:{DIGIT}\d{{1,2}}(?:\.\d+)?|{WORD}(?:{NATIVE}))"
MINUTES: Final = rf"(?:{DIGIT}\d{{1,3}}|{WORD}(?:{SINO_MINUTES}))"

SENTENCE_BREAK: Final = re.compile(r"[!?\n]+|\.(?!\d)")
CLAUSE_BREAK: Final = re.compile(
    r"[!?\n;]+|\.(?!\d)|,(?!\d{3})|(?<=[가-힣])(?:고|며|(?<!까)지만|는데|은데|인데|니까|거나)(?=\s)",
)
DENIAL: Final = (
    r"\s*(?:까지|이상|정도)?(?:은|는|이|가|도|에|에는|엔|에도|으로|로)?\s*"
    r"(?:(?:수업|클래스|타임|회차|예약|참여|신청|참가|자리|좌석|진행|운영|시작)"
    r"(?:은|는|이|가|도|을|를|에는|에)?\s*){0,2}"
    r"(?:(?:받|모시|진행하|참여하|예약하|오)기(?:는|가)?\s*"
    r"|(?:받을|모실|오실|참여하실|참여할|예약하실|예약할|하실|할)\s*수(?:는|가)?\s*)?"
    r"(?:어려|어렵|힘들|불가|없(?!이)|안\s*(?:돼|되|됩|열|해)|못\s*|마감|휴무|쉬[어는고]|쉽니다|아니|아닌)"
)
DENIED: Final = re.compile(DENIAL)

DIGITS: Final = r"\d{1,3}(?:,\d{3})+|\d+"
WON: Final = r"원(?!데이|형|칙)|(?:won|KRW)(?![A-Za-z])"
AMOUNT_TAIL: Final = (
    r"(?=\s*(?:이에요|예요|입니다|이고|이며|인데|이니|이라|이면|씩|정도|까지|부터|~|[,.!?)\n]|$))"
)
AMOUNT: Final = re.compile(
    (
        rf"(?:₩|\uffe6|\bKRW)\s*(?P<symbol>{DIGITS})"
        rf"|{DIGIT}(?P<kilo>\d{{2,3}}(?:\.\d)?)\s*[kK](?![A-Za-z0-9])"
        rf"|{DIGIT}(?P<plain>{DIGITS})\s*(?:{WON})"
        rf"|(?:{DIGIT}(?=\d)|{WORD}(?=[일이삼사오육칠팔구십백천만]))"
        r"(?:(?P<man>\d+(?:\.\d+)?|[일이삼사오육칠팔구십백]+)?\s*(?P<has_man>만)\s*)?"
        rf"(?:(?P<cheon>\d{{1,3}}|{SINO_ONE})?\s*(?P<has_cheon>천)\s*)?"
        rf"(?:(?P<baek>\d|{SINO_ONE})?\s*(?P<has_baek>백)\s*)?"
        rf"(?P<rest>\d,\d{{3}}|\d{{1,4}})?\s*(?P<unit>{WON}|{AMOUNT_TAIL})"
    ),
)
PRICE_NOUN: Final = "수업료|참가비|체험비|강습료|수강료|가격|비용|요금|금액|단가"
PRICE_CALLED: Final = re.compile(PRICE_NOUN)
BALANCE_CALLED: Final = re.compile(r"나머지|잔금|잔액|남은\s*금액")
DEPOSIT_BEFORE: Final = re.compile(
    r"(?:예약금|보증금|계약금)(?![^.\n]{0,12}(?:없|포함|빼|제외))[^.\n]{0,12}$",
)
DEPOSIT_AFTER: Final = re.compile(r"^\s*(?:을|를|이|가|은|는|으로|로)?\s*(?:예약금|보증금|계약금)")
EACH_BEFORE: Final = re.compile(
    (
        rf"(?:{DIGIT}1\s*(?:인|명|분|사람)|{WORD}한\s*(?:명|분|사람)|인당|명당|분당|각각|각자)"
        rf"(?:\s*(?:당|마다|기준|에))?\s*(?:{PRICE_NOUN})?(?:은|는|이|가|에|:)?\s*$"
    ),
)
EACH_AFTER: Final = re.compile(r"^\s*(?:씩|/\s*1?\s*(?:인|명))")
TOTAL_BEFORE: Final = re.compile(
    (
        r"(?:총|총액|합계|합쳐서?|합해서?|다\s*해서|도합)\s*"
        rf"(?:{PRICE_NOUN})?(?:은|는|이|가|:)?\s*$"
    ),
)
GROUP_BEFORE: Final = re.compile(
    (
        rf"(?P<n>{COUNT})\s*(?P<unit>명|분|인|사람|자리|석)\s*"
        r"(?:께서|이서|이\s*(?:오|함께\s*하|참여하)시면|이시면|이면|이라면|시면|기준|은|는|이|의)?\s*"
        rf"(?:{PRICE_NOUN})?(?:은|는|이|가|:)?\s*$"
    ),
)
PEOPLE: Final = re.compile(
    (
        rf"(?P<n>{COUNT})\s*(?P<unit>명|사람|인(?!분)|분(?!\s*(?:간|동안|정도|거리|전|후|뒤|이내|단위|마다)))"
        r"(?!\s*당)"
    ),
)
PEOPLE_WORDS: Final[dict[str, int]] = {"혼자": 1, "둘": 2, "셋": 3, "넷": 4}
PEOPLE_WORD: Final = re.compile(rf"{WORD}(?P<word>혼자|둘|셋|넷)(?=이|서|은|끼리|[\s,.])")
LOOK_BACK: Final = 30
LOOK_AHEAD: Final = 12

DATE: Final = re.compile(
    (
        rf"{DIGIT}(?P<m1>\d{{1,2}})\s*월\s*(?P<d1>\d{{1,2}})\s*일(?:\s*\(?(?P<w1>[{WEEKDAYS}])(?:요일|\)))?"
        r"|(?<![\d/.])(?P<m2>1[0-2]|0?[1-9])/(?P<d2>3[01]|[12]\d|0?[1-9])(?![\d/])"
        rf"(?:\s*\(?(?P<w2>[{WEEKDAYS}])(?:요일|\)))?"
        r"|(?<!\d)20\d{2}\s?[-./]\s?(?P<m3>1[0-2]|0?[1-9])\s?[-./]\s?(?P<d3>3[01]|[12]\d|0?[1-9])(?!\d)"
        rf"(?:\s*\(?(?P<w3>[{WEEKDAYS}])(?:요일|\)))?"
        rf"|{DIGIT}(?P<d4>3[01]|[12]?\d)\s*일\s*\(?(?P<w4>[{WEEKDAYS}])(?:요일|\))"
        rf"|(?<![\d.])(?P<m5>1[0-2]|0?[1-9])\.\s?(?P<d5>3[01]|[12]\d|0?[1-9])\s*\((?P<w5>[{WEEKDAYS}])\)"
    ),
)
WEEKDAY: Final = re.compile(rf"(?:(?P<when>다음\s*주|이번\s*주)\s*)?(?P<day>[{WEEKDAYS}])요일")
RELATIVE_DAYS: Final = (("오늘", 0), ("내일", 1), ("모레", 2))
PAST_DAYS: Final = 3
DAY_ONLY_RANGE: Final = 62

HOUR_WORDS: Final = "열한|열두|열|한|두|세|네|다섯|여섯|일곱|여덟|아홉"
TIME: Final = re.compile(
    (
        r"(?:(?P<mark>오전|오후|아침|낮|점심|저녁|밤|새벽|[AaPp]\.?[Mm]\.?)\s*)?"
        rf"(?:{DIGIT}(?P<h1>[01]?\d|2[0-4])\s*:\s*(?P<m1>[0-5]\d)(?![\d:])"
        rf"|(?:{DIGIT}(?P<h2>[01]?\d|2[0-4])|{WORD}(?P<h3>{HOUR_WORDS}))\s*시"
        r"(?=[에부까쯤경반이예입로와과나은는가도정\d\s,.!?~)\-]|$)"
        rf"(?:\s*(?P<m2>[0-5]?\d|{SINO_MINUTES})\s*분(?!\s*(?:전|후|뒤))"
        r"|\s*(?P<half>반)(?=에|부터|까지|이|쯤|경|으로|[\s,.!?~)]|$))?"
        rf"|{DIGIT}(?P<h4>1[0-2]|0?[1-9])(?=\s*[AaPp]\.?[Mm]\.?(?![A-Za-z]))"
        r"|(?P<noon>정오)|(?P<midnight>자정))"
        r"(?:\s*(?P<mark2>[AaPp]\.?[Mm]\.?)(?![A-Za-z]))?"
    ),
)
MORNING: Final = frozenset({"오전", "아침", "새벽", "am"})
MIDDAY: Final = frozenset({"낮", "점심"})

CAPACITY: Final = re.compile(
    (
        r"(?P<prefix>(?:정원|최대\s*인원|모집\s*인원)\s*(?:은|는|이|가|:)?\s*(?:최대\s*|총\s*)?)"
        rf"(?P<n>{COUNT})\s*(?P<unit>명)"
        r"|(?P<prefix2>한\s*(?:회차|회|타임|수업|클래스)(?:에|당)?\s*(?:최대\s*)?)"
        rf"(?P<n2>{COUNT})\s*(?P<unit2>명|분)"
    ),
)
OPEN_FILLER: Final = (
    r"(?:까지|도|이서|이|은|는|만|을|를)?\s*"
    r"(?:(?:더|모두|다|함께|같이|정도|추가로|추가|바로|지금|아직|동시에|한\s*번에|한꺼번에)\s*)*"
)
OPEN: Final = (
    r"(?:(?:예약|신청|참여|참가|수강|등록|접수|입장|방문|체험|수업)(?:이|가|을|를|도|은|는)?\s*)?"
    r"(?:가능(?!성|한지|할지|하신지|하실지|하실까|할까|한가|하신가|\s*여부|한\s)"
    r"|받을\s*수\s*있|받아요|받습니다|받고\s*있|돼요|됩니다|되세요"
    r"|(?:하실|할|오실|올|모실|들어오실|들어올|앉으실|함께하실)\s*수\s*있|자리(?:가)?\s*있|여유(?:가)?\s*있)"
)
PEOPLE_UNIT: Final = "명|분|인|사람"
SEATS_LEFT: Final = re.compile(
    (
        r"(?P<prefix>(?:남은|잔여|빈)\s*(?:자리|좌석|인원)?\s*(?:이|가|은|는|:)?\s*)"
        rf"(?P<n>{COUNT})\s*(?P<unit>자리|석|명|분|개)"
    ),
)
PEOPLE_LEFT: Final = re.compile(
    (
        rf"(?P<n>{COUNT})\s*(?P<unit>{PEOPLE_UNIT})"
        r"(?=\s*(?:정도|만)?\s*(?:이|가)?\s*(?:자리(?:가|는)?\s*)?(?:더\s*)?(?:남[았아은]|비어|여유))"
    ),
)
SEATS: Final = re.compile(rf"(?P<n>{COUNT})\s*(?P<unit>자리|석)(?!\s*당)")
PEOPLE_OPEN: Final = re.compile(
    rf"(?P<limit>최대\s*)?(?P<n>{COUNT})\s*(?P<unit>{PEOPLE_UNIT})(?={OPEN_FILLER}{OPEN})",
)
PEOPLE_DENIED: Final = re.compile(rf"(?P<n>{COUNT})\s*(?P<unit>{PEOPLE_UNIT})(?={DENIAL})")
EXACT_TAIL: Final = re.compile(r"^\s*(?:이|가|은|는|만)?\s*(?:정도)?\s*(?:남|밖에|뿐)")

LENGTH: Final = re.compile(
    (
        rf"(?:(?:{DIGIT}(?P<low>\d{{1,2}}(?:\.\d)?)\s*(?:[~\u223c\uff5e\u2013-]|에서)\s*)?(?P<h>{HOURS}|\d{{1,2}})\s*시간(?!표|대)"
        rf"(?:\s*(?P<half>반)(?=이|정|동|[\s,.!?]|$)|\s*(?P<m>{MINUTES})\s*분)?"
        rf"|(?P<only>{MINUTES})\s*분"
        r"|(?P<word>반나절|하루\s*종일|온종일))"
        r"(?!\s*(?:전|후|뒤|이내|안|단위|마다|간격|씩|당|거리|일찍|늦|(?:은|는|까지|동안)?\s*[무유]료))"
    ),
)
LENGTH_WORDS: Final[dict[str, tuple[int, int]]] = {
    "반나절": (180, 360), "하루종일": (360, DAY_MINUTES), "온종일": (360, DAY_MINUTES),
}
TOTAL_LENGTH: Final = re.compile(r"총\s*$")
CLASS_LENGTH: Final = re.compile(r"수업|클래스|체험|과정|코스|진행|소요|걸리|걸려")
OTHER_ACTIVITY: Final = re.compile(
    r"상담|휴식|쉬는|대기|이동|설명|준비\s*시간|도보|걸어|거리|버스|지하철|택시|차로|건조|소성|굽",
)
MIN_CLASS_MINUTES: Final = 30
HALF: Final = 30

TOPIC_WORDS: Final[dict[Topic, re.Pattern[str]]] = {
    "parking": re.compile(r"주차|차(?:는|를|도)?\s[^.,!?\n]{0,14}(?:대실|대셔|대시|세우|세워)"),
    "refund": re.compile(r"환불|취소|위약|변경|일정을\s*바[꾸꿀]|돌려\s*[드받]"),
    "materials": re.compile(r"재료|준비물|앞치마|도구|점토|유약|물감"),
    "discount": re.compile(r"할인|세일"),
}
# A sentence that only says 2시간 무료예요 continues the topic of the sentence before it.
TOPIC_HINTS: Final[dict[Topic, re.Pattern[str]]] = {
    "parking": re.compile(r"무료|유료|요금"),
    "refund": re.compile(r"전액|돌려|수수료|공제"),
    "materials": re.compile(r"제공|포함"),
    "discount": re.compile(r"깎아"),
}
CLASS_WORDS: Final = re.compile(
    r"수업|클래스|체험|과정|코스|진행|소요|걸리|걸려|자리|좌석|정원|예약|가격|수업료",
)
CLASS_BEFORE: Final = re.compile(
    r"(?:(?:수업|클래스|체험|과정|코스)(?:\s*시간)?|소요\s*시간)(?:은|는|이|가|:)\s*(?:총|약|대략)?\s*$",
)
CLASS_AFTER: Final = re.compile(r"^\s*(?:짜리\s*|동안의?\s*)?(?:수업|클래스|체험|과정|코스|원데이)")
QUANTITY_HOURS: Final = rf"(?P<hours>{HOURS})\s*시간(?:\s*(?P<half>반)(?![가-힣])|\s*(?P<m>{MINUTES})\s*분)?"
QUANTITY_MINUTES: Final = rf"(?P<minutes>{MINUTES})\s*분"
QUANTITY_DAYS: Final = (
    rf"{WORD}(?P<word>{'|'.join(DAY_WORDS)})|{DIGIT}(?P<days>\d{{1,3}})\s*일(?!정|반|상|부|요)"
    rf"|(?P<weeks>{DIGIT}\d{{1,2}}|{WORD}(?:[한두세네일이삼사]))\s*주(?:일)?(?!차|말|문|의|중|로|소|인|년|민|변|요)"
)
QUANTITY_MONTHS: Final = rf"(?P<months>{DIGIT}\d{{1,2}}|{WORD}[한두세네])\s*(?:개월|달)(?!력|라)"
QUANTITY_PERCENT: Final = (
    rf"{DIGIT}(?P<percent>\d{{1,3}}(?:\.\d+)?)\s*(?:%|퍼센트|프로(?![가-힣]))|(?P<part>절반|반액)"
)
PIECES: Final = (
    "개(?!월)|장(?!소)|벌|세트|가지|종|점(?!토|심|검)|켤레|병|봉지|통|자루"
    "|kg|킬로(?:그램)?|g(?![A-Za-z])|그램|ml|리터|cm"
)
QUANTITIES: Final[dict[Topic, re.Pattern[str]]] = {
    "parking": re.compile(
        (
            rf"{QUANTITY_HOURS}|{QUANTITY_MINUTES}|{QUANTITY_DAYS}"
            rf"|(?P<piece>{HOURS})\s*(?P<unit>대(?![가-힣])|층)"
        ),
    ),
    "refund": re.compile(rf"{QUANTITY_HOURS}|{QUANTITY_DAYS}|{QUANTITY_MONTHS}|{QUANTITY_PERCENT}"),
    "discount": re.compile(QUANTITY_PERCENT),
    "materials": re.compile(
        rf"(?P<piece>{DIGIT}\d+(?:\.\d+)?|{WORD}(?:{NATIVE}))\s*(?P<unit>{PIECES})",
    ),
}
QUANTITY_UNITS: Final = (
    ("minutes", "분", 1), ("days", "일", 1), ("weeks", "일", 7), ("months", "개월", 1), ("percent", "%", 1),
)
UNIT_NAMES: Final[dict[str, str]] = {"킬로": "kg", "킬로그램": "kg", "그램": "g"}
REFUND_DENIED: Final = re.compile(
    (
        r"(?:환불|취소|변경|반환|돌려)(?:(?!위약|수수료|부담|비용|문제|걱정|제한)[^.,!?\n]){0,14}?"
        r"(?:어려|어렵|힘들|불가|안\s*(?:돼|되|됩)|못\s*|없(?!이))|불가"
    ),
)
TOPIC_DENIED: Final = re.compile(r"어려|어렵|힘들|불가|안\s*(?:돼|되|됩)|없(?!이)|아니|아닌")


@dataclass(frozen=True, slots=True)
class Span:
    """A piece of text that states a number."""

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class AmountSpan(Span):
    """A won amount, whether the text calls it a deposit, the rest after one, or a price, and for whom."""

    won: int = 0
    is_deposit: bool = False
    is_balance: bool = False
    is_price: bool = False
    role: AmountRole = "any"


@dataclass(frozen=True, slots=True)
class NumberSpan(Span):
    """A whole number of seats or people, and what the text says about it."""

    value: int = 0
    exact: bool = False
    is_limit: bool = False
    denied: bool = False
    prefix: str = ""
    unit: str = ""

    def with_value(self, value: int) -> str:
        """Put another number into the same words."""
        return f"{self.prefix}{value}{self.unit}"


@dataclass(frozen=True, slots=True)
class DateSpan(Span):
    """A written day; no month means the day stands with its weekday alone."""

    month: int = 0
    day: int = 0
    weekday: str = ""
    denied: bool = False

    def names(self, day: date) -> bool:
        """Tell whether the numbers of this date fit a day, whatever its weekday."""
        return self.day == day.day and self.month in {0, day.month}


@dataclass(frozen=True, slots=True)
class WeekdaySpan(Span):
    """A weekday without a written date, and the week when the text names one."""

    weekday: str = ""
    when: str = ""


@dataclass(frozen=True, slots=True)
class TimeSpan(Span):
    """A time of day as every minute of the day it can mean; 2시 can be two of them."""

    minutes: frozenset[int] = frozenset()
    is_clock: bool = False
    denied: bool = False


@dataclass(frozen=True, slots=True)
class LengthSpan(Span):
    """A class length in minutes; words such as 반나절 cover a range."""

    low: int = 0
    high: int = 0
    in_hours: bool = False


@dataclass(frozen=True, slots=True)
class TopicSpan(Span):
    """A quantity in a sentence about parking, refunds, or materials."""

    topic: Topic = "refund"
    values: frozenset[Quantity] = frozenset()
    denied: bool = False


@dataclass(frozen=True, slots=True)
class Reading:
    """Every number found in one text."""

    amounts: tuple[AmountSpan, ...]
    dates: tuple[DateSpan, ...]
    weekdays: tuple[WeekdaySpan, ...]
    times: tuple[TimeSpan, ...]
    seats: tuple[NumberSpan, ...]
    capacities: tuple[NumberSpan, ...]
    lengths: tuple[LengthSpan, ...]
    topics: tuple[TopicSpan, ...]

    @property
    def spans(self) -> tuple[Span, ...]:
        """Return all of them but weekdays, which also stand in sentences that are not about a class."""
        return (
            *self.amounts, *self.dates, *self.times, *self.seats, *self.capacities, *self.lengths,
            *self.topics,
        )


def sino(text: str) -> int:
    """Read Sino-Korean numbers, such as 구십, 백이십, or 삼천오백."""
    total = current = 0
    for letter in text:
        if letter in SINO:
            current = SINO[letter]
        elif letter in SINO_UNITS:
            total, current = total + (current or 1) * SINO_UNITS[letter], 0
    return total + current


def whole_number(text: str) -> int:
    """Read 3, 세, 열두, or 삼십 as a whole number."""
    if text.isdigit():
        return int(text)
    return NATIVE_COUNTS.get(text) or sino(text)


def numeral(text: str | None) -> float:
    """Read digits or words; nothing before a unit means one of it."""
    if text is None:
        return 1.0
    return float(text) if text[0].isdigit() else float(whole_number(text))


def overlaps(span: Span, others: Sequence[Span]) -> bool:
    """Tell whether a span shares text with any other."""
    return any(span.start < other.end and other.start < span.end for other in others)


def pieces(text: str, breaks: re.Pattern[str], first: int, last: int) -> Iterator[tuple[int, int]]:
    """Cut a stretch of text at its breaks."""
    start = first
    for match in breaks.finditer(text, first, last):
        if match.start() > start:
            yield start, match.start()
        start = match.end()
    if start < last:
        yield start, last


def around(text: str, start: int, end: int, breaks: re.Pattern[str]) -> tuple[int, int]:
    """Return where the sentence or clause around a number starts and ends."""
    first, last = 0, len(text)
    for match in breaks.finditer(text):
        if match.end() <= start:
            first = match.end()
        elif match.start() >= end:
            last = match.start()
            break
    return first, last


def is_denied(text: str, start: int, end: int) -> bool:
    """Tell whether the words right after a number say that it does not hold."""
    _, last = around(text, start, end, CLAUSE_BREAK)
    return DENIED.match(text, end, last) is not None


def won_value(match: re.Match[str]) -> int | None:
    """Read one matched amount; a bare word such as 이만 is not one."""
    digits = match["symbol"] or match["plain"]
    if digits is not None:
        return int(digits.replace(",", ""))
    if match["kilo"] is not None:
        return round(float(match["kilo"]) * 1_000)
    man = match["man"]
    spoken = match["has_man"] and man is not None and (man[0].isdigit() or match["has_cheon"])
    if not (match["unit"] or spoken):
        return None
    if not (match["has_man"] or match["has_cheon"] or match["has_baek"]):
        return None
    value = numeral(man) * 10_000 if match["has_man"] else 0.0
    value += numeral(match["cheon"]) * 1_000 if match["has_cheon"] else 0.0
    value += numeral(match["baek"]) * 100 if match["has_baek"] else 0.0
    return round(value) + int((match["rest"] or "0").replace(",", ""))


def counted_people(match: re.Match[str]) -> int | None:
    """Read a matched headcount; 1인 marks a price per person, and 30분 is a length."""
    value = whole_number(match["n"])
    if match["unit"] == "인" and value == 1:
        return None
    if match["unit"] == "분" and match["n"].isdigit() and len(match["n"]) > 1:
        return None
    return value


def amount_role(before: str, after: str) -> AmountRole:
    """Tell whether an amount is named for each person or for several together."""
    if EACH_BEFORE.search(before) or EACH_AFTER.match(after):
        return "each"
    group = GROUP_BEFORE.search(before)
    people = None if group is None else counted_people(group)
    if TOTAL_BEFORE.search(before) or (people is not None and people > 1):
        return "total"
    return "any"


def amount_spans(text: str) -> list[AmountSpan]:
    """Find won amounts, in digits or in words, and what the text around calls them."""
    spans: list[AmountSpan] = []
    for match in AMOUNT.finditer(text):
        value = won_value(match)
        if value is None:
            continue
        stated = match.group().rstrip()
        start, end = match.start(), match.start() + len(stated)
        first, _ = around(text, start, end, SENTENCE_BREAK)
        before = text[max(first, spans[-1].end if spans else 0, start - LOOK_BACK):start]
        after = text[end:end + LOOK_AHEAD]
        role = amount_role(before, after)
        spans.append(AmountSpan(
            start, end, stated, value,
            is_deposit=bool(DEPOSIT_BEFORE.search(before)) or bool(DEPOSIT_AFTER.search(after)),
            is_balance=bool(BALANCE_CALLED.search(before)),
            is_price=role != "any" or bool(PRICE_CALLED.search(before)), role=role,
        ))
    return spans


def people_spans(text: str) -> list[NumberSpan]:
    """Find headcounts that are not the capacity of a class."""
    capacities = capacity_spans(text)
    found: list[NumberSpan] = []
    for match in PEOPLE.finditer(text):
        value = counted_people(match)
        span = NumberSpan(match.start(), match.end(), match.group(), value or 0)
        if value is not None and not overlaps(span, capacities):
            found.append(span)
    found += [
        NumberSpan(m.start(), m.end(), m.group(), PEOPLE_WORDS[m["word"]]) for m in PEOPLE_WORD.finditer(text)
    ]
    return sorted(found, key=lambda span: span.start)


def with_sum(counts: Sequence[int]) -> frozenset[int]:
    """Allow 두 분 and 아이 한 분 to count as three."""
    return frozenset([*counts, sum(counts)]) if counts else frozenset()


def headcounts_in(text: str) -> frozenset[int]:
    """Return the headcounts a whole text names, and their sum."""
    return with_sum([span.value for span in people_spans(text)])


def headcounts_near(text: str, span: Span, amounts: Sequence[Span]) -> frozenset[int]:
    """Return the people an amount is for: named before it, after it, or earlier in its sentence."""
    first, last = around(text, span.start, span.end, SENTENCE_BREAK)
    clause_start, clause_end = around(text, span.start, span.end, CLAUSE_BREAK)
    before = max((other.end for other in amounts if first <= other.start < span.start), default=first)
    is_last = not any(span.end <= other.start < last for other in amounts)
    # 두 자리 예약하시면 counts two people, but seats another clause says are left do not.
    booked = [seat for seat in seat_spans(text) if not seat.exact and clause_start <= seat.start < clause_end]
    people = [*people_spans(text), *(seat for seat in booked if seat.unit in {"자리", "석"})]
    for low, high in (
        (before, span.start), (span.end, last if is_last else clause_end), (first, span.start),
    ):
        counts = [found.value for found in people if low <= found.start and found.end <= high]
        if counts:
            return with_sum(counts)
    return frozenset()


def date_spans(text: str) -> list[DateSpan]:
    """Find written days: 11월 21일, 11/21(토), 2026-11-21, and 21일 토요일."""
    spans: list[DateSpan] = []
    for match in DATE.finditer(text):
        found = {name[0]: text for name, text in match.groupdict().items() if text is not None}
        month, day, weekday = found.get("m", "0"), found["d"], found.get("w", "")
        # 1/2 is a half at least as often as it is a day.
        if match["d2"] is not None and len(day) == 1 and not weekday:
            continue
        spans.append(DateSpan(
            match.start(), match.end(), match.group(), int(month), int(day), weekday,
            denied=is_denied(text, match.start(), match.end()),
        ))
    return spans


def resolve_day(span: DateSpan, today: date) -> date | None:
    """Take the nearest day a written date can mean, skipping days long past."""
    if span.month:
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, span.month, span.day)
            except ValueError:
                continue
            if candidate >= today - timedelta(days=PAST_DAYS):
                return candidate
        return None
    ahead = (today + timedelta(days=offset) for offset in range(DAY_ONLY_RANGE))
    return next(
        (day for day in ahead if day.day == span.day and WEEKDAYS[day.weekday()] == span.weekday), None,
    )


def weekday_spans(text: str) -> list[WeekdaySpan]:
    """Find weekdays that do not stand beside a written date."""
    dates = date_spans(text)
    return [
        WeekdaySpan(match.start(), match.end(), match.group(), match["day"], match["when"] or "")
        for match in WEEKDAY.finditer(text)
        if not any(span.start <= match.start() < span.end for span in dates)
    ]


def weekday_day(span: WeekdaySpan, today: date) -> date:
    """Read a weekday as its next day, or as next week's when the text says 다음 주."""
    index = WEEKDAYS.index(span.weekday)
    if span.when.startswith("다음"):
        return today + timedelta(days=7 - today.weekday() + index)
    return today + timedelta(days=(index - today.weekday()) % 7)


def day_expressions(text: str, today: date) -> list[tuple[int, date]]:
    """List the days a text names and where; a weekday beside its date is part of that date."""
    found = [(span.start, day) for span in date_spans(text) if (day := resolve_day(span, today)) is not None]
    found += [(span.start, weekday_day(span, today)) for span in weekday_spans(text)]
    return sorted(found)


def relative_days(text: str, today: date) -> set[date]:
    """Collect 오늘, 내일, 모레, and 주말 as days."""
    days = {today + timedelta(days=offset) for word, offset in RELATIVE_DAYS if word in text}
    if "주말" in text:
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        days |= {saturday, saturday + timedelta(days=1)}
    return days


def days_named(text: str, today: date, *, relative: bool = True) -> frozenset[date]:
    """Collect the days a text names; a draft's 오늘/내일/주말 can be skipped."""
    days = {day for _, day in day_expressions(text, today)}
    return frozenset(days | (relative_days(text, today) if relative else set()))


def days_near(text: str, position: int, today: date) -> frozenset[date]:
    """Return the day a number belongs to: the last one named before it in its sentence, or the next."""
    first, last = around(text, position, position + 1, SENTENCE_BREAK)
    inside = [(start, day) for start, day in day_expressions(text, today) if first <= start < last]
    before = [day for start, day in inside if start <= position]
    if before:
        return frozenset(before[-1:])
    return frozenset(day for _, day in inside[:1])


def minutes_of(mark: str, hour: int, minute: int, *, padded: bool) -> frozenset[int]:
    """Turn a spoken hour into minutes of the day; without 오전 or 오후 both halves are possible."""
    half_day = hour % NOON
    if not mark:
        hours = {hour % 24} if hour > NOON or hour == 0 or padded else {half_day, half_day + NOON}
    elif hour > NOON:
        hours = {hour % 24}
    elif mark in MORNING or (mark == "밤" and hour == NOON) or (mark in MIDDAY and half_day >= NOON - 2):
        hours = {half_day}
    else:
        hours = {half_day + NOON}
    return frozenset(value * HOUR_MINUTES + minute for value in hours)


def time_spans(text: str) -> list[TimeSpan]:
    """Find times of day: 오후 2시, 14시, 10:00, 열 시 반, and 정오."""
    spans: list[TimeSpan] = []
    for match in TIME.finditer(text):
        if match["noon"] or match["midnight"]:
            minutes = frozenset({NOON * HOUR_MINUTES if match["noon"] else 0})
        else:
            hour = match["h1"] or match["h2"] or match["h3"] or match["h4"]
            minute = HALF if match["half"] else whole_number(match["m1"] or match["m2"] or "0")
            mark = (match["mark"] or match["mark2"] or "").lower().replace(".", "")
            minutes = minutes_of(mark, whole_number(hour), minute, padded=hour.startswith("0"))
        spans.append(TimeSpan(
            match.start(), match.end(), match.group(), minutes, is_clock=match["h1"] is not None,
            denied=is_denied(text, match.start(), match.end()),
        ))
    return spans


def times_near(text: str, position: int) -> list[frozenset[int]]:
    """Return the times of the sentence around a number, the closest one before it first."""
    first, last = around(text, position, position + 1, SENTENCE_BREAK)
    inside = [span for span in time_spans(text) if first <= span.start < last]
    before = [span.minutes for span in inside if span.start <= position]
    return [*reversed(before), *(span.minutes for span in inside if span.start > position)]


def capacity_spans(text: str) -> list[NumberSpan]:
    """Find stated class capacities."""
    return [
        NumberSpan(
            m.start(), m.end(), m.group(), whole_number(m["n"] or m["n2"]),
            prefix=m["prefix"] or m["prefix2"], unit=m["unit"] or m["unit2"],
        )
        for m in CAPACITY.finditer(text)
    ]


def seat_spans(text: str) -> list[NumberSpan]:
    """Find seat counts, said as seats or as people, and whether the draft states the number left."""
    capacities = capacity_spans(text)
    found: list[NumberSpan] = []
    for pattern in (SEATS_LEFT, PEOPLE_LEFT, SEATS, PEOPLE_OPEN, PEOPLE_DENIED):
        for match in pattern.finditer(text):
            groups, unit = match.groupdict(), match["unit"]
            if unit == "분" and counted_people(match) is None:
                continue
            span = NumberSpan(
                match.start(), match.end(), match.group(), whole_number(match["n"]),
                exact=pattern in {SEATS_LEFT, PEOPLE_LEFT}
                or (pattern is SEATS and EXACT_TAIL.match(text[match.end():]) is not None),
                is_limit=groups.get("limit") is not None,
                denied=is_denied(text, match.start(), match.end()),
                prefix=groups.get("prefix") or groups.get("limit") or "", unit=unit,
            )
            if not overlaps(span, [*capacities, *found]):
                found.append(span)
    return sorted(found, key=lambda span: span.start)


def length_minutes(match: re.Match[str]) -> tuple[int, int]:
    """Read a matched length as the minutes it can mean."""
    if match["word"] is not None:
        return LENGTH_WORDS[match["word"].replace(" ", "")]
    if match["only"] is not None:
        minutes = whole_number(match["only"])
        return minutes, minutes
    high = round(numeral(match["h"]) * HOUR_MINUTES)
    high += HALF if match["half"] else whole_number(match["m"] or "0")
    return (round(float(match["low"]) * HOUR_MINUTES) if match["low"] else high), high


def length_spans(text: str) -> list[LengthSpan]:
    """Find class lengths; a length needs a class around it and nothing else that takes time."""
    spans: list[LengthSpan] = []
    for match in LENGTH.finditer(text):
        low, high = length_minutes(match)
        if match["only"] is not None and low < MIN_CLASS_MINUTES:
            continue
        first, last = around(text, match.start(), match.end(), SENTENCE_BREAK)
        start, end = around(text, match.start(), match.end(), CLAUSE_BREAK)
        is_class = CLASS_LENGTH.search(text, first, last) or TOTAL_LENGTH.search(text[first:match.start()])
        if is_class and not OTHER_ACTIVITY.search(text, start, end):
            spans.append(LengthSpan(
                match.start(), match.end(), match.group(), low, high, in_hours=match["only"] is None,
            ))
    return spans


def mentions_topic(text: str, topic: Topic) -> bool:
    """Tell whether a text is about parking, refunds, or materials."""
    return TOPIC_WORDS[topic].search(text) is not None


def topic_clauses(text: str) -> list[tuple[int, int, frozenset[Topic]]]:
    """Cut a text into clauses and tell which topics each one is about, or still about."""
    clauses: list[tuple[int, int, frozenset[Topic]]] = []
    current: frozenset[Topic] = frozenset()
    for first, last in pieces(text, SENTENCE_BREAK, 0, len(text)):
        opening = len(clauses)
        for start, end in pieces(text, CLAUSE_BREAK, first, last):
            clause = text[start:end]
            own: frozenset[Topic] = frozenset(t for t in TOPIC_WORDS if mentions_topic(clause, t))
            if own:
                # 하루 전까지, 전액 환불돼요: the words before the topic belong to it too.
                if not any(topics for _, _, topics in clauses[opening:]):
                    clauses[opening:] = [
                        (low, high, frozenset() if CLASS_WORDS.search(text[low:high]) else own)
                        for low, high, _ in clauses[opening:]
                    ]
                current = own
            elif start == first:
                current = frozenset(topic for topic in current if TOPIC_HINTS[topic].search(clause))
            elif CLASS_WORDS.search(clause):
                current = frozenset()
            clauses.append((start, end, current))
    return clauses


def topics_at(text: str, position: int) -> frozenset[Topic]:
    """Return the topics of the clause at a position."""
    nowhere: frozenset[Topic] = frozenset()
    return next(
        (topics for start, end, topics in topic_clauses(text) if start <= position < end), nowhere,
    )


def quantity_values(match: re.Match[str]) -> frozenset[Quantity]:
    """Normalize a quantity, so that 하루, 1일, and 24시간 are the same."""
    found = {name: text for name, text in match.groupdict().items() if text is not None}
    if "hours" in found:
        minutes = numeral(found["hours"]) * HOUR_MINUTES
        minutes += HALF if "half" in found else whole_number(found.get("m", "0"))
        days = minutes / DAY_MINUTES
        return frozenset({("분", minutes), ("일", days)} if days.is_integer() else {("분", minutes)})
    if "word" in found:
        return frozenset({("일", float(DAY_WORDS[found["word"]]))})
    if "part" in found:
        return frozenset({("%", 50.0)})
    for name, unit, factor in QUANTITY_UNITS:
        if name in found:
            return frozenset({(unit, numeral(found[name]) * factor)})
    return frozenset({(UNIT_NAMES.get(found["unit"], found["unit"]), numeral(found["piece"]))})


def quantities_in(text: str, topic: Topic, first: int = 0, last: int | None = None) -> list[TopicSpan]:
    """Find the quantities of one topic in a stretch of text."""
    end = len(text) if last is None else last
    denied = REFUND_DENIED if topic == "refund" else TOPIC_DENIED
    spans: list[TopicSpan] = []
    for match in QUANTITIES[topic].finditer(text, first, end):
        _, clause_end = around(text, match.start(), match.end(), CLAUSE_BREAK)
        spans.append(TopicSpan(
            match.start(), match.end(), match.group(), topic, quantity_values(match),
            denied=denied.search(text, match.end(), clause_end) is not None,
        ))
    return spans


def topic_distance(text: str, span: TopicSpan, first: int, last: int) -> int:
    """Measure how far a quantity is from the nearest word of its topic in the clause."""
    words = TOPIC_WORDS[span.topic].finditer(text, first, last)
    return min((max(span.start - m.end(), m.start() - span.end, 0) for m in words), default=last - first)


def topic_spans(text: str) -> list[TopicSpan]:
    """Find quantities that belong to parking, refunds, or materials rather than to the class."""
    found: list[TopicSpan] = []
    for first, last, topics in topic_clauses(text):
        candidates = [span for topic in topics for span in quantities_in(text, topic, first, last)]
        for span in sorted(candidates, key=lambda item: topic_distance(text, item, first, last)):
            is_class = CLASS_BEFORE.search(text[first:span.start]) or CLASS_AFTER.match(text[span.end:last])
            if not is_class and not overlaps(span, found):
                found.append(span)
    return sorted(found, key=lambda span: span.start)


def read(text: str) -> Reading:
    """Find every number in a text; one piece of text is read as one number only."""
    amounts, dates, times = amount_spans(text), date_spans(text), time_spans(text)
    topics = [span for span in topic_spans(text) if not overlaps(span, [*amounts, *dates, *times])]
    lengths = [span for span in length_spans(text) if not overlaps(span, [*times, *topics])]
    return Reading(
        tuple(amounts), tuple(dates), tuple(weekday_spans(text)), tuple(times), tuple(seat_spans(text)),
        tuple(capacity_spans(text)), tuple(lengths), tuple(topics),
    )


def amounts_in(texts: Sequence[str]) -> frozenset[int]:
    """Collect the amounts written in any of several texts."""
    return frozenset(span.won for text in texts for span in amount_spans(text))


def number_tokens(text: str) -> frozenset[str]:
    """Normalize the numbers in a sentence so a rewrite can be compared with its source."""
    amounts = amount_spans(text)
    rest = text
    for span in reversed(amounts):
        rest = f"{rest[:span.start]} {rest[span.end:]}"
    return frozenset([f"{span.won}원" for span in amounts] + re.findall(r"\d+(?:\.\d+)?", rest))


def names_a_day(text: str, today: date) -> bool:
    """Tell whether a text names a day, by date, weekday, or a relative word."""
    return bool(days_named(text, today))
