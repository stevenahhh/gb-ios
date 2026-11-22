"""Hide names, contacts, addresses, and account or resident numbers before the model or a record.

Matching reads a folded copy, so width, composition, invisible characters, and dash shapes hide nothing;
only the matched words are replaced and every other character stays as it was written. Order numbers,
tracking numbers, money, dates, and times stay readable: a long number without separators is an account
or resident number only beside a word that says so. A name is hidden the way the app shows it
(display.masked), and `aliases` remembers which real name each hidden form in the owner's turn was.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

from display import masked

SEP: Final = r"[-.\s()]{0,3}"
NOT_INVOICE: Final = r"(?<!송장)(?<!송장 )(?<!송장번호 )(?<!송장번호는 )"
CONTACT: Final = re.compile(
    (
        rf"(?<!\d)\(?(?:\+?82{SEP}0?{SEP}|0)1[016789]{SEP}\d{{3,4}}{SEP}\d{{4}}(?!\d)"
        r"|(?<!\d)\(?0\d{1,2}[-.\s)]{1,3}\d{3,4}[-.\s]{1,3}\d{4}(?!\d)"
        r"|(?<!\d)050\d[-.\s]\d{3,4}[-.\s]\d{4}(?!\d)"
        rf"|{NOT_INVOICE}(?<!\d)0(?:2|[3-6][1-5]|70)\d{{7,8}}(?!\d)"
    ),
)
EMAIL: Final = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
RESIDENT: Final = re.compile(
    (
        r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[-.\s]{1,3}[1-8]\d{6}(?!\d)"
        r"|(?:주민|외국인\s?등록)[^\d\n]{0,12}(?P<part>\d{13})(?!\d)"
    ),
)
BANK: Final = r"(?:국민|신한|우리|하나|기업|카카오|토스|케이|농협|수협|신협)?(?:은행|뱅크)?"
ACCOUNT: Final = re.compile(
    (
        rf"(?:계좌|통장|은행|뱅크|농협|수협|신협|토스)(?:번호)?[은는이가]?[\s:]{{0,3}}{BANK}[\s:]{{0,3}}"
        r"(?P<part>\d(?:[ -]?\d){9,15})(?!\d)"
        rf"|{NOT_INVOICE}(?<![\d-])(?=\d(?:-?\d){{9,13}}(?![\d-]))\d{{2,6}}-\d{{2,6}}-(?!(?<=-\d{{4}}-)\d{{4}}(?!\d))"
        r"\d{2,7}(?![\d-])"
    ),
)
ADDRESS: Final = re.compile(
    (
        r"[가-힣]{2,12}(?:특별시|광역시|특별자치시|도|시)?\s*[가-힣]{1,8}(?:구|군|시)\s+"
        r"[가-힣0-9]{1,20}(?:로|길|동|읍|면|가)(?:\s+[가-힣]{1,8}리(?=\s*\d))?\s*\d*(?:-\d+)?"
        r"(?:,?\s*\d+(?:동|호|층))*"
    ),
)
SURNAMES: Final = (
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염"
    "여추도소석선설마길연위표명기반라왕금옥육인맹제모탁국"
)
HONORED: Final = re.compile(rf"(?<![가-힣])(?P<part>[{SURNAMES}][가-힣]{{1,3}})(?:\s?님|\s씨)")
GENERAL: Final = frozenset({
    "고객", "손님", "구매자", "주문자", "예약자", "문의자", "회원", "비회원", "익명",
    "네이버", "스마트스토어", "카카오", "카카오톡", "인스타그램",
})
"""Words a channel writes where a name is missing; none of them is ever a name."""
ROLES: Final = frozenset({"선생", "강사", "원장", "기사", "주인", "이모", "신랑", "신부", "조교"})
HIDDEN_CONTACT: Final = "(연락처 가림)"
HIDDEN_ADDRESS: Final = "(주소 가림)"
HIDDEN_EMAIL: Final = "(이메일 가림)"
HIDDEN_NUMBER: Final = "(번호 가림)"
NAME_KEYS: Final = frozenset({"customer", "customer_name", "name"})
MIN_NAME: Final = 2
SPACED_NAME: Final = 3
"""Only a name this long is also read with spaces inside, so two letters never join across words."""
PIECE: Final = re.compile("[\u1100-\u1112][\u1161-\u1175][\u11a8-\u11c2]?|.", re.DOTALL)
DASHES: Final = frozenset("\u2212\u1173\u30fc")
INVISIBLE: Final = frozenset({"Cf", "Mn"})


@dataclass(frozen=True, slots=True)
class Folded:
    """A text as a person reads it, with where each letter came from."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    @classmethod
    def of(cls, value: str) -> "Folded":
        """Fold width, composition, digits, and dashes, and skip invisible characters."""
        letters: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        for piece in PIECE.finditer(value):
            for char in unicodedata.normalize("NFKC", piece.group()):
                kind = unicodedata.category(char)
                if kind in INVISIBLE:
                    continue
                is_dash = kind == "Pd" or char in DASHES
                letters.append("-" if is_dash else str(unicodedata.decimal(char, char)))
                starts.append(piece.start())
                ends.append(piece.end())
        return cls("".join(letters), tuple(starts), tuple(ends))

    def found(self, pattern: re.Pattern[str]) -> Iterator[tuple[int, int, str]]:
        """Yield where each match lies in the original text, with the folded words."""
        for match in pattern.finditer(self.text):
            part = "part" if match.re.groupindex and match["part"] is not None else 0
            start, end = match.span(part)
            yield self.starts[start], self.ends[end - 1], match[part]


