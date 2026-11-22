"""A name the owner says for the first time stays hidden wherever a record cuts the turn."""

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.agent_core_support import ask, chat_of, rows, says, set_mode, wants

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


async def test_a_new_name_cut_from_its_honorific_stays_hidden(
    database: AsyncEngine,
    client: AsyncClient,
) -> None:
    await set_mode(database, "auto")
    call = wants(
        "create_booking", session="원데이 물레 체험", day="2026-11-21", time="11:00",
        customer_name="강*봄", party_size=2,
    )
    body = await ask(
        client, chat_of(call, says("네")), "토요일 11시 원데이 물레 체험에 강새봄 님 두 명 예약해 줘",
    )
    [step] = body["steps"]
    assert step["decision"] == "auto"
    records = await rows(database, "SELECT args, target_label, evidence, result FROM agent_steps")
    assert "강새봄" not in str(records)
    assert await rows(database, "SELECT name FROM customers WHERE name = '강새봄'") == [("강새봄",)]
