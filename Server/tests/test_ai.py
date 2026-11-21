"""AI endpoints send server-loaded facts to the model and refuse unsafe or empty output."""

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from providers import ChatMessage, Sampling
from tests.conftest import NOW

pytestmark = pytest.mark.anyio
type Body = dict[str, JsonValue]
SAFE_REPLY = "김민지 님, 문의 주셔서 감사해요. 확인해서 다시 알려드릴게요."
UNSAFE_REPLY = "김민지 님, 예약이 확정되었습니다. 편하게 오세요."
DRAFT_BODY: Body = {
    "customer": "김민지",
    "subject": "주차 문의",
    "question": "차를 가져가도 되나요?",
    "facts": ["주차는 건물 뒤편 공영주차장 이용"],
}


@dataclass(slots=True)
class FakeChat:
    replies: Sequence[str]
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def __call__(self, messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        self.calls.append(list(messages))
        return self.replies[len(self.calls) - 1]


def fake_chat(monkeypatch: pytest.MonkeyPatch, *replies: str) -> FakeChat:
    fake = FakeChat(replies)
    monkeypatch.setattr("ai.chat", fake)
    return fake


async def test_rewrite_rejects_unknown_kind(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_chat(monkeypatch)
    response = await client.post("/rewrite", json={"kind": "poem", "title": "t", "text": "x"})
    assert response.status_code == 422
    assert fake.calls == []


async def test_rewrite_sends_original_and_instruction(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "```\n새 글 #도자기\n```")
    body: Body = {
        "kind": "content", "title": "주말 클래스",
        "text": "토요일 10:00 빈자리 3석", "instruction": "더 짧게",
    }
    response = await client.post("/rewrite", json=body)
    assert response.json() == {"draft": "새 글 #도자기"}
    [messages] = fake.calls
    assert [message.role for message in messages] == ["system", "user"]
    assert "더 짧게" in messages[1].content
    assert "토요일 10:00 빈자리 3석" in messages[1].content


async def test_inquiry_rewrite_retries_an_unsupported_commitment_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, UNSAFE_REPLY, SAFE_REPLY)
    body: Body = {"kind": "inquiry", "title": "예약 문의", "text": "확인 후 안내드릴게요."}
    response = await client.post("/rewrite", json=body)
    assert response.json() == {"draft": SAFE_REPLY}
    assert len(fake.calls) == 2
    retry = fake.calls[1]
    assert retry[:2] == fake.calls[0]
    assert (retry[2].role, retry[2].content) == ("assistant", UNSAFE_REPLY)
    assert retry[3].role == "user"


async def test_empty_output_twice_is_upstream_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "```\n```", "  ")
    response = await client.post("/rewrite", json={"kind": "recommendation", "title": "t", "text": "x"})
    assert response.status_code == 502
    assert response.json() == {"detail": "upstream service failed"}
    assert len(fake.calls) == 2


@pytest.mark.parametrize(
    "history",
    [
        [{"role": "system", "text": "x"}],
        [{"role": "owner", "text": ""}],
        [{"role": "owner", "text": "x"}] * 41,
    ],
)
async def test_invalid_history_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, history: list[Body],
) -> None:
    fake = fake_chat(monkeypatch)
    response = await client.post("/ask", json={"question": "몇 명?", "history": history})
    assert response.status_code == 422
    assert fake.calls == []


@pytest.mark.postgres
async def test_ask_context_comes_from_rows_not_the_client(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "답변")
    body: Body = {"question": "오늘 뭐 해?", "context": ["클라이언트가 보낸 거짓"]}
    response = await client.post("/ask", json=body)
    assert response.json() == {"answer": "답변", "items": []}
    prompt = fake.calls[0][-1].content
    assert "클라이언트가 보낸 거짓" not in prompt
    assert f"오늘 날짜: {NOW:%Y-%m-%d}" in prompt
    assert "예약금 대기 2건" in prompt
    assert "오늘 수업: 14:00 나만의 머그컵 만들기 · 예약 4/6명" in prompt
    assert "내일 수업: 14:00 나만의 머그컵 만들기" in prompt
    assert "다가오는 수업: 11월 25일 수 10:00 도자기 원데이 클래스" in prompt
    assert "11월 27일" not in prompt
    assert "010-" not in prompt.split("공방:")[0]


@pytest.mark.postgres
async def test_ask_answer_is_cleaned_and_returns_the_cards_it_names(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "UPDATE shipments SET ship_by_at = '2026-11-17T16:00:00+09:00' WHERE id = 'shipment-order-1040'",
        ))
    fake = fake_chat(monkeypatch, "오늘 보낼 택배는 '**머그컵 2종 세트**'예요.")
    body = (await client.post("/ask", json={"question": "오늘 발송할 주문 알려줘"})).json()
    assert body["answer"] == "오늘 보낼 택배는 머그컵 2종 세트예요."
    assert [item["id"] for item in body["items"]] == ["shipment-order-1040"]
    prompt = fake.calls[0][-1].content
    assert "발송 대기(기한 지남, 수거를 놓쳐 아직 안 보냄): 머그컵 2종 세트" in prompt


