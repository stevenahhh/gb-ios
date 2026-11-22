"""Read the owner's invoice text into entries and the numbers written in them, without changing a digit."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal

from b_k25_numbers import sino
from carriers import MAX_DIGITS, MIN_DIGITS

type Role = Literal["tracking", "order", "carrier", "phone", "address", "recipient"]
HEADER_WORDS: Final[tuple[tuple[Role, tuple[str, ...]], ...]] = (
    ("tracking", ("운송장번호", "송장번호", "운송장", "송장")),
    ("order", ("주문번호", "주문")),
    ("carrier", ("택배사", "배송사", "택배")),
    ("phone", ("전화", "연락처", "휴대폰", "핸드폰")),
    ("address", ("주소",)),
    ("recipient", ("받는분", "받는사람", "수취인", "수령인", "고객명", "이름")),
)
DIGIT_WORDS: Final = str.maketrans("공영빵일이삼사오육륙칠팔구", "0001234566789")
SPOKEN: Final = re.compile(r"[0-9공영빵일이삼사오육륙칠팔구](?:[ -]?[0-9공영빵일이삼사오육륙칠팔구])+")
MIN_SPOKEN: Final = 6
DASHES: Final = re.compile("[\u2010-\u2015\u2212\uff0d]")
GROUPS: Final = re.compile(r"(?<!\d)\d+(?:[ .-]\d+)*(?!\d)")
MOMENT: Final = re.compile(
    r"(?<![\d.-])(?:19|20)\d{2}[.-]\d{1,2}[.-]\d{1,2}(?![\d-]|\.\d)|(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])",
)
SPOKEN_ORDER: Final = re.compile(r"([일이삼사오육칠팔구십백천]*[백천][일이삼사오육칠팔구십백천]*)\s*번")
UNIT_AFTER: Final = re.compile(r"\s?(?:개|원|일|월|년|시|분|명|호|동|층|박스|kg|g\b|%)")
PHONE: Final = re.compile(
    (
        r"(?<![\d-])(?:0\d{1,2}-\d{3,4}-\d{4}|01[016789][ .-]?\d{3,4}[ .-]?\d{4}"
        r"|050\d-\d{3,4}-\d{4}|\+82[ -]?\d{1,2}[ -]?\d{3,4}[ -]?\d{4})(?![\d-])"
    ),
)
TOTALS: Final = re.compile(r"합계|총계|소계|총\s*\d+\s*건|total")
CLAUSE_BREAK: Final = re.compile(r"[,;/]|\s(?:그리고|또|다음)\s")
SENTENCE_END: Final = re.compile(r"(?:(?<=[^\d\s])(?<!no)|(?<=[\d -]{8}))[.!?]+\s+")
DELIMITERS: Final = ("\t", ",", "|")
MAX_ORDER_DIGITS: Final = 7
MIN_ORDER_DIGITS: Final = 3
MIN_HEADER_ROLES: Final = 2
MIN_PARTIAL: Final = 8
MAX_JOINED: Final = 40
HANGUL: Final = re.compile("[\uac00-\ud7a3]")
COPULA: Final = frozenset("이일")


def normalize(text: str) -> tuple[str, bool]:
    """Fold full-width forms and dashes, lower-case, and spell out dictated digit runs; flag dictation."""
    folded = DASHES.sub("-", unicodedata.normalize("NFKC", text)).lower()
    folded = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in folded)
    spoken = False

    def digits(match: re.Match[str]) -> str:
        nonlocal spoken
        run, head, tail = match.group(), "", ""
        if HANGUL.match(folded[match.start() - 1:match.start()]) and run[1] in " -":
            head, run = run[:2], run[2:]
        while run and run[-1] in COPULA and HANGUL.match(tail or folded[match.end():match.end() + 1]):
            run, tail = run[:-1], run[-1] + tail
        if sum(not letter.isascii() for letter in run) < MIN_SPOKEN:
            return match.group()
        spoken = True
        return head + run.translate(DIGIT_WORDS) + tail

    return SPOKEN.sub(digits, folded), spoken


@dataclass(frozen=True, slots=True)
class Entry:
    """One source row: free text, or cells keyed by the header word above them."""

    line: int
    text: str
    cells: tuple[tuple[Role, str], ...]
    spoken: bool

    def cell(self, role: Role) -> str | None:
        """Return this row's value under one header, when the source had one."""
        return next((value for key, value in self.cells if key == role), None)


