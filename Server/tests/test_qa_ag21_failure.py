"""Failure answers: no false claim, no repeated write, no unreadable or unstorable model output."""

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_hcx import WireAnswer, chat_turn
from agent_store import NO_ANSWER
from ai import AskResponse
from tests.agent_core_support import ask, chat_of, says, scalar, set_mode, wants

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
PLAIN = "주문 화면에서 볼 수 있어요."


@pytest.fixture
async def database(database: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncEngine:
    async def answered(body: object, now: object) -> AskResponse:
        del body, now
        return AskResponse(answer=PLAIN, intent="lookup")

    monkeypatch.setattr("agent_run.ask", answered)
    await set_mode(database, "auto")
    return database


@pytest.mark.parametrize(
    "words",
    ["1040 포장 완료로 바꿨어요.", "일정에 넣어 뒀어요.", "입금 확인했어요.", "", "Done at agent_run.py"],
)
async def test_an_unusable_answer_falls_back(database: AsyncEngine, client: AsyncClient, words: str) -> None:
    body = await ask(client, chat_of(says(words)), "1040 포장 끝났어")
    assert (body["status"], body["answer"]) == ("fallback", PLAIN)
    assert await scalar(database, "SELECT error FROM agent_runs") == "empty_answer"


async def test_a_named_doer_is_not_a_claim(database: AsyncEngine, client: AsyncClient) -> None:
    body = await ask(client, chat_of(says("김*연 님이 문의를 남겼어요.")), "새 문의 있어?")
    assert body["answer"] == "김*연 님이 문의를 남겼어요."


async def test_a_plain_answer_never_claims_a_change(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def claimed(body: object, now: object) -> AskResponse:
        del body, now
        return AskResponse(answer="1040 포장 완료 처리했어요.", intent="lookup")

    monkeypatch.setattr("agent_run.ask", claimed)
    body = await ask(client, chat_of(says("")), "1040 포장 끝났어")
    assert "처리했어요" not in str(body["answer"])
    assert body["answer"] != NO_ANSWER


async def test_the_same_write_runs_once(database: AsyncEngine, client: AsyncClient) -> None:
    again = [wants("add_event", title="재고 확인", day="2026-11-20", time="15:00") for _ in range(6)]
    body = await ask(client, chat_of(*again, says("넣었어요.")), "금요일 3시에 재고 확인 일정 넣어줘")
    decisions = [step["decision"] for step in body["steps"]]
    assert decisions[0] == "auto"
    assert set(decisions[1:]) == {"refused"}
    assert await scalar(database, "SELECT count(*) FROM calendar_events WHERE title = '재고 확인'") == 1


async def test_nul_and_nan_never_break_a_run(database: AsyncEngine, client: AsyncClient) -> None:
    raw = (
        '{"result":{"message":{"content":"","toolCalls":[{"id":"a","function":'
        '{"name":"find_orders","arguments":{"query":"a\\u0000b","x":NaN}}}]}}}'
    )
    turn = chat_turn(WireAnswer.model_validate_json(raw))
    body = await ask(client, chat_of(turn, says("주문은\x00 세 건이에요.")), "주문 몇 건이야?")
    assert (body["status"], body["answer"]) == ("done", "주문은 세 건이에요.")
    assert [step["tool"] for step in body["steps"]] == ["find_orders"]