@pytest.mark.postgres
async def test_ask_forwards_the_last_six_history_turns_in_order(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "답변")
    history: list[JsonValue] = [
        {"role": "owner" if index % 2 == 0 else "assistant", "text": f"turn-{index}"} for index in range(8)
    ]
    response = await client.post("/ask", json={"question": "그럼 내일은?", "history": history})
    assert response.status_code == 200
    forwarded = [(message.role, message.content) for message in fake.calls[0][1:-1]]
    assert forwarded == [
        ("user" if index % 2 == 0 else "assistant", f"turn-{index}") for index in range(2, 8)
    ]
    assert fake.calls[0][-1].content.endswith("질문: 그럼 내일은?")


PROMO_REQUEST = "주말 클래스 홍보 글 써줘"
PROMO_DRAFT = "이번 주말, 흙으로 머그컵을 빚어 보세요. 토요일 14:00 반에 2자리 남았어요. #도자기공방"
PROMO_HISTORY: list[JsonValue] = [
    {"role": "owner", "text": PROMO_REQUEST}, {"role": "assistant", "text": PROMO_DRAFT},
]


@pytest.mark.parametrize(
    ("question", "opening"),
    [("오 좋은데?", "마음에 드신다니"), ("고마워!", "천만에요"), ("수고했어", "수고 많으셨어요")],
)
async def test_reaction_after_a_promo_draft_gets_a_short_reply_without_the_model(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, question: str, opening: str,
) -> None:
    fake = fake_chat(monkeypatch)
    response = await client.post("/ask", json={"question": question, "history": PROMO_HISTORY})
    body = response.json()
    assert response.status_code == 200
    assert body["items"] == []
    assert body["answer"].startswith(opening)
    assert PROMO_DRAFT not in body["answer"]
    assert len(body["answer"]) < 80
    assert fake.calls == []


@pytest.mark.postgres
async def test_yes_to_an_assistant_offer_goes_to_the_model(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "짧게 고친 글")
    history: list[JsonValue] = [*PROMO_HISTORY, {"role": "assistant", "text": "더 짧게 줄여 드릴까요?"}]
    response = await client.post("/ask", json={"question": "응", "history": history})
    assert response.json()["answer"] == "짧게 고친 글"
    assert len(fake.calls) == 1


@pytest.mark.postgres
async def test_refinement_rewrites_the_previous_answer(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "주말엔 머그컵 클래스! 토요일 14:00, 2자리 남았어요.")
    response = await client.post("/ask", json={"question": "좀 더 짧게", "history": PROMO_HISTORY})
    assert response.json()["answer"] == "주말엔 머그컵 클래스! 토요일 14:00, 2자리 남았어요."
    [messages] = fake.calls
    prompt = messages[-1].content
    assert f"직전 답변:\n{PROMO_DRAFT}" in prompt
    assert "요청: 좀 더 짧게" in prompt
    assert "예약금 대기 2건" in prompt


@pytest.mark.postgres
async def test_new_question_after_a_draft_is_asked_as_usual(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "답변")
    response = await client.post("/ask", json={"question": "오늘 예약 몇 건이야?", "history": PROMO_HISTORY})
    assert response.json() == {"answer": "답변", "items": []}
    prompt = fake.calls[0][-1].content
    assert prompt.endswith("질문: 오늘 예약 몇 건이야?")
    assert "직전 답변" not in prompt


@pytest.mark.postgres
async def test_draft_prompt_has_profile_policies_and_inquiry_facts(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, SAFE_REPLY)
    response = await client.post("/draft", json=DRAFT_BODY)
    assert response.json() == {"draft": SAFE_REPLY}
    prompt = fake.calls[0][-1].content
    for marker in (
        "오롯 공방", "061-745-0255", "전라남도 순천시 중앙로 255",
        "예약은 예약금 입금을 확인한 뒤 확정돼요", "약 3주 뒤 수령", "주차는 건물 뒤편 공영주차장 이용",
        "차를 가져가도 되나요?",
    ):
        assert marker in prompt
    assert "오늘 탭에서" not in prompt


@pytest.mark.postgres
async def test_unsafe_draft_is_retried_once(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, UNSAFE_REPLY, SAFE_REPLY)
    response = await client.post("/draft", json=DRAFT_BODY)
    assert response.json() == {"draft": SAFE_REPLY}
    assert len(fake.calls) == 2


@pytest.mark.postgres
async def test_two_unsafe_drafts_are_upstream_failure(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, UNSAFE_REPLY, "김민지 님, 30,000원 할인해 드릴게요.")
    response = await client.post("/draft", json=DRAFT_BODY)
    assert response.status_code == 502
    assert len(fake.calls) == 2