def header_roles(cells: Sequence[str]) -> list[Role | None] | None:
    """Map each header cell to a role, or say the row is not a header."""
    roles: list[Role | None] = []
    for cell in cells:
        word = re.sub(r"\s", "", normalize(cell)[0])
        roles.append(next((role for role, words in HEADER_WORDS if any(w in word for w in words)), None))
    named = {role for role in roles if role}
    if len(named) < MIN_HEADER_ROLES or not named & {"tracking", "order"} or GROUPS.search(" ".join(cells)):
        return None
    return roles


def table_entries(rows: Sequence[Sequence[str]]) -> list[Entry]:
    """Turn rows into entries; rows under a header keep their cells, totals rows are dropped."""
    entries: list[Entry] = []
    roles: list[Role | None] | None = None
    for line, cells in enumerate(rows, 1):
        found = header_roles(cells)
        if found is not None:
            roles = found
            continue
        joined = " / ".join(cell for cell in cells if cell.strip())
        text, spoken = normalize(joined)
        if not text.strip() or TOTALS.search(text):
            continue
        keyed: tuple[tuple[Role, str], ...] = ()
        if roles is not None and len(cells) == len(roles):
            keyed = tuple(
                (role, normalize(cell)[0].strip()) for role, cell in zip(roles, cells, strict=True) if role
            )
        entries.append(Entry(line, text, keyed, spoken))
    return entries


def sentences(entries: Sequence[Entry]) -> list[Entry]:
    """Cut free text at sentence ends, so an order named in one sentence says nothing about the next."""
    cut: list[Entry] = []
    for entry in entries:
        parts = [entry.text] if entry.cells else SENTENCE_END.split(entry.text)
        cut.extend(replace(entry, text=part) for part in parts if part.strip())
    return cut


def text_rows(text: str) -> list[list[str]]:
    """Split pasted lines into cells by the delimiter of the first header line, if there is one."""
    lines = text.splitlines()
    for line in lines:
        for delimiter in DELIMITERS:
            if delimiter in line and header_roles(line.split(delimiter)) is not None:
                return [row.split(delimiter) if delimiter in row else [row] for row in lines]
    return [[line] for line in lines]


@dataclass(frozen=True, slots=True)
class Group:
    """A run of digits and where it sits in the clause."""

    digits: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Candidate:
    """A tracking number as written: its digits and the text it was read from."""

    digits: str
    excerpt: str
    start: int


@dataclass(frozen=True, slots=True)
class Mentions:
    """The numbers one clause names: tracking candidates, order numbers, and phone numbers."""

    numbers: tuple[Candidate, ...]
    orders: tuple[int, ...]
    phones: tuple[str, ...]


def in_range(digits: str) -> bool:
    """Tell whether a digit string is as long as some tracking number."""
    return MIN_DIGITS <= len(digits) <= MAX_DIGITS


def joined(groups: Sequence[Group]) -> str:
    """Join neighbouring groups the way the owner wrote them, minus separators."""
    return "".join(group.digits for group in groups)


def short_order(text: str, group: Group) -> int | None:
    """Read a 3 to 7 digit number as an order reference unless a unit follows it."""
    if not MIN_ORDER_DIGITS <= len(group.digits) <= MAX_ORDER_DIGITS or UNIT_AFTER.match(text, group.end):
        return None
    return int(group.digits)


