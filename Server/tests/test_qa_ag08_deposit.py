"""Deposits and bookings run by themselves only on a plain, complete statement about that customer."""

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from ai import AskResponse
from tests.agent_core_support import Body, ask, chat_of, rows, says, set_mode, wants

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
BOOKING: Body = {
    "session": "주말 도자기 클래스", "day": "2026-11-21", "time": "10:00", "customer_name": "강새봄",
    "party_size": 1,
}


@pytest.fixture
async def shop(database: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncEngine:
    async def answered(body: JsonValue, now: JsonValue) -> AskResponse:
        del body, now
        return AskResponse(answer="읽어서 알려 드릴게요.", intent="lookup")

    monkeypatch.setattr("agent_run.ask", answered)
    await set_mode(database, "auto")
    return database


@pytest.mark.parametrize(
    ("words", "decision"),
    [
        ("최민우 님 30,000원 들어왔어", "auto"),
        ("최민우 님 3만 들어왔어", "auto"),
        ("최민우 님이 저한테 30,000원 보냈어요", "auto"),
        ("최민우 님 20,000 들어왔어", "proposed"),
        ("최민우 님 ２００００원 들어왔어", "proposed"),
        ("최민우 님한테 30,000원 보냈어", "proposed"),
        ("최민우 님 예약금 30,000원 환불했어", "proposed"),
        ("최민우 님 예약금 일부만 들어왔어", "proposed"),
        ("최민우 님이 30,000원 보냈대", "proposed"),
        ("박지은 님 예약금 30,000원 들어왔어. 최민우 님은 확인 중", "proposed"),
    ],
)
async def test_a_deposit_needs_a_plain_payment_of_its_amount(
    shop: AsyncEngine, client: AsyncClient, words: str, decision: str,
) -> None:
    body = await ask(client, chat_of(wants("confirm_deposit", booking="최민우"), says("네")), words)
    [step] = body["steps"]
    assert step["decision"] == decision, step["reason"]
    [(status,)] = await rows(shop, "SELECT status FROM bookings WHERE id = 'booking-minwoo'")
    assert status == ("confirmed" if decision == "auto" else "deposit_pending")


@pytest.mark.parametrize(
    "words",
    [
        "토요일 10시 주말 도자기 클래스에 강새봄 님 1명 예약 취소해 줘",
        "토요일 10시 주말 도자기 클래스 강새봄 님 예약 1명으로 변경해 줘",
        "토요일 10시 주말 도자기 클래스에 강새봄 님 성인 1명 아이 2명 예약해 줘",
    ],
)
async def test_a_cancelled_changed_or_larger_party_is_not_booked(
    shop: AsyncEngine, client: AsyncClient, words: str,
) -> None:
    body = await ask(client, chat_of(wants("create_booking", **BOOKING), says("네")), words)
    [step] = body["steps"]
    assert step["decision"] == "proposed", step["reason"]
    assert await rows(shop, "SELECT count(*) FROM customers WHERE name = '강새봄'") == [(0,)]
