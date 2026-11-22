"""Redesigned screen read contracts over the real migrated PostgreSQL schema."""

import re

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
        "session": {
            "id": "session-today-afternoon", "isDone": False, "revision": 0,
            "startsAt": "2026-11-18T14:00:00+09:00",
        },
        "depositDue": None,
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
    assert (pending["depositConfirmed"], pending["depositDeadline"]) == (False, "입금 마감 오늘 18:00")
    assert pending["action"]["code"] == "confirmDeposit"
    assert pending["undo"] is None
    finished = (await client.get("/bookings", params={"session": "session-today-morning"})).json()["items"][0]
    assert (finished["status"], finished["tag"]) == ({"text": "수업 완료", "tone": "done"}, "확정")
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE bookings SET channel_id = NULL WHERE id = 'booking-yuna'"))
    assert (await client.get("/bookings/booking-yuna")).json()["source"] == "직접 입력"


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
    # Migrated inquiries carry the wall-clock insert time; pin them to the fixed test day.
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE inquiries SET received_at = '2026-11-18T09:00:00+09:00'"))
    response = await client.get("/operations", params={"start": "2026-11-18", "end": "2026-11-19"})
    assert response.status_code == 200
    period = response.json()["period"]
    assert period["month"] == {"key": "custom", "title": "선택 기간", "range": "11.18 – 11.19"}  # noqa: RUF001
    assert {m["key"]: m["value"] for m in period["metrics"]} == {
        "bookings": 4, "orders": 3, "shipments": 2, "inquiries": 3,
    }
    assert (period["total"], period["handled"]) == (12, 3)
    assert period["comparisons"] == [
        {"label": "예약 지난 기간 대비", "display": "+300%"},
        {"label": "주문 지난 기간 대비", "display": "+0%"},
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


async def test_operations_numbers_explain_themselves(database: AsyncEngine, client: AsyncClient) -> None:
    body = (await client.get("/operations", params={"month": "2026-11"})).json()
    assert {m["key"]: m["detail"] for m in body["period"]["metrics"]} == {
        "bookings": "지난달보다 +8건", "orders": "지난달보다 +6건",
        "shipments": "발송 대기 2건", "inquiries": "답장 못 한 문의 3건",
    }
    custom = (await client.get("/operations", params={"start": "2026-11-18", "end": "2026-11-19"})).json()
    assert custom["period"]["metrics"][0]["detail"] == "지난 기간보다 +3건"
    attention = {m["key"]: m["detail"] for m in body["attention"]}
    deposits = (await client.get("/bookings", params={"status": "deposit_pending"})).json()["total"]
    assert attention["depositPending"].endswith(f"님 외 {deposits - 1}명")
    assert attention["pendingInquiries"] == "비서가 쓴 초안 3건 있어요"
    assert attention["unshipped"].endswith("택배 수거")
    async with database.begin() as connection:
        _ = await connection.execute(
            text("UPDATE bookings SET status = 'confirmed' WHERE status = 'deposit_pending'"),
        )
        _ = await connection.execute(text("UPDATE inquiries SET draft = '' WHERE status = 'pending'"))
    cleared = {m["key"]: m["detail"] for m in (await client.get("/operations")).json()["attention"]}
    assert (cleared["depositPending"], cleared["pendingInquiries"]) == (None, None)


async def test_calendar_rows_carry_timeline_facts(database: AsyncEngine, client: AsyncClient) -> None:
    async def november() -> list[dict[str, object]]:
        response = await client.get("/calendar", params={"start": "2026-11-01", "end": "2026-11-30"})
        return response.json()["days"]

    def row(days: list[dict[str, object]], row_id: str) -> dict[str, object]:
        return next(item for day in days for item in day["items"] if item["id"] == row_id)

    days = await november()
    for day in days:
        all_day = [item["time"] == "종일" for item in day["items"]]
        assert all_day == sorted(all_day, reverse=True)
    tasks = [item for day in days for item in day["items"] if item["id"].startswith("task:")]
    assert tasks
    assert all(item["kind"] == "todo" for item in tasks)
    session = row(days, "session:session-today-afternoon")
    assert session["minutes"] == 120
    assert re.fullmatch(r".\*. 님( 외 \d+명)?", session["subject"])
    order = row(days, "order:order-1042")
    assert order["minutes"] is None
    assert order["amountWon"] > 0
    assert row(days, "task:task-clay")["revision"] == 0
    assert (
        await client.post("/tasks/task-clay/completion", json={"done": True, "expectedRevision": 0})
    ).status_code == 200
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "UPDATE bookings SET status = 'cancelled' WHERE session_id = 'session-today-afternoon'",
        ))
    days = await november()
    assert row(days, "task:task-clay")["revision"] == 1
    assert row(days, "session:session-today-afternoon")["subject"] == "아직 예약한 분이 없어요"


