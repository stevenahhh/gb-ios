"""Read Korean owner text as numbers, times, dates, and statements; nothing here changes a digit."""

import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from operator import itemgetter
from typing import Final, Literal

from agent_mask import ACCOUNT, ADDRESS, CONTACT, EMAIL, RESIDENT, Folded

type Unit = Literal["clock", "date", "people", "money", "other", ""]

SINO: Final = {
    "영": 0,
    "공": 0,
    "일": 1,
    "이": 2,
    "삼": 3,
    "사": 4,
    "오": 5,
    "육": 6,
    "륙": 6,
    "칠": 7,
    "팔": 8,
    "구": 9,
}
UNITS: Final = {"십": 10, "백": 100, "천": 1000, "만": 10_000, "억": 100_000_000}
BIG_UNITS: Final = frozenset({"만", "억"})
NATIVE_ONES: Final = {
    "하나": 1,
    "한": 1,
    "둘": 2,
    "두": 2,
    "셋": 3,
    "세": 3,
    "석": 3,
    "넷": 4,
    "네": 4,
    "넉": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
}
NATIVE_TENS: Final = {
    "열": 10,
    "스물": 20,
    "스무": 20,
    "서른": 30,
    "마흔": 40,
    "쉰": 50,
    "예순": 60,
    "일흔": 70,
    "여든": 80,
    "아흔": 90,
}
PEOPLE_UNITS: Final = frozenset({"명", "인", "사람", "분"})
COUNTERS: Final = "명|인|사람|개|시|분|장|권|병|번|팀|자리|좌석|세트|박스|건|벌|매|층|마리|원|월|일|년|초"
TOKEN: Final = re.compile(r"[0-9]+(?:,[0-9]{3})*|[영공일이삼사오육륙칠팔구십백천만억]")
COUNTER_AFTER: Final = re.compile(rf"\s*({COUNTERS})")
NATIVE: Final = re.compile(
    (
        r"(?:(열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)\s*)?"
        r"(하나|한|둘|두|셋|세|석|넷|네|넉|다섯|여섯|일곱|여덟|아홉)?"
        rf"(?=\s*(?:{COUNTERS}))"
    ),
)
HOURS: Final = {
    "열두": 12,
    "열한": 11,
    "열": 10,
    "아홉": 9,
    "여덟": 8,
    "일곱": 7,
    "여섯": 6,
    "다섯": 5,
    "네": 4,
    "세": 3,
    "두": 2,
    "한": 1,
}
MERIDIEM: Final = r"(?P<meridiem>오전|오후|새벽|아침|낮|저녁|밤)?\s*"
HOUR: Final = rf"(?P<hour>\d{{1,2}}|{'|'.join(HOURS)})\s*"
CLOCK: Final = re.compile(rf"{MERIDIEM}{HOUR}시(?:\s*(?P<minute>\d{{1,2}})\s*분|\s*(?P<half>반))?")
COLON_CLOCK: Final = re.compile(rf"{MERIDIEM}(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})(?P<half>)?")
MORNING: Final = frozenset({"오전", "새벽", "아침"})
AFTERNOON: Final = frozenset({"오후", "낮", "저녁", "밤"})
NOON: Final = 12
MONTHS: Final = 12
MONTH_DAY: Final = re.compile(r"(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일")
SLASH_DATE: Final = re.compile(r"(?<!\d)(?:(\d{4})[./-])?(\d{1,2})[./-](\d{1,2})(?!\d)")
DAY_ONLY: Final = re.compile(r"(?<![\d/월])(\d{1,2})\s*일(?!\s*(?:간|동안|뒤|후|전))")
RELATIVE_DAYS: Final = {"그저께": -2, "어제": -1, "오늘": 0, "내일모레": 2, "내일": 1, "모레": 2, "글피": 3}
RELATIVE: Final = re.compile("|".join(sorted(RELATIVE_DAYS, key=len, reverse=True)))
WEEKDAYS: Final = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
WEEKS: Final = {
    "이번 주": 0,
    "이번주": 0,
    "금주": 0,
    "다음 주": 1,
    "다음주": 1,
    "차주": 1,
    "담주": 1,
    "다다음 주": 2,
    "다다음주": 2,
}
WEEKDAY: Final = re.compile(
    rf"(?:({'|'.join(sorted(WEEKS, key=len, reverse=True))})\s*)?([월화수목금토일])요일",
)
SENTENCE: Final = re.compile(r"[^.!?\n]+[.!?]*")
QUESTION_END: Final = re.compile(
    (
        r"(?:까요|나요|가요|을까|할까|될까|일까|니까|냐|니|나|까|어때|는지|은지|은가|는가|인가|건가|지|죠|였나|했나|"
        r"됐나|되나|맞나|맞지|던가|더라|맞아요?)$"
    ),
)
QUESTION_WORD: Final = re.compile(
    (
        r"몇|언제|어디|누구|누가|무엇|뭐|뭘|무슨|어느|어떤|어떻게|왜|얼마|"
        r"(?:알려|보여|읽어|봐|요약\s*해|정리\s*해|내용\s*확인\s*해)\s*(?:줘|주)|"
        r"[는은을]지(?=\s)|모르|몰라|궁금"
    ),
)
NEGATION: Final = re.compile(
    (
        r"(?<![가-힣])(?:안(?=\s|들어|됐|된|돼|되|했|하|받|왔|끝|보냈|쌌)|못|덜\s)|않|아직|말고|지\s*마|말아|보류|"
        r"나중에|취소\s*하지|아니|없(?:어|음|다|네)|빼고|제외|틀렸|거짓말|뻥이|농담|했다가"
    ),
)
CONDITIONAL: Final = re.compile(
    r"(?:(?<!라)(?<!측)(?<!전)(?<!양)(?<!표)면|거든)(?=[\s,.!?~]|$)",
)
INTENDED: Final = re.compile(
    r"(?<![알르좋찮있])겠|예정|계획|려고|하려|할\s*거(?:야|예요|거든)|할\s*겁니다|까지\s*(?:할|끝낼|마칠)",
)
OVERRIDE: Final = re.compile(
    (
        r"이전\s*지시|지시(?:는|를|을)?\s*무시|지침(?:은|을)?\s*무시|규칙(?:은|을)?\s*무시|무시하고|무시해|프롬프트|"
        r"시스템\s*메시지|관리자\s*모드"
    ),
)
SPOKEN_SHALL: Final = re.compile(r"([가-힣])게(?:요)?(?=[\s,.!?~]|$)")
REPORTED: Final = re.compile(
    r"(?:다|냐|라|자|까)고(?=[\s,.!?~]|$)|다는(?:데|\s)|다던데|다더라|다며|다네|단다|[했됐났냈]대|말로는|그러는데|내용은",
)
TENTATIVE: Final = re.compile(
    (
        r"[했됐났냈었았]을|(?:것|거)\s*같|아마|텐데|어야\s*했|더라면|거의|반쯤|다\s*치|[했됐났냈]던|[했됐났냈]었|던\s*거|"
        r"(?:는데|다가|[했됐났냈]고)[\s.…~]*$"
    ),
)
RIEUL_FINAL: Final = 8
QUOTES: Final = (
    ("'", "'"),
    ('"', '"'),
    ("\u2018", "\u2019"),
    ("\u201c", "\u201d"),
    ("\u300c", "\u300d"),
    ("\u300e", "\u300f"),
    ("\u00ab", "\u00bb"),
    ("`", "`"),
)
RELAYED_LINE: Final = re.compile(r"\||\t|^\s*[>{\[]|(?<!\d),(?=\S)|,(?=[^\s\d])")
RELAYED_LABEL: Final = re.compile(
    (
        r"(?:문의|후기|리뷰|댓글|메시지|문자|카톡|카카오톡|메일|글|비고|손님|고객|from|subject)\s*[:\uff1a]|"
        r"^\s*(?!(?:일정|할\s?일|추가|송장|주문|예약|입금|포장|배송|기억|오늘|내일|메모)\s*[:\uff1a])"
        r"[가-힣]{2,4}\s*(?:님|씨)?\s*[:\uff1a]"
    ),
    re.IGNORECASE,
)
RELAYED_BELOW: Final = re.compile(
    r"손님|고객|문의|후기|리뷰|댓글|메시지|문자|카톡|메일|배송\s*메모|붙여|글이야|```",
)
REPORTED_BY: Final = re.compile(
    r"(?:손님|고객|구매자|님|분)(?:이|께서|은|는)?\s.*(?:다|냐|라|자|까)고(?=[\s,.!?~]|$)",
)
NUMBERED: Final = (EMAIL, RESIDENT, CONTACT, ACCOUNT)
"""What reaches or identifies a person by digits or letters; an address is told apart less surely."""
PARTICLE: Final = re.compile(
    (
        r"(?:에게서|한테서|입니다|이에요|께서|에서|에게|한테|으로|이랑|예요|로|은|는|이|가|을|를|의|도|만|에|와|과|랑|"
        r"님|씨|요)$"
    ),
)


