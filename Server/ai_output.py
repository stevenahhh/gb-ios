"""Pure cleanup and safety checks applied to model output before a client sees it."""

import re
from typing import Final

FENCE: Final = re.compile(r"^[ \t]*```[\w-]*[ \t]*$", re.MULTILINE)
LABEL: Final = re.compile(
    r"^\s*(?:답변\s*초안|답장\s*초안|답변|답장|초안|수정본|수정안|다시\s*쓴\s*글|홍보\s*글|결과)\s*[:\uff1a]\s*",
)
HEADING: Final = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
BULLET: Final = re.compile(r"^[ \t]*[-*•][ \t]+", re.MULTILINE)
BOLD: Final = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
FILLER: Final = re.compile(
    r"(?:\s*[^.!?\n]*도움이\s*(?:되셨|되었|됐|되)(?:길|기를|으면|다면)[^.!?\n]*[.!?]?)+\s*$",
)
BLANK_RUN: Final = re.compile(r"\n{3,}")
QUOTE_PAIRS: Final = (
    ('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u300c", "\u300d"), ("\u300e", "\u300f"),
)

COMMITMENTS: Final = (
    ("예약 확정", re.compile(
        r"예약(?:이|은|을|도)?\s*(?:확정(?:되었|됐|되셨|이에요|입니다|해\s*드[리릴렸]|했)|완료(?:되었|됐|입니다|했))",
    )),
    ("환불 약속", re.compile(r"환불(?:을|은)?\s*(?:처리|진행)?\s*(?:해\s*드[리릴렸]|했|되었|됐)")),
    ("결제 완료", re.compile(r"결제(?:가|는|도)?\s*(?:완료|확인되었|확인됐|처리되었|처리됐)")),
    ("할인 약속", re.compile(r"할인(?:을|은)?\s*(?:적용\s*)?(?:해\s*드[리릴렸]|되었|됐|됩니다)")),
)
AMOUNT: Final = re.compile(r"\d[\d,]*\s*원")
DATE: Final = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def unquote(text: str) -> str:
    """Remove one pair of quotes that wraps the whole text."""
    for opening, closing in QUOTE_PAIRS:
        inner = text[1:-1]
        if len(text) > 1 and text[0] == opening and text[-1] == closing and closing not in inner:
            return inner.strip()
    return text


def normalize(raw: str) -> str:
    """Strip wrappers, labels, markdown, and closing filler the prompts forbid."""
    text = FENCE.sub("", raw).strip()
    text = unquote(LABEL.sub("", text, count=1).strip())
    text = BOLD.sub(r"\1\2", HEADING.sub("", text))
    text = BULLET.sub("· ", text)
    text = FILLER.sub("", text)
    return BLANK_RUN.sub("\n\n", text).strip()


def amounts(text: str) -> set[str]:
    """Collect won amounts with separators removed."""
    return {re.sub(r"[,\s]", "", match.expand(r"\g<0>")) for match in AMOUNT.finditer(text)}


def dates(text: str) -> set[tuple[int, int]]:
    """Collect month-day dates."""
    return {(int(match.expand(r"\1")), int(match.expand(r"\2"))) for match in DATE.finditer(text)}


def empty_problems(text: str) -> list[str]:
    """Report output that has nothing left after cleanup."""
    return [] if text else ["빈 응답"]


def reply_problems(text: str, basis: str, question: str) -> list[str]:
    """Report commitments, amounts, and dates a customer reply cannot support.

    `basis` holds the facts and written rules the reply may rely on. Commitments must
    appear there; the customer's own question is accepted only as a source of values,
    so asking "예약 확정됐나요?" never licenses claiming the booking is confirmed.
    """
    if not text:
        return empty_problems(text)
    problems = [
        f"근거 없는 {label}" for label, pattern in COMMITMENTS
        if pattern.search(text) and not pattern.search(basis)
    ]
    sources = f"{basis}\n{question}"
    problems += [f"근거 없는 금액 {amount}" for amount in sorted(amounts(text) - amounts(sources))]
    problems += [f"근거 없는 날짜 {m}월 {d}일" for m, d in sorted(dates(text) - dates(sources))]
    return problems
