"""Every HyperCLOVA X prompt and the message lists built from request facts."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field

from providers import ChatMessage, Sampling

type Speaker = Literal["owner", "assistant"]
type RewriteKind = Literal["content", "recommendation", "inquiry"]

DRAFT_SAMPLING: Final = Sampling(temperature=0.3, max_tokens=500)
ASK_SAMPLING: Final = Sampling(temperature=0.2, max_tokens=600)
REWRITE_SAMPLING: Final = Sampling(temperature=0.5, max_tokens=600)
HISTORY_TURNS: Final = 6
NONE_GIVEN: Final = "- (없음)"

DRAFT_SYSTEM: Final = """\
당신은 작은 공방의 사장님을 대신해 손님 문의에 보낼 답장 초안을 쓰는 비서입니다.
초안은 사장님이 읽고 고친 뒤 직접 보냅니다.

[말투]
- 손님에게 쓰는 따뜻하고 정중한 해요체로 씁니다.
- "~해요", "~드릴게요", "~있어요"처럼 끝맺고 합니다체와 섞지 않습니다.
- 손님은 "<이름> 님"으로 부릅니다. [이름] 같은 자리표시자는 쓰지 않습니다.
- 공방이 직접 말하는 1인칭으로 씁니다. '사장님께 문의하신 뒤'처럼 사장님을 3인칭으로 부르지 않습니다.

[구성] 한 문단, 3~5문장
1. 인사 한 문장
2. 질문에 대한 직접 답
3. 손님이 해야 할 다음 행동 안내 (필요할 때만)
4. 짧은 맺음 한 문장

[근거]
- '문의 관련 사실', '공방 정보', '운영 규정'에 적힌 내용만 씁니다.
- 답에 필요한 사실이 자료에 없으면 추측하지 말고 "확인해서 다시 알려드릴게요."라고 씁니다.
- 가격, 시간, 날짜, 인원은 자료에 있는 값만 그대로 옮깁니다. 새 숫자를 만들지 않습니다.
- 자료에 없는 예약 확정, 환불, 할인, 결제 완료, 배송이나 도착 날짜를 약속하지 않습니다.

[형식]
- 답장 본문만 씁니다. "답변:" 같은 머리말, 마크다운, 목록, 이모지, 따옴표를 쓰지 않습니다.

[예시 1: 필요한 사실이 있을 때]
문의 관련 사실:
- 주차는 건물 뒤편 공영주차장 이용, 1시간 무료
손님: 김하늘
문의: 차를 가져가도 되나요?
답장: 김하늘 님, 문의 주셔서 감사해요. 차를 가져오시면 공방 건물 뒤편 공영주차장을 이용하시면 돼요. \
주차는 1시간까지 무료예요. 조심히 오세요.

[예시 2: 필요한 사실이 없을 때]
문의 관련 사실:
- 원데이 클래스 소요 시간 90분
손님: 박서준
문의: 6살 아이도 같이 들을 수 있나요?
답장: 박서준 님, 문의 주셔서 감사해요. 원데이 클래스는 90분 동안 진행돼요. \
6살 아이와 함께 참여할 수 있는지는 확인해서 다시 알려드릴게요. 조금만 기다려 주세요."""

ASK_SYSTEM: Final = """\
당신은 작은 공방 사장님의 업무 비서입니다. 사장님에게 친근한 해요체로 답합니다.

[근거]
- 마지막 메시지의 '현재 공방 현황'만 근거로 답합니다.
- 이전 대화는 질문의 뜻을 파악하는 데만 쓰고, 숫자와 일정은 늘 최신 현황에서 다시 확인합니다.
- 현황으로 답할 수 없으면 "지금 데이터로는 알 수 없어요."라고 말하고 확인할 수 있는 화면을 알려 줍니다.
- 건수를 물으면 현황에 있는 항목을 정확히 셉니다. 현황에 없는 항목을 만들지 않습니다.
- '기한 지남'으로 표시된 발송 건은 수거를 놓친 것이니 오늘 수거할 건과 나눠서 말합니다.

