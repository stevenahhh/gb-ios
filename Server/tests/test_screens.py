"""Screen numbers are recomputed from rows and agree across endpoints."""

from typing import Final

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
type Json = dict[str, JsonValue]
TODAY: Final = "2026-11-18"


async def get(client: AsyncClient, path: str, **params: str | int) -> Json:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def displays(metrics: JsonValue) -> dict[str, str]:
    assert isinstance(metrics, list)
    return {item["key"]: item["display"] for item in metrics if isinstance(item, dict)}


async def test_today_numbers_come_from_seeded_rows(database: AsyncEngine, client: AsyncClient) -> None:
    today = await get(client, "/today")
    assert today["date"] == TODAY
    assert displays(today["tasks"]["metrics"]) == {
        "bookedPeople": "8명",
        "newOrders": "3건",
        "shipToday": "2건",
    }
    assert displays(today["delivery"]["metrics"]) == {
        "unshipped": "2건",
        "inTransit": "2건",
        "delivered": "3건",
    }
    assert today["delivery"]["transitSummary"] == "배송 중 2건 · 오늘 도착 1건"
    assert today["attentionCount"] == 7
    assert [group["title"] for group in today["tasks"]["groups"]] == ["예약", "배송", "재료 주문", "할 일"]
    sessions = today["tasks"]["groups"][0]["items"]
    assert sessions
    assert all(item["startsAt"] for item in sessions)


async def test_metric_changes_when_a_row_changes(database: AsyncEngine, client: AsyncClient) -> None:
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE bookings SET party_size = 5 WHERE id = 'booking-eunju'"))
    assert displays((await get(client, "/today"))["tasks"]["metrics"])["bookedPeople"] == "9명"


async def test_attention_counts_match_their_filtered_lists(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    attention = displays((await get(client, "/operations"))["attention"])
    deposits = await get(client, "/bookings", status="deposit_pending")
    shipments = await get(client, "/shipments", status="scheduled")
    inquiries = await get(client, "/channels", section="inquiries")
    assert attention["depositPending"] == f"{deposits['total']}건"
    assert attention["unshipped"] == f"{shipments['total']}건"
    assert attention["pendingInquiries"] == f"{len(inquiries['inquiries'])}건"


async def test_operations_rate_and_comparison_are_defined(database: AsyncEngine, client: AsyncClient) -> None:
    period = (await get(client, "/operations", month="2026-11"))["period"]
    assert period["total"] == 11 + 8 + 5 + 3
    assert period["handled"] == 9 + 5 + 3 + 0
    assert period["rateDisplay"] == "63%"
    assert period["comparisons"] == [
        {"label": "예약 지난달 대비", "display": "+267%"},
        {"label": "주문 지난달 대비", "display": "+300%"},
    ]
    empty = (await get(client, "/operations", month="2026-01"))["period"]
    assert empty["ratePercent"] is None
    assert empty["comparisons"][0]["display"] == "—"


@pytest.mark.parametrize("month", ["2026-13", "november"])
async def test_invalid_month_is_rejected(database: AsyncEngine, client: AsyncClient, month: str) -> None:
    assert (await client.get("/operations", params={"month": month})).status_code == 422


async def test_calendar_markers_equal_agenda_rows(database: AsyncEngine, client: AsyncClient) -> None:
    body = await get(client, "/calendar", start="2026-11-01", end="2026-11-30")
    day = next(item for item in body["days"] if item["date"] == TODAY)
    assert {event["kind"]: event["count"] for event in day["events"]} == {
        "booking": 2,
        "order": 3,
        "delivery": 3,
        "todo": 3,
    }
    for item in body["days"]:
        assert sum(event["count"] for event in item["events"]) == len(item["items"])
    too_long = await client.get("/calendar", params={"start": "2026-01-01", "end": "2026-06-01"})
    assert too_long.status_code == 422


@pytest.mark.parametrize(
    ("path", "params", "expected"),
    [
        ("/bookings", {"q": "물레"}, ["원데이 물레 체험"]),
        ("/bookings", {"q": "100%"}, []),
        ("/orders", {"q": "#1043"}, ["핸드메이드 미니 화병"]),
        (
            "/shipments",
            {"status": "in_transit", "sort": "latest"},
            ["핸드메이드 커피잔", "도자기 찬기 3종 세트"],
        ),
        ("/shipments", {"q": "없는주문"}, []),
    ],
)
async def test_filter_and_search_run_on_the_server(
    database: AsyncEngine,
    client: AsyncClient,
    path: str,
    params: dict[str, str],
    expected: list[str],
) -> None:
    assert [item["title"] for item in (await get(client, path, **params))["items"]] == expected


async def test_sort_and_pagination_cover_every_row_once(database: AsyncEngine, client: AsyncClient) -> None:
    first = await get(client, "/orders", limit=4, sort="oldest")
    second = await get(client, "/orders", limit=4, offset=4, sort="oldest")
    third = await get(client, "/orders", limit=4, offset=8, sort="oldest")
    ids = [item["id"] for page in (first, second, third) for item in page["items"]]
    assert first["hasMore"] is True
    assert third["hasMore"] is False
    assert len(ids) == len(set(ids)) == first["total"] == 10
    assert first["items"][0]["id"] == "order-1021"


async def test_unfinished_shipments_sort_before_delivered_ones(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    items = (await get(client, "/shipments"))["items"]
    statuses = [item["status"]["text"] for item in items]
    assert statuses[:2] == ["배송 중", "배송 중"]
    assert statuses[-3:] == ["배송 완료", "배송 완료", "배송 완료"]


async def test_unknown_filter_is_rejected(database: AsyncEngine, client: AsyncClient) -> None:
    assert (await client.get("/bookings", params={"status": "paid"})).status_code == 422


async def test_channels_report_real_connection_state(database: AsyncEngine, client: AsyncClient) -> None:
    page = await get(client, "/channels", section="channels")
    assert displays(page["metrics"])["channels"] == "3개"
    channel = next(item for item in page["items"] if item["id"] == "channel-naver-store")
    assert channel["status"] == {"text": "아직 연결 안 됨", "tone": "neutral"}
    assert channel["lines"][1] == "오늘 들어온 주문 3건 · 받은 돈 126,000원"
    assert channel["deadline"] == "문의 3건이 답을 기다려요"