@dataclass(frozen=True, slots=True)
class Mention:
    """One number the text spells out, where it is, and what it counts."""

    value: int
    start: int
    end: int
    unit: Unit


def normalized(text: str) -> str:
    """Fold width, case, and runs of whitespace; offsets are not kept."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def compact(text: str) -> str:
    """Drop every space and separator for name and quote comparison."""
    return re.sub(r"[\s.,·!?~…\-]+", "", normalized(text))


def without_particle(text: str) -> str:
    """Drop one trailing particle a reference may carry."""
    stripped = text.strip()
    return PARTICLE.sub("", stripped) if len(stripped) > 1 else stripped


def number_tokens(text: str) -> Iterator[tuple[list[str], int, int]]:
    """Yield the token runs that spell one number: digits with units, or digits read one by one."""
    position = 0
    while (match := TOKEN.search(text, position)) is not None:
        tokens, start, end = [match.group()], match.start(), match.end()
        while True:
            last = tokens[-1]
            following = TOKEN.match(text, end)
            gap = re.match(r"\s+", text[end:])
            if following is None and gap and last in UNITS:
                following = TOKEN.match(text, end + gap.end())
            if following is None:
                break
            word = following.group()
            arabic_after_digits = word[0].isdigit() and last not in UNITS
            sino_after_arabic = last[0].isdigit() and word in SINO
            if arabic_after_digits or sino_after_arabic:
                break
            tokens.append(word)
            end = following.end()
        yield tokens, start, end
        position = end


def evaluate(tokens: Sequence[str]) -> int | None:
    """Work out what a token run says: positional numerals with units, or digits read one by one."""
    if all(token in SINO for token in tokens):
        return int("".join(str(SINO[token]) for token in tokens)) if len(tokens) > 1 else None
    total = section = current = 0
    for token in tokens:
        if token[0].isdigit():
            current = int(token.replace(",", ""))
        elif token in SINO:
            current = SINO[token]
        elif token in BIG_UNITS:
            total += (section + current or 1) * UNITS[token]
            section = current = 0
        else:
            section += (current or 1) * UNITS[token]
            current = 0
    return total + section + current


def unit_after(text: str, end: int, *, native: bool) -> Unit:
    """Name what a number counts from the word right after it."""
    match = COUNTER_AFTER.match(text, end)
    if match is None:
        return ""
    word = match.group(1)
    if word == "원":
        return "money"
    if word in {"월", "일", "년"}:
        return "date"
    if word in {"시", "초"} or (word == "분" and not native):
        return "clock"
    return "people" if word in PEOPLE_UNITS else "other"


def mentions(text: str) -> list[Mention]:
    """List every number the text spells out; a run of units alone needs a counter after it."""
    found: list[Mention] = []
    for tokens, start, end in number_tokens(text):
        value = evaluate(tokens)
        unit = unit_after(text, end, native=False)
        units_only = all(token in UNITS for token in tokens)
        if value is not None and (not units_only or unit):
            found.append(Mention(value, start, end, unit))
    for match in NATIVE.finditer(text):
        tens, ones = match.group(1), match.group(2)
        if tens or ones:
            value = NATIVE_TENS.get(tens or "", 0) + NATIVE_ONES.get(ones or "", 0)
            unit = unit_after(text, match.end(), native=True)
            found.append(Mention(value, match.start(), match.end(), unit))
    return sorted(found, key=lambda mention: mention.start)


def clock_times(text: str) -> list[tuple[int, int, int, int]]:
    """List (hour, minute, start, end); an hour without a meridiem stays as said."""
    found: list[tuple[int, int, int, int]] = []
    for pattern in (CLOCK, COLON_CLOCK):
        for match in pattern.finditer(text):
            word = match["hour"]
            hour = HOURS.get(word) or int(word)
            minute = 30 if match["half"] else int(match["minute"] or 0)
            if match["meridiem"] in MORNING and hour == NOON:
                hour = 0
            elif match["meridiem"] in AFTERNOON and hour < NOON:
                hour += NOON
            found.append((hour, minute, match.start(), match.end()))
    return found


def same_clock(hour: int, minute: int, wanted: time) -> bool:
    """Compare a spoken time with a 24-hour time; an hour up to 12 may mean either half of the day."""
    if minute != wanted.minute:
        return False
    return hour == wanted.hour or (hour <= NOON and hour % NOON == wanted.hour % NOON)


def day_of(today: date, year: str | None, month: str | None, day: str) -> date:
    """Build a date from its parts; a missing month or year follows today."""
    number = int(day)
    if month is None:
        month_number, year_number = today.month, today.year
        if number < today.day:
            month_number, year_number = (month_number % MONTHS) + 1, year_number + (month_number == MONTHS)
    else:
        month_number = int(month)
        year_number = int(year) if year else today.year + (int(month) < today.month)
    try:
        return date(year_number, month_number, number)
    except ValueError:
        return today


def dates_named(text: str, today: date) -> list[tuple[date, int, int]]:
    """List dates the text names, relative to today, with their positions."""
    found: list[tuple[date, int, int]] = []
    for pattern in (MONTH_DAY, SLASH_DATE):
        found.extend(
            (day_of(today, match.group(1), match.group(2), match.group(3)), *match.span())
            for match in pattern.finditer(text)
        )
    covered = [(start, end) for _, start, end in found]
    found.extend(
        (day_of(today, None, None, match.group(1)), *match.span())
        for match in DAY_ONLY.finditer(text)
        if not any(start <= match.start() < end for start, end in covered)
    )
    found.extend(
        (today + timedelta(days=RELATIVE_DAYS[match.group()]), *match.span())
        for match in RELATIVE.finditer(text)
    )
    found.extend((weekday_date(today, match), *match.span()) for match in WEEKDAY.finditer(text))
    return found


def weekday_date(today: date, match: re.Match[str]) -> date:
    """Name the weekday the owner means: the next one from today, or the one of the week they named."""
    offset = WEEKDAYS[match.group(2)]
    if match.group(1) is None:
        return today + timedelta(days=(offset - today.weekday()) % 7)
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(days=WEEKS[match.group(1)] * 7 + offset)


def sentence_around(text: str, position: int, following: int = 0) -> str:
    """Return the sentence that contains a position, with the sentences right after it when asked."""
    found = list(SENTENCE.finditer(text))
    for index, match in enumerate(found):
        if match.start() <= position < match.end():
            return text[match.start() : found[min(index + following, len(found) - 1)].end()]
    return text


def is_question(sentence: str) -> bool:
    """Tell when a sentence asks instead of stating; unclear wording counts as a question."""
    stripped = sentence.strip().rstrip(".! ")
    return (
        "?" in sentence
        or "\uff1f" in sentence
        or QUESTION_END.search(stripped) is not None
        or QUESTION_WORD.search(stripped) is not None
    )


def is_negated(sentence: str) -> bool:
    """Tell when a sentence denies or postpones what it names."""
    return NEGATION.search(sentence) is not None


def is_planned(sentence: str) -> bool:
    """Tell when a sentence promises or plans something instead of reporting it."""
    if INTENDED.search(sentence) is not None:
        return True
    return any(
        (ord(match.group(1)) - 0xAC00) % 28 == RIEUL_FINAL for match in SPOKEN_SHALL.finditer(sentence)
    )


def is_unfinished(sentence: str) -> bool:
    """Tell when a sentence does not state a done fact: a condition, a plan, or someone else's words."""
    return (
        CONDITIONAL.search(sentence) is not None
        or is_planned(sentence)
        or REPORTED.search(sentence) is not None
        or TENTATIVE.search(sentence) is not None
        or OVERRIDE.search(sentence) is not None
    )