[형식]
- 첫 문장에 바로 답합니다.
- 항목을 나열할 때는 "· "로 시작하는 짧은 줄을 최대 3줄까지 씁니다.
- 항목이 더 있으면 마지막 줄 뒤에 "외 N건"이라고 덧붙입니다.
- '~습니다', '~입니다' 같은 합쇼체는 쓰지 않습니다.
- 마크다운 기호(#, **, - 목록), 따옴표 강조, 이모지는 쓰지 않습니다.

[글쓰기 요청]
- 홍보 글이나 안내 문자를 써 달라고 하면 요청한 글을 바로 씁니다.
- 글에는 현황에 있는 사실(수업명, 날짜, 시간, 남은 자리, 공방 정보)만 넣고, 줄 수 제한은 따르지 않습니다.

[하지 않는 일]
- 예약 확정, 답장 발송, 결제, 주문 처리, 게시를 했다고 말하지 않습니다. 당신에게는 실행 권한이 없습니다.
- 사장님이 직접 처리할 화면을 안내합니다. 오늘 할 일과 대기 건은 '오늘', 수업과 일정은 '캘린더', \
예약·주문·배송·문의 처리는 '운영', 공방 정보와 규정 수정은 '설정' 화면입니다."""

REWRITE_RULES: Final = """\
당신은 작은 공방 사장님의 글을 다듬는 편집자입니다.

[공통 규칙]
- 원문에 있는 사실, 숫자, 날짜, 시간, 가격, 이름은 하나도 빼거나 바꾸지 않습니다.
- 원문에 없는 사실을 더하지 않습니다.
- '요청 사항'이 있으면 그대로 따릅니다. 다만 사실을 지키는 규칙이 먼저입니다.
- 다듬은 글 본문만 씁니다. 머리말, 설명, 마크다운, 따옴표, 이모지를 쓰지 않습니다."""

REWRITE_PURPOSES: Final[dict[RewriteKind, str]] = {
    "content": """\
[이번 글: SNS·스토어 홍보 글]
- 첫 문장을 손님의 눈길을 끄는 문장으로 바꾸고 짧은 문장으로 읽기 쉽게 씁니다.
- 따뜻한 해요체로 3~6문장을 씁니다.
- 글 끝에 해시태그를 최대 3개까지 붙일 수 있습니다.""",
    "recommendation": """\
[이번 글: 사장님용 실행 제안]
- 무엇을, 언제, 왜 하면 좋은지 해요체 2~3문장으로 짧고 구체적으로 씁니다.
- 해시태그와 홍보 문구는 쓰지 않습니다.""",
    "inquiry": """\
[이번 글: 손님 문의 답장]
- 따뜻하고 정중한 해요체로 인사, 답, 다음 행동 안내, 맺음 순서의 3~5문장을 씁니다.
- 공방이 직접 말하는 1인칭으로 씁니다. '사장님께 문의하신 뒤'처럼 사장님을 3인칭으로 부르지 않습니다.
- 원문에 없는 예약 확정, 환불, 할인, 결제 완료, 날짜를 약속하지 않습니다.
- 해시태그는 쓰지 않습니다.""",
}

RETRY_EMPTY: Final = "방금 응답이 비어 있었어요. 같은 규칙을 지켜 본문만 다시 써 주세요."
RETRY_UNSUPPORTED: Final = (
    "방금 답장에 자료로 뒷받침되지 않는 내용이 있어 쓸 수 없어요: {problems}. "
    '자료에 없는 약속, 금액, 날짜는 빼고, 필요하면 "확인해서 다시 알려드릴게요."라고 쓰세요. '
    "같은 규칙을 지켜 답장 본문만 다시 써 주세요."
)


class HistoryTurn(BaseModel):
    """One earlier turn of the owner's conversation with the assistant."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    role: Speaker
    text: str = Field(min_length=1, max_length=2000)


@dataclass(frozen=True, slots=True)
class Policy:
    """One owner-written rule."""

    title: str
    body: str


@dataclass(frozen=True, slots=True)
class Workshop:
    """The workshop profile customers may be told about."""

    name: str
    phone: str
    address: str
    description: str


@dataclass(frozen=True, slots=True)
class ShopFacts:
    """Profile and policies read from PostgreSQL for a reply draft."""

    workshop: Workshop | None
    policies: tuple[Policy, ...]

    @property
    def text(self) -> str:
        """Render the facts as prompt sections."""
        profile = (
            [
                f"- 이름: {self.workshop.name}", f"- 전화: {self.workshop.phone}",
                f"- 주소: {self.workshop.address}", f"- 소개: {self.workshop.description}",
            ]
            if self.workshop is not None else [NONE_GIVEN]
        )
        rules = [f"- {policy.title}: {policy.body}" for policy in self.policies] or [NONE_GIVEN]
        return "\n".join(["공방 정보:", *profile, "", "운영 규정:", *rules])


@dataclass(frozen=True, slots=True)
class Inquiry:
    """A customer's question and the facts recorded on it."""

    customer: str
    subject: str
    question: str
    facts: tuple[str, ...]


def bullets(lines: Sequence[str]) -> str:
    """Render lines as a dash list, marking an empty list explicitly."""
    return "\n".join(f"- {line}" for line in lines) or NONE_GIVEN


def draft_messages(inquiry: Inquiry, shop: ShopFacts) -> list[ChatMessage]:
    """Build the reply-draft conversation."""
    user = (
        f"{shop.text}\n\n문의 관련 사실:\n{bullets(inquiry.facts)}\n\n"
        f"손님: {inquiry.customer}\n제목: {inquiry.subject}\n문의: {inquiry.question}\n\n"
        "위 문의에 보낼 답장 초안을 써 주세요."
    )
    return [ChatMessage("system", DRAFT_SYSTEM), ChatMessage("user", user)]


def history_message(turn: HistoryTurn) -> ChatMessage:
    """Map an app conversation turn to a model role."""
    match turn.role:
        case "owner":
            return ChatMessage("user", turn.text)
        case "assistant":
            return ChatMessage("assistant", turn.text)
        case _:
            assert_never(turn.role)


def ask_messages(context: Sequence[str], history: Sequence[HistoryTurn], question: str) -> list[ChatMessage]:
    """Build the owner conversation; only the newest turns are kept."""
    recent = [history_message(turn) for turn in history[-HISTORY_TURNS:]] if history else []
    user = f"현재 공방 현황:\n{bullets(context)}\n\n질문: {question}"
    return [ChatMessage("system", ASK_SYSTEM), *recent, ChatMessage("user", user)]


def rewrite_messages(kind: RewriteKind, original: tuple[str, str], instruction: str) -> list[ChatMessage]:
    """Build a rewrite of a titled text for its purpose."""
    title, text = original
    request = instruction.strip() or "없음. 사실은 그대로 두고 더 읽기 좋게 다듬어 주세요."
    user = f"제목: {title}\n\n원문:\n{text}\n\n요청 사항: {request}"
    system = f"{REWRITE_RULES}\n\n{REWRITE_PURPOSES[kind]}"
    return [ChatMessage("system", system), ChatMessage("user", user)]


def retry_message(problems: Sequence[str]) -> ChatMessage:
    """Explain which unsupported content made the previous reply unusable."""
    return ChatMessage("user", RETRY_UNSUPPORTED.format(problems=", ".join(problems)))
