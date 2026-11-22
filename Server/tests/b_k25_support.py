"""Shared helpers of the grounded reply tests: a scripted model and the customer's inquiry."""

from collections.abc import Sequence
from typing import Final

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from providers import ChatMessage, Sampling

GROUNDED: Final = "inquiry-weekend"
CONTROL: Final = "inquiry-paste"
QUESTION: Final = "토요일 주말 클래스 두 명 가능해요? 가격도 알려 주세요. 제 번호는 010-1234-5678이에요."


class ScriptedModel:
    """Answers routing, drafting, extraction, and rule calls by what the system prompt asks for."""

    def __init__(self) -> None:
        self.route: str = '{"route":"draft"}'
        self.drafts: list[str] = []
        self.claims: str = "[]"
        self.rule: str = ""
        self.prompts: list[str] = []
        self.routes: int = 0

    async def __call__(self, messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        self.prompts += [message.content for message in messages]
        system = messages[0].content
        if system.startswith("너는 공방 문의를 분류한다"):
            self.routes += 1
            return self.route
        if system.startswith("아래 [초안]에서"):
            return self.claims
        if system.startswith("사장님이 손님 질문에 대해 한 답을"):
            return self.rule
        return self.drafts.pop(0)


def scripted(monkeypatch: pytest.MonkeyPatch) -> ScriptedModel:
    """Replace every model call of the reply engine with one scripted model."""
    fake = ScriptedModel()
    for target in ("ai.chat", "b_k25_engine.chat", "b_k25_judgments.chat"):
        monkeypatch.setattr(target, fake)
    return fake


async def add_inquiry(database: AsyncEngine, inquiry_id: str) -> None:
    """Insert one waiting inquiry whose arm follows from its id."""
    async with database.begin() as connection:
        _ = await connection.execute(
            text(
                "INSERT INTO inquiries (id, customer, subject, question, facts, draft, status, revision,"
                " received_at) VALUES (:id, '이서준', '주말 클래스', :question, ARRAY['안내 · 앞치마 제공'],"
                " '', 'pending', 0, now())",
            ),
            {"id": inquiry_id, "question": QUESTION},
        )