async def test_order_and_shipment_cards_share_fulfilment_progress(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    steps = ["결제", "주문 확인", "포장", "발송", "배송 완료"]
    order = (await client.get("/cards/order/order-1042")).json()
    assert order["progress"] == {"steps": steps, "current": 1}
    assert [field["label"] for field in order["fields"]] == ["주문자", "수량", "결제금액"]
    assert order["source"]
    assert (await client.post("/orders/order-1042/confirm", json={"expectedRevision": 0})).status_code == 200
    assert (await client.get("/cards/order/order-1042")).json()["progress"]["current"] == 2
    base = "/shipments/shipment-order-1040"
    assert (await client.get("/cards/shipment/shipment-order-1040")).json()["progress"]["current"] == 2
    assert (await client.post(f"{base}/pack", json={"expectedRevision": 0})).status_code == 200
    packed = (await client.get("/cards/shipment/shipment-order-1040")).json()
    assert packed["progress"]["current"] == 3
    assert "송장" not in [field["label"] for field in packed["fields"]]
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE orders SET status = 'cancelled' WHERE id = 'order-1044'"))
    assert (await client.get("/cards/order/order-1044")).json()["progress"] is None


async def test_deadlines_are_sent_as_moments(database: AsyncEngine, client: AsyncClient) -> None:
    shipments = (await client.get("/shipments", params={"status": "scheduled"})).json()["items"]
    pickup = shipments[0]["due"]
    assert (pickup["suffix"], pickup["missed"]) == (" 택배 수거", "수거 놓침")
    assert re.fullmatch(r"2026-\d\d-\d\dT\d\d:\d\d:00\+09:00", pickup["at"])
    deposit = (await client.get("/bookings/booking-jieun")).json()
    assert deposit["depositDue"]["prefix"] == "입금 마감"
    today = (await client.get("/today")).json()
    ship_today = next(m for m in today["tasks"]["metrics"] if m["key"] == "shipToday")["value"]
    operations = (await client.get("/operations")).json()
    unshipped = next(m for m in operations["attention"] if m["key"] == "unshipped")
    assert unshipped["value"] == ship_today
    assert unshipped["due"]["missed"] == "수거 놓침"
    group = next(g for g in today["tasks"]["groups"] if g["kind"] == "delivery")
    assert len(group["items"]) == ship_today
    assert all(item["due"] for item in group["items"])


async def test_calendar_carries_overdue_parcels_and_move_targets(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "UPDATE shipments SET ship_by_at = ship_by_at - interval '1 day' "
            "WHERE id = 'shipment-order-1040'",
        ))
    body = (await client.get("/calendar", params={"start": "2026-11-18", "end": "2026-11-18"})).json()
    assert [item["id"] for item in body["overdueShipments"]] == ["shipment:shipment-order-1040"]
    assert body["overdueShipments"][0]["isDone"] is False
    created = (await client.post(
        "/calendar/events", json={"title": "공방 대청소", "startsAt": "2026-11-17T10:00:00+09:00"},
    )).json()
    assert created["revision"] == 0
    event_id = created["id"].removeprefix("event:")
    moved = await client.post(
        f"/calendar/events/{event_id}/move",
        json={"startsAt": "2026-11-18T10:00:00+09:00", "expectedRevision": 0},
    )
    assert moved.json() == {"revision": 1}
    stale = await client.post(
        f"/calendar/events/{event_id}/move",
        json={"startsAt": "2026-11-17T10:00:00+09:00", "expectedRevision": 0},
    )
    assert stale.status_code == 409
    response = await client.get("/calendar", params={"start": "2026-11-18", "end": "2026-11-18"})
    assert any(item["id"] == f"event:{event_id}" for item in response.json()["days"][0]["items"])


async def test_open_task_moves_and_done_task_refuses(database: AsyncEngine, client: AsyncClient) -> None:
    moved = await client.post(
        "/tasks/task-clay/move", json={"dueAt": "2026-11-19T12:00:00+09:00", "expectedRevision": 0},
    )
    assert moved.json() == {"revision": 1}
    row = next(
        item for day in (await client.get(
            "/calendar", params={"start": "2026-11-19", "end": "2026-11-19"},
        )).json()["days"] for item in day["items"] if item["id"] == "task:task-clay"
    )
    assert (row["time"], row["revision"]) == ("12:00", 1)
    assert (
        await client.post("/tasks/task-clay/completion", json={"done": True, "expectedRevision": 1})
    ).status_code == 200
    refused = await client.post(
        "/tasks/task-clay/move", json={"dueAt": "2026-11-20T12:00:00+09:00", "expectedRevision": 2},
    )
    assert refused.status_code == 409


async def test_headline_facts_follow_rows(database: AsyncEngine, client: AsyncClient) -> None:
    facts = (await client.get("/today")).json()["headline"]
    assert facts["sessions"]
    assert {"title", "startsAt", "minutes", "isDone"} <= set(facts["sessions"][0])
    before = facts["overdueShipments"]
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "UPDATE shipments SET ship_by_at = '2026-11-18T09:00:00+09:00' WHERE id = 'shipment-order-1040'",
        ))
    after = (await client.get("/today")).json()["headline"]
    assert after["overdueShipments"] == before + 1
