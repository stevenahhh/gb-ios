"""Fact cards are stored per class with optimistic revisions; interview answers are read, never stored."""

from collections.abc import Sequence

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from b_k25 import card_id_for
from providers import ChatMessage, Sampling
from tests.conftest import downgrade, upgrade

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
type Body = dict[str, JsonValue]
MUG = "나만의 머그컵 만들기"
WEEKEND = "주말 도자기 클래스"


class FakeChat:
    """Answers every model call with the next reply and keeps what it was asked."""

    def __init__(self, *replies: str) -> None:
        self.replies: list[str] = list(replies)
        self.calls: list[Sequence[ChatMessage]] = []

    async def __call__(self, messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


def card_body(class_name: str = MUG, revision: int = 0, **values: JsonValue) -> Body:
    body: Body = {"className": class_name, "expectedRevision": revision}
    return body | values


async def test_every_class_of_the_calendar_is_listed_before_it_has_a_card(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    response = await client.get("/fact-cards")
    assert response.status_code == 200
    rows = response.json()
    assert [row["className"] for row in rows] == [
        MUG, WEEKEND, "원데이 물레 체험", "도자기 원데이 클래스",
    ]
    assert {row["filledCount"] for row in rows} == {0}
    assert {row["revision"] for row in rows} == {0}
    assert rows[0]["id"] == card_id_for(MUG)


async def test_a_card_is_created_then_revised(database: AsyncEngine, client: AsyncClient) -> None:
    card = card_id_for(MUG)
    created = await client.put(f"/fact-cards/{card}", json=card_body(
        durationMinutes=120, capacity=6, parking="건물 뒤 공영주차장", priceWon=38000,
    ))
    assert created.status_code == 200
    assert created.json()["revision"] == 1
    assert created.json()["filledCount"] == 3
    updated = await client.put(f"/fact-cards/{card}", json=card_body(
        revision=1, durationMinutes=150, includedMaterials="  앞치마와 도구  ",
    ))
    body = updated.json()
    assert updated.status_code == 200
    assert (body["durationMinutes"], body["parking"], body["priceWon"]) == (150, None, None)
    assert (body["includedMaterials"], body["revision"]) == ("앞치마와 도구", 2)
    listed = next(row for row in (await client.get("/fact-cards")).json() if row["className"] == MUG)
    assert (listed["filledCount"], listed["revision"]) == (2, 2)


async def test_card_detail_returns_an_empty_card_for_a_class_without_one(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    empty = await client.get(f"/fact-cards/{card_id_for(WEEKEND)}")
    assert empty.json()["className"] == WEEKEND
    assert (empty.json()["revision"], empty.json()["rules"]) == (0, [])
    assert (await client.get("/fact-cards/card-missing")).status_code == 404


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (card_body(revision=1), 409),
        (card_body(class_name=WEEKEND), 422),
        (card_body(priceWon=0), 422),
        (card_body(capacity=-1), 422),
        (card_body(durationMinutes=99999), 422),
        (card_body(unknownField="x"), 422),
    ],
)
async def test_invalid_card_writes_are_refused(
    database: AsyncEngine, client: AsyncClient, body: Body, status: int,
) -> None:
    response = await client.put(f"/fact-cards/{card_id_for(MUG)}", json=body)
    assert response.status_code == status
    assert (await client.get("/fact-cards")).json()[0]["revision"] == 0


async def test_a_stale_card_revision_changes_nothing(database: AsyncEngine, client: AsyncClient) -> None:
    card = card_id_for(MUG)
    assert (await client.put(f"/fact-cards/{card}", json=card_body(capacity=6))).status_code == 200
    assert (await client.put(f"/fact-cards/{card}", json=card_body(capacity=8))).status_code == 409
    assert (await client.get(f"/fact-cards/{card}")).json()["capacity"] == 6


async def test_interview_numbers_need_no_model_and_unclear_ones_stay_empty(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeChat()
    monkeypatch.setattr("b_k25.chat", fake)
    clear = await client.post(f"/fact-cards/{card_id_for(MUG)}/interview", json={
        "field": "durationMinutes", "answer": "두 시간 반 정도요",
    })
    assert clear.json() == {"field": "durationMinutes", "value": "150", "confidence": "clear"}
    unclear = await client.post(f"/fact-cards/{card_id_for(MUG)}/interview", json={
        "field": "capacity", "answer": "그때그때 달라요",
    })
    assert unclear.json() == {"field": "capacity", "value": "", "confidence": "unclear"}
    assert fake.calls == []


async def test_interview_text_is_tidied_unless_the_model_changes_a_number(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeChat('{"value": "앞치마와 도구는 공방에서 드려요."}', '{"value": "수업 3일 전까지 환불돼요."}')
    monkeypatch.setattr("b_k25.chat", fake)
    card = card_id_for(MUG)
    tidied = await client.post(f"/fact-cards/{card}/interview", json={
        "field": "includedMaterials", "answer": "음 앞치마랑 도구는 저희가 다 드려요 010-1234-5678",
    })
    assert tidied.json()["value"] == "앞치마와 도구는 공방에서 드려요."
    assert "(연락처 가림)" in fake.calls[0][1].content
    changed = await client.post(f"/fact-cards/{card}/interview", json={
        "field": "refundPolicy", "answer": "수업 2일 전까지 환불돼요",
    })
    assert changed.json()["value"] == "수업 2일 전까지 환불돼요"


async def test_interview_survives_a_model_failure(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(_messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        from fastapi import HTTPException  # noqa: PLC0415

        raise HTTPException(502, "upstream service failed")

    monkeypatch.setattr("b_k25.chat", broken)
    response = await client.post(f"/fact-cards/{card_id_for(MUG)}/interview", json={
        "field": "parking", "answer": " 건물 뒤   공영주차장 ",
    })
    assert response.json() == {"field": "parking", "value": "건물 뒤 공영주차장", "confidence": "clear"}


async def test_fact_cards_need_the_api_key(database: AsyncEngine, client: AsyncClient) -> None:
    response = await client.get("/fact-cards", headers={"X-Roundup-Key": "wrong"})
    assert response.status_code == 401


async def test_downgrade_drops_only_the_added_tables(database: AsyncEngine) -> None:
    await downgrade(database, "0004")
    async with database.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM inquiries")) == 3
        missing = await connection.scalar(text("SELECT to_regclass('class_fact_cards')"))
        assert missing is None
    await upgrade(database)
    async with database.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM class_fact_cards")) == 0
