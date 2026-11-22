"""HyperCLOVA X prompts, message builders, and output parsers of the grounded reply engine.

Prompts follow the design chapter: the model routes, writes, and extracts, but the server
decides every match, so a malformed answer always has a deterministic fallback.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import JsonValue, TypeAdapter, ValidationError

from b_k25_claims import CardFact, Ledger
from display import won
from prompts import DRAFT_SYSTEM, NONE_GIVEN, ShopFacts
from providers import ChatMessage, Sampling

type FactField = Literal["durationMinutes", "capacity", "includedMaterials", "parking", "refundPolicy"]
type RouteKind = Literal["draft", "judgment"]

ROUTE_SAMPLING: Final = Sampling(temperature=0.1, max_tokens=100)
EXTRACT_SAMPLING: Final = Sampling(temperature=0.1, max_tokens=900)
RULE_SAMPLING: Final = Sampling(temperature=0.1, max_tokens=200)
INTERVIEW_SAMPLING: Final = Sampling(temperature=0.1, max_tokens=200)
MAX_ISSUE_CHARS: Final = 30
NAME_PLACEHOLDER: Final = "○○"
JSON_OBJECT: Final = re.compile(r"\{.*\}", re.DOTALL)

PHONE: Final = re.compile(
    (
        r"(?:\+?82[-\s]?)?0?1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"
        r"|0\d{1,2}[-\s.]\d{3,4}[-\s.]\d{4}"
    ),
)

ROUTE_SYSTEM: Final = f"""\
너는 공방 문의를 분류한다. 아래 [근거]에 있는 사실만으로 손님 질문에 답할 수 있는지 판단한다.
[근거]에 없는 가격, 인원 기준, 날짜 예외, 할인은 답할 수 없는 것으로 본다.
답할 수 있으면 {{"route":"draft"}}만 출력한다.
답할 수 없으면 {{"route":"judgment","issue":"<사장님이 정할 쟁점 한 줄, {MAX_ISSUE_CHARS}자 안>"}}만 출력한다.
issue는 명사구로 짧게 쓴다. 예: {{"route":"judgment","issue":"6인 단체, 금요일, 견적 기준?"}}"""

EXTRACT_SYSTEM: Final = """\
아래 [초안]에서 손님에게 약속하거나 알려 주는 숫자와 사실을 모두 뽑는다.
각 항목은 {"kind":"price|seats|date|deposit|fact|rule","text":"초안 속 표현 그대로",
"value":"정규화 값"} 형식이다.
정규화 값은 원 단위 정수(예: 35000), 좌석 정수(예: 2), 날짜 MM-DD(예: 11-28)로 쓴다.
초안에 없는 내용은 만들지 않는다. JSON 배열만 출력한다."""

RULE_SYSTEM: Final = """\
사장님이 손님 질문에 대해 한 답을 다음 답장에서도 쓸 규칙 한 문장으로 바꾼다.
숫자와 조건은 사장님 말 그대로 둔다. 새 조건을 더하지 않는다. 사람 이름을 규칙에 옮기지 않는다.
applies_to에는 수업 목록에 있는 이름을 그대로 쓴다. 수업이 정해지지 않으면 전체라고 쓴다.
{"rule":"<규칙 한 문장>","applies_to":"<수업 이름 또는 전체>"}만 출력한다."""

INTERVIEW_SYSTEM: Final = """\
사장님이 말한 답을 수업 사실 카드의 칸에 넣을 짧은 글로 정리한다.
말한 내용에 없는 사실을 더하지 않는다. 숫자와 조건은 말한 그대로 둔다.
인사말과 머뭇거리는 말은 뺀다. 사람 이름과 전화번호는 쓰지 않는다.
{"value":"<정리한 글>"}만 출력한다."""

INTERVIEW_FIELDS: Final[dict[FactField, str]] = {
    "durationMinutes": "소요 시간", "capacity": "정원", "includedMaterials": "포함 재료와 준비물",
    "parking": "주차", "refundPolicy": "환불 규정",
}

GROUNDED_RULES: Final = f"""\

