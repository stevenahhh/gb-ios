"""The classifier's JSON decides the intent; anything unreadable falls back to keywords."""

from collections.abc import Sequence

import pytest
from fastapi import HTTPException

from intents import Reading, classify, fallback
from prompts import HistoryTurn, Intent
from providers import ChatMessage, Sampling

pytestmark = pytest.mark.anyio
DRAFTED = (
    HistoryTurn(role="owner", text="주말 클래스 홍보 글 써줘"),
    HistoryTurn(role="assistant", text="이번 주말 머그컵 클래스에 놀러 오세요."),
)


def answering(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    async def chat(_messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        return raw

    monkeypatch.setattr("intents.chat", chat)


async def test_fenced_json_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = '{"intent": "advise", "confidence": 0.8, "reading": "홍보 방법 조언"}'
    answering(monkeypatch, f"```json\n{raw}\n```")
    assert await classify("어떻게 홍보하면 좋을까?", ()) == Reading("advise", "model", 0.8, "홍보 방법 조언")


@pytest.mark.parametrize(
    "raw", ["", "advise", '{"intent": "dance", "confidence": 0.9}', '{"intent": "advise", "confidence": 3}'],
)
async def test_malformed_output_falls_back(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    answering(monkeypatch, raw)
    assert await classify("주말 홍보 글 써줘", ()) == Reading("write", "fallback")


async def test_upstream_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    async def chat(_messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        raise HTTPException(502, "upstream service failed")

    monkeypatch.setattr("intents.chat", chat)
    assert await classify("포장 완료 처리해줘", ()) == Reading("act", "fallback")


@pytest.mark.parametrize(("history", "expected"), [((), "clarify"), (DRAFTED, "edit")])
async def test_edit_needs_an_earlier_answer(
    monkeypatch: pytest.MonkeyPatch, history: tuple[HistoryTurn, ...], expected: Intent,
) -> None:
    answering(monkeypatch, '{"intent": "edit", "confidence": 0.6, "reading": ""}')
    assert (await classify("그거 바꿔줘", history)).intent == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("포장 완료 처리해줘", "act"), ("예약 확정해줘", "act"), ("공지 문자 써줘", "write"),
        ("오늘 뭐 해?", "lookup"),
    ],
)
def test_fallback_keywords(question: str, expected: Intent) -> None:
    assert fallback(question) == expected