def sentences(text: str) -> list[str]:
    """Split a text into its sentences."""
    return [match.group() for match in SENTENCE.finditer(text)]


def is_quoted(text: str, start: int, end: int) -> bool:
    """Tell when a span sits inside quotation marks, so it is someone else's words."""
    for opening, closing in QUOTES:
        before, after = text[:start], text[end:]
        if opening == closing:
            if before.count(opening) % 2 == 1 and closing in after:
                return True
        elif before.rfind(opening) > before.rfind(closing) and closing in after:
            return True
    return False


def is_relayed(text: str, start: int) -> bool:
    """Tell when a span sits in pasted text: a table, a quoted or labelled line, or below one."""
    *above, _ = text[: start + 1].split("\n")
    opening = text.rfind("\n", 0, start) + 1
    line = text[opening:].split("\n", 1)[0]
    label = RELAYED_LABEL.search(line)
    if RELAYED_LINE.search(line) is not None or (label is not None and label.end() <= start - opening):
        return True
    return any(RELAYED_LABEL.search(one) or RELAYED_BELOW.search(one) for one in above)


def is_retold(sentence: str) -> bool:
    """Tell when a sentence passes on what a customer said or overrides the assistant's rules."""
    return REPORTED_BY.search(sentence) is not None or OVERRIDE.search(sentence) is not None


def contact_spans(
    text: str,
    patterns: Sequence[re.Pattern[str]] = NUMBERED,
) -> list[tuple[int, int]]:
    """List phones, emails, and account or resident numbers, whose digits never name an order."""
    folded = Folded.of(text)
    return [(start, end) for pattern in patterns for start, end, _ in folded.found(pattern)]


def excerpt(text: str, start: int, end: int, limit: int = 40) -> str:
    """Cut a readable piece of text around a span, so no word, contact, or address is cut in two."""
    room = max(limit - (end - start), 0) // 2
    left, right = max(start - room, 0), min(end + room, len(text))
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    while right < len(text) and not text[right].isspace():
        right += 1
    whole = contact_spans(text, (*NUMBERED, ADDRESS))
    for first, last in sorted(whole, reverse=True):
        left = first if first < left < last else left
    for first, last in sorted(whole, key=itemgetter(1)):
        right = last if first < right < last else right
    piece = " ".join(text[left:right].split())
    return f"{'…' if left else ''}{piece}{'…' if right < len(text) else ''}"