def replaced(value: str, spans: Iterable[tuple[int, int, str]]) -> str:
    """Put each label where its words were; spans come in order and do not overlap."""
    parts: list[str] = []
    last = 0
    for start, end, label in spans:
        parts += [value[last:start], label]
        last = end
    return "".join([*parts, value[last:]])


def without_contacts(value: str) -> str:
    """Hide everything that reaches or identifies a person except a name."""
    hidden = value
    for pattern, label in (
        (EMAIL, HIDDEN_EMAIL), (RESIDENT, HIDDEN_NUMBER), (CONTACT, HIDDEN_CONTACT), (ACCOUNT, HIDDEN_NUMBER),
        (ADDRESS, HIDDEN_ADDRESS),
    ):
        hidden = replaced(hidden, ((start, end, label) for start, end, _ in Folded.of(hidden).found(pattern)))
    return hidden


def joined(name: str) -> str:
    """Write a name without spaces or invisible characters, for comparison."""
    return "".join(Folded.of(name).text.split())


def is_general(name: str) -> bool:
    """Tell when a customer field holds only general words, such as 네이버 고객, instead of a name."""
    return all({word, word.removesuffix("님")} & GENERAL for word in Folded.of(name).text.split())


def name_pattern(name: str) -> str:
    """Match a name as written, and a longer one with single spaces inside."""
    return " ?".join(map(re.escape, name)) if len(name) >= SPACED_NAME else re.escape(name)


@dataclass(frozen=True, slots=True)
class Masker:
    """Masks every text of one run with the names of the customers known when the run started."""

    names: tuple[str, ...]

    @classmethod
    def of(cls, names: Iterable[str]) -> "Masker":
        """Prepare the names, longest first so a full name wins over a part of it."""
        kept = {
            name.strip() for name in names if len(joined(name)) >= MIN_NAME and not is_general(name)
        }
        return cls(tuple(sorted(kept, key=len, reverse=True)))

    def named(self, value: str) -> list[tuple[int, int, str]]:
        """List where a known name stands in a text, with the real name."""
        if not self.names:
            return []
        known = {joined(name): name for name in reversed(self.names)}
        pattern = re.compile("|".join(name_pattern(name) for name in sorted(known, key=len, reverse=True)))
        return [(start, end, known[joined(words)]) for start, end, words in Folded.of(value).found(pattern)]

    def text(self, value: str) -> str:
        """Hide names, contacts, addresses, and account or resident numbers in free text."""
        hidden = without_contacts(value)
        hidden = replaced(hidden, ((start, end, masked(name)) for start, end, name in self.named(hidden)))
        return replaced(hidden, ((start, end, masked(name)) for start, end, name in honored(hidden)))

    def aliases(self, turn: str) -> dict[str, str]:
        """Map each hidden name that appears in the owner's turn back to the real one, if it is unique."""
        found: dict[str, str] = {}
        taken: set[str] = set()
        known = self.named(turn)
        rest = replaced(turn, ((start, end, masked(name)) for start, end, name in known))
        for *_, name in [*known, *honored(rest)]:
            hidden = masked(name)
            if joined(found.setdefault(hidden, name)) != joined(name):
                taken.add(hidden)
        return {hidden: name for hidden, name in found.items() if hidden not in taken}

    def args(self, values: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        """Hide personal data in the arguments that are stored with a step, keys included."""
        return {self.text(key): self.value(key, item) for key, item in values.items()}

    def value(self, key: str, item: JsonValue) -> JsonValue:
        """Hide one argument value; a phone sent as a number has lost its leading zero."""
        if isinstance(item, str):
            return masked(item) if key in NAME_KEYS else self.text(item)
        if isinstance(item, dict):
            return self.args(item)
        if isinstance(item, list):
            return [self.value(key, part) for part in item]
        if isinstance(item, int) and CONTACT.fullmatch(f"0{item}"):
            return HIDDEN_CONTACT
        return item


def honored(value: str) -> list[tuple[int, int, str]]:
    """List names a text addresses with 님 or 씨, so a person who is not a customer yet is hidden too."""
    return [
        span for span in Folded.of(value).found(HONORED)
        if not any(span[2].endswith(word) for word in GENERAL | ROLES)
    ]


def unmasked(values: Mapping[str, JsonValue], aliases: Mapping[str, str]) -> dict[str, JsonValue]:
    """Put the real names back where the model used the hidden form it was shown."""
    return {
        key: aliases.get(item.strip(), item) if isinstance(item, str) else item
        for key, item in values.items()
    }