def split_known(groups: list[Group], known: frozenset[int], text: str) -> tuple[list[Group], list[int]]:
    """Take a known order number set off by a space from either end, even when the whole looks valid."""
    orders: list[int] = []
    if len(groups) > 1 and int(groups[0].digits) in known and text[groups[0].end] == " ":
        orders.append(int(groups[0].digits))
        groups = groups[1:]
    if len(groups) > 1 and int(groups[-1].digits) in known and text[groups[-1].start - 1] == " ":
        orders.append(int(groups[-1].digits))
        groups = groups[:-1]
    return groups, orders


def peel(groups: list[Group], known: frozenset[int]) -> tuple[list[Group], list[int]]:
    """Take order numbers off either end of a run of short groups until the rest is number-sized."""
    orders: list[int] = []
    while len(groups) > 1 and not in_range(joined(groups)):
        first, last = groups[0], groups[-1]
        if int(first.digits) in known or in_range(joined(groups[1:])):
            orders.append(int(first.digits))
            groups = groups[1:]
        elif int(last.digits) in known or in_range(joined(groups[:-1])):
            orders.append(int(last.digits))
            groups = groups[:-1]
        else:
            break
    return groups, orders


def pieces(text: str, run: re.Match[str]) -> list[list[Group]]:
    """Cut a run so every number-sized group stands alone and short groups stay together."""
    cut: list[list[Group]] = [[]]
    for match in re.finditer(r"\d+", text[run.start():run.end()]):
        group = Group(match.group(), run.start() + match.start(), run.start() + match.end())
        if len(group.digits) >= MIN_DIGITS:
            cut.extend([[group], []])
        else:
            cut[-1].append(group)
    return [piece for piece in cut if piece]


def without_phones(text: str) -> str:
    """Blank out phones, dates, and times at the same length, so no other number can join across one."""
    for pattern in (PHONE, MOMENT):
        text = pattern.sub(lambda match: "_" * len(match.group()), text)
    return text


def read_clause(text: str, known: frozenset[int]) -> Mentions:
    """Find tracking candidates, order references, and phone numbers in one clause."""
    numbers: list[Candidate] = []
    orders = [sino(match.group(1)) for match in SPOKEN_ORDER.finditer(text)]
    phones = tuple(
        re.sub(r"\D", "", match.group()) for match in PHONE.finditer(text)
        if not match.group().startswith(("050", "+82"))
    )
    for run in GROUPS.finditer(without_phones(text)):
        for piece in pieces(text, run):
            rest, named = split_known(piece, known, text)
            groups, peeled = peel(rest, known)
            orders.extend([*named, *peeled])
            if len(joined(groups)) >= (MIN_PARTIAL if named else MIN_DIGITS):
                first, last = groups[0], groups[-1]
                numbers.append(Candidate(joined(groups), text[first.start:last.end], first.start))
            else:
                orders.extend(order for g in groups if (order := short_order(text, g)) is not None)
    return Mentions(tuple(numbers), tuple(orders), phones)


def clauses(entry: Entry, known: frozenset[int]) -> list[tuple[str, Mentions]]:
    """Split a free-text entry into clauses only when it names more than one tracking number."""
    whole = read_clause(entry.text, known)
    if len(whole.numbers) <= 1:
        return [(entry.text, whole)]
    return [(part, read_clause(part, known)) for part in CLAUSE_BREAK.split(entry.text) if part.strip()]


def verbatim_numbers(text: str) -> frozenset[str]:
    """List every digit string the text spells out; only short neighbouring groups may join."""
    found: set[str] = set()
    source = without_phones(normalize(text)[0])
    for run in GROUPS.finditer(source):
        for piece in pieces(source, run):
            found.update(
                joined(piece[i:j])
                for i in range(len(piece)) for j in range(i + 1, min(i + MAX_JOINED, len(piece)) + 1)
            )
    return frozenset(found)
