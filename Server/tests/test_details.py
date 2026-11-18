"""Redesigned screen read contracts over the real migrated PostgreSQL schema."""

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


async def test_booking_detail_and_structured_card(database: AsyncEngine, client: AsyncClient) -> None:
    detail = await client.get("/bookings/booking-yuna")
    assert detail.status_code == 200
    body = detail.json()
    assert body == {
        "id": "booking-yuna", "title": "나만의 머그컵 만들기",
        "status": {"text": "확정", "tone": "done"}, "schedule": "11월 18일 수 · 14:00–16:00",  # noqa: RUF001
        "customer": "한*나", "people": 2, "minutes": 120, "source": "네이버 예약",
        "seatNote": "남은 자리 2개", "depositDisplay": "20,000원", "depositConfirmed": True,
        "depositDeadline": None, "revision": 0, "action": None,
        "undo": {"label": "되돌리기", "path": "/bookings/booking-yuna/undo-deposit"},
        "session": {"id": "session-today-afternoon", "isDone": False, "revision": 0},
    }
    cards = (await client.get("/bookings", params={"session": "session-today-afternoon"})).json()["items"]
    assert {card["id"] for card in cards} == {"booking-yuna", "booking-junho"}
    card = next(card for card in cards if card["id"] == "booking-yuna")
    assert card["booking"] == {
        "day": "2026-11-18", "dayTitle": "11월 18일 수요일", "time": "14:00",
        "customer": "한*나", "people": 2,
    }
    assert card["draft"] is None
    pending = (await client.get("/bookings/booking-jieun")).json()
    assert (pending["depositConfirmed"], pending["depositDeadline"]) == (False, "입금 기한 오늘 18:00")
    assert pending["action"]["code"] == "confirmDeposit"
    assert pending["undo"] is None
    finished = (await client.get("/bookings", params={"session": "session-today-morning"})).json()["items"][0]
    assert (finished["status"], finished["tag"]) == ({"text": "수업 완료", "tone": "done"}, "확정")
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE bookings SET channel_id = NULL WHERE id = 'booking-yuna'"))
    assert (await client.get("/bookings/booking-yuna")).json()["source"] == "직접 등록"


async def test_session_detail_active_booking_order_and_completion(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "UPDATE bookings SET created_at = '2026-11-01T00:00:00+09:00' WHERE id = 'booking-yuna'",
        ))
        _ = await connection.execute(text(
            "UPDATE bookings SET status = 'cancelled' WHERE id = 'booking-junho'",
        ))
    response = await client.get("/class-sessions/session-today-afternoon")
    assert response.status_code == 200
    assert response.json()["bookingIds"] == ["booking-yuna"]
    assert (response.json()["isDone"], response.json()["revision"]) == (False, 0)
    assert (
        await client.post(
            "/class-sessions/session-today-afternoon/completion", json={"done": True, "expectedRevision": 0},
        )
    ).status_code == 200
    after = (await client.get("/class-sessions/session-today-afternoon")).json()
    assert (after["isDone"], after["revision"]) == (True, 1)
    assert (await client.get("/bookings/booking-yuna")).json()["session"]["isDone"] is True
    calendar = (await client.get("/calendar", params={"start": "2026-11-18", "end": "2026-11-18"})).json()
    rows = {item["id"]: item for item in calendar["days"][0]["items"]}
    assert rows["session:session-today-afternoon"]["isDone"] is True
    assert rows["task:task-clay"]["isDone"] is False
    assert rows["order:order-1042"]["isDone"] is None
    assert (
        await client.post("/tasks/task-clay/completion", json={"done": True, "expectedRevision": 0})
    ).status_code == 200
    calendar = (await client.get("/calendar", params={"start": "2026-11-18", "end": "2026-11-18"})).json()
    task = next(item for item in calendar["days"][0]["items"] if item["id"] == "task:task-clay")
    assert task["isDone"] is True


@pytest.mark.parametrize(("kind", "row_id", "collection"), [
    ("order", "order-1040", "/orders"), ("shipment", "shipment-order-1040", "/shipments"),
])
async def test_card_detail_reuses_collection_contract(
    database: AsyncEngine, client: AsyncClient, kind: str, row_id: str, collection: str,
) -> None:
    response = await client.get(f"/cards/{kind}/{row_id}")
    assert response.status_code == 200
    expected = next(item for item in (await client.get(collection)).json()["items"] if item["id"] == row_id)
    assert response.json() == expected
    assert response.json()["booking"] is None
    assert response.json()["draft"] is None


@pytest.mark.parametrize("path", [
    "/bookings/missing", "/class-sessions/missing", "/cards/order/missing",
    "/cards/shipment/missing", "/cards/task/missing",
])
async def test_missing_detail_is_404(database: AsyncEngine, client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 404


async def test_unknown_card_kind_is_422(database: AsyncEngine, client: AsyncClient) -> None:
    assert (await client.get("/cards/content/draft-weekend-class")).status_code == 422
    assert (await client.get("/bookings", params={"session": "missing"})).json()["items"] == []


async def test_custom_operations_uses_inclusive_range_and_equal_previous_period(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    response = await client.get("/operations", params={"start": "2026-11-18", "end": "2026-11-19"})
    assert response.status_code == 200
    period = response.json()["period"]
    assert period["month"] == {"key": "custom", "title": "선택 기간", "range": "11.18 – 11.19"}  # noqa: RUF001
    assert {m["key"]: m["value"] for m in period["metrics"]} == {
        "bookings": 4, "orders": 3, "shipments": 2, "drafts": 2,
    }
    assert (period["total"], period["handled"]) == (12, 3)
    assert period["comparisons"] == [
        {"label": "예약 이전 기간 대비", "display": "+300%"},
        {"label": "주문 이전 기간 대비", "display": "+0%"},
    ]
    one_day = (await client.get(
        "/operations", params={"start": "2026-11-19", "end": "2026-11-19"},
    )).json()["period"]
    assert next(m["value"] for m in one_day["metrics"] if m["key"] == "bookings") == 1
    limit = await client.get("/operations", params={"start": "2026-01-01", "end": "2027-01-01"})
    assert limit.status_code == 200
    empty = (await client.get(
        "/operations", params={"start": "2026-11-03", "end": "2026-11-12"},
    )).json()["period"]
    assert empty["month"] == {
        "key": "custom", "title": "선택 기간", "range": "11.03 – 11.12",  # noqa: RUF001
    }
    assert (empty["total"], empty["ratePercent"]) == (0, None)


@pytest.mark.parametrize("params", [
    {"start": "2026-11-03"}, {"end": "2026-11-12"},
    {"month": "2026-11", "start": "2026-11-03", "end": "2026-11-12"},
    {"start": "2026-11-12", "end": "2026-11-03"},
    {"start": "2026-01-01", "end": "2027-01-02"},
    {"start": "wrong", "end": "2026-11-12"},
])
async def test_invalid_custom_operations_is_422(
    database: AsyncEngine, client: AsyncClient, params: dict[str, str],
) -> None:
    assert (await client.get("/operations", params=params)).status_code == 422