[근거 있는 답장]
- 답장의 숫자는 [장부], [사실 카드], [내 규칙], 공방 정보에 적힌 값만 씁니다. 그 밖의 숫자는 쓰지 않습니다.
- [장부]의 좌석, 가격, 예약금, 날짜를 그대로 씁니다. [장부]에 없는 숫자는 만들지 않습니다.
- [사실 카드]와 [내 규칙]에 있는 내용은 확인해 보겠다고 미루지 말고 바로 답합니다.
- [사실 카드]의 칸이 '없음'이면 그 내용은 사장님이 확인해서 알려 드린다고 씁니다.
- 손님이 묻지 않은 할인이나 다른 수업 홍보를 넣지 않습니다.
- 위 [말투]의 이름 규칙 대신, 손님 이름은 알려 주지 않으니 부를 때는 '{NAME_PLACEHOLDER} 님'이라고만 씁니다.
  보내기 전에 이름으로 바뀝니다."""


@dataclass(frozen=True, slots=True)
class Route:
    """The routing answer: write a draft, or hand the question to the owner."""

    kind: RouteKind
    issue: str = ""


@dataclass(frozen=True, slots=True)
class RuleSuggestion:
    """The model's reusable sentence and the class it belongs to."""

    rule: str
    applies_to: str


def mask_contacts(text: str) -> str:
    """Hide phone numbers before a text leaves the server."""
    return PHONE.sub("(연락처 가림)", text)


def masked_question(customer: str, subject: str, question: str) -> str:
    """Return the customer's words without the name or phone number the model must not see."""
    text = mask_contacts(f"{subject}\n{question}")
    return text.replace(customer, "손님") if len(customer.strip()) > 1 else text


OBJECT: Final = TypeAdapter(dict[str, JsonValue])


def json_object(raw: str) -> dict[str, JsonValue] | None:
    """Read the first JSON object in a model answer, or nothing when it is malformed."""
    found = JSON_OBJECT.search(raw)
    if found is None:
        return None
    try:
        return OBJECT.validate_json(found.group())
    except ValidationError:
        return None


def parse_route(raw: str) -> Route | None:
    """Read a routing answer; a judgment needs a short issue."""
    answer = json_object(raw)
    if answer is None:
        return None
    if answer.get("route") == "draft":
        return Route("draft")
    issue = answer.get("issue")
    if answer.get("route") != "judgment" or not isinstance(issue, str):
        return None
    issue = " ".join(issue.split())
    if not issue or len(issue) > MAX_ISSUE_CHARS:
        return None
    return Route("judgment", issue)


def parse_rule(raw: str) -> RuleSuggestion | None:
    """Read a rule suggestion."""
    answer = json_object(raw)
    if answer is None:
        return None
    rule, applies_to = answer.get("rule"), answer.get("applies_to")
    if not isinstance(rule, str) or not rule.strip():
        return None
    return RuleSuggestion(" ".join(rule.split()), applies_to.strip() if isinstance(applies_to, str) else "")


def parse_interview(raw: str) -> str | None:
    """Read a cleaned interview value."""
    answer = json_object(raw)
    value = None if answer is None else answer.get("value")
    return " ".join(value.split()) if isinstance(value, str) else None


def bullets(lines: Sequence[str]) -> str:
    """Render lines as a dash list, marking an empty list explicitly."""
    return "\n".join(f"- {line}" for line in lines) or NONE_GIVEN


def card_line(card: CardFact, *, has_session: bool) -> str:
    """Describe one fact card; the ledger's own length and capacity win over the card's."""
    parts: list[str] = []
    if not has_session:
        parts.append(f"소요 시간 {card.duration_minutes}분" if card.duration_minutes else "소요 시간 없음")
        parts.append(f"정원 {card.capacity}명" if card.capacity else "정원 없음")
    parts.append(f"포함 재료와 준비물: {card.included_materials or '없음'}")
    parts.append(f"주차: {card.parking or '없음'}")
    parts.append(f"환불 규정: {card.refund_policy or '없음'}")
    parts.append(f"가격 {won(card.price_won)}" if card.price_won is not None else "가격 없음")
    return f"{card.class_name}: {', '.join(parts)}"


def grounding_text(ledger: Ledger) -> str:
    """Render the ledger, fact cards, and rules as the prompt sections the model may quote."""
    titles = {session.title for session in ledger.sessions}
    sessions = [
        (
            f"{s.title} · {s.label} · 남은 자리 {s.seats_left}명 · 정원 {s.capacity}명"
            f" · 예약금 {won(s.deposit_won)} · {s.duration_minutes}분"
        )
        for s in ledger.sessions
    ]
    cards = [card_line(card, has_session=card.class_name in titles) for card in ledger.cards]
    rules = [f"({rule.class_name or '공방 전체'}) {rule.text}" for rule in ledger.rules]
    return "\n".join([
        "[장부]", bullets(sessions), "", "[사실 카드]", bullets(cards), "", "[내 규칙]", bullets(rules),
    ])


def basis_text(ledger: Ledger, shop: ShopFacts) -> str:
    """Everything a draft may rely on, as one text for the output guard."""
    return "\n".join([shop.text, "문의 관련 사실:", bullets(ledger.facts), grounding_text(ledger)])


def route_messages(ledger: Ledger, shop: ShopFacts, extra: Sequence[str] = ()) -> list[ChatMessage]:
    """Ask whether the facts can answer the customer's question."""
    extras = f"\n{bullets(extra)}" if extra else ""
    user = f"[근거]\n{basis_text(ledger, shop)}{extras}\n\n손님 질문: {ledger.question}"
    return [ChatMessage("system", ROUTE_SYSTEM), ChatMessage("user", user)]


def draft_messages(
    ledger: Ledger, shop: ShopFacts, extra: Sequence[str] = (), *, owner_answer: str = "",
) -> list[ChatMessage]:
    """Ask for a reply that rests only on the ledger, the cards, and the owner's rules."""
    sections = [
        shop.text, "", "문의 관련 사실:", bullets(ledger.facts), "", grounding_text(ledger),
    ]
    if extra:
        sections += ["", "[이번 문의]", bullets(extra)]
    if owner_answer:
        sections += ["", "[이번 문의에 대한 사장님 답]", f"- {owner_answer}"]
    sections += ["", f"손님 문의: {ledger.question}", "", "위 문의에 보낼 답장 초안을 써 주세요."]
    return [ChatMessage("system", DRAFT_SYSTEM + GROUNDED_RULES), ChatMessage("user", "\n".join(sections))]


def extract_messages(draft: str) -> list[ChatMessage]:
    """Ask for the numbers and facts a draft tells the customer."""
    return [ChatMessage("system", EXTRACT_SYSTEM), ChatMessage("user", f"[초안]\n{draft}")]


def rule_messages(issue: str, answer: str, class_names: Sequence[str]) -> list[ChatMessage]:
    """Ask for the owner's answer as one reusable sentence."""
    user = f"쟁점: {issue}\n사장님 답: {answer}\n수업 목록: {', '.join(class_names) or '없음'}"
    return [ChatMessage("system", RULE_SYSTEM), ChatMessage("user", user)]


def interview_messages(field: FactField, answer: str) -> list[ChatMessage]:
    """Ask for a spoken answer as one short card value."""
    return [
        ChatMessage("system", INTERVIEW_SYSTEM),
        ChatMessage("user", f"칸: {INTERVIEW_FIELDS[field]}\n사장님 답: {mask_contacts(answer)}"),
    ]
