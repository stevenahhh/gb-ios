"""Runs, mapping, and the collector API against real PostgreSQL."""

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Final

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from collectors.http import Gateway
from collectors.registry import ALL_SOURCES, STATUS_SOURCES
from collectors.routes import collector_gateway
from collectors.runner import Outcome, run_all, run_source
from main import app
from seed import apply_seed
from tests.collector_fakes import FEED, FakeNetwork, json_reply, reply
from tests.conftest import NOW, downgrade, upgrade

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
API: Final = "/external/v1"
TOKEN: Final = "synthetic-instagram-token"  # noqa: S105 - not a credential.


def clock() -> datetime:
    return NOW


@pytest.fixture(autouse=True)
def net(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeNetwork]:
    for name in (
        "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID",
        "NAVER_COMMERCE_CLIENT_ID", "NAVER_COMMERCE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    network = FakeNetwork()
    app.dependency_overrides[collector_gateway] = lambda: network.gateway
    yield network
    _ = app.dependency_overrides.pop(collector_gateway, None)


@pytest.fixture
def store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAVER_COMMERCE_CLIENT_ID", "synthetic-id")
    monkeypatch.setenv("NAVER_COMMERCE_CLIENT_SECRET", "$2a$04$abcdefghijklmnopqrstuv")


def serve_store(net: FakeNetwork, *, status: str = "PAYED", answered: bool = False) -> None:
    order = {
        "order": {
            "orderDate": "2026-11-18T09:00:00.000+09:00", "ordererId": "buyer", "ordererName": "김바다",
        },
        "productOrder": {
            "productOrderId": "2026111800000001", "productName": "조약돌 접시", "quantity": 2,
            "productOrderStatus": status, "placeOrderStatus": "NOT_YET", "totalPaymentAmount": 31000,
        },
    }
    inquiry = {
        "inquiryNo": 3, "title": "배송 문의", "inquiryContent": "언제 오나요?", "answered": answered,
        "answerContent": "내일 보내요." if answered else None, "orderId": "1",
        "inquiryRegistrationDateTime": "2026-11-18T10:00:00.000+09:00",
        "customerId": "buyer", "customerName": "김바다",
    }
    changed = {"lastChangeStatuses": [{"productOrderId": "2026111800000001"}]}
    net.answers = {
        f"{API}/oauth2/token": json_reply({"access_token": "synthetic-access"}),
        f"{API}/pay-order/seller/product-orders/last-changed-statuses": json_reply({"data": changed}),
        f"{API}/pay-order/seller/product-orders/query": json_reply({"data": [order]}),
        f"{API}/pay-user/inquiries": json_reply({"content": [inquiry], "last": True}),
        f"{API}/contents/qnas": json_reply({"contents": [], "last": True}),
    }


async def run_store(gateway: Gateway) -> Outcome:
    return await run_source("naver_smartstore", gateway, clock)


async def ids(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as connection:
        return set((await connection.scalars(text(f"SELECT id FROM {table}"))).all())  # noqa: S608


async def test_status_has_the_exact_contract(database: AsyncEngine, client: AsyncClient) -> None:
    body = (await client.get("/collectors/status")).json()
    assert set(body) == {"sources", "updated_at"}
    assert body["updated_at"] == "2026-11-18T11:00:00+09:00"
    assert [source["id"] for source in body["sources"]] == list(STATUS_SOURCES)
    for source in body["sources"]:
        assert set(source) == {"id", "name", "state", "last_collected_at", "collected_today", "message"}
        assert source["state"] == "needs_connection"
        assert source["last_collected_at"] is None
        assert source["collected_today"] == 0
        assert source["message"]


async def test_run_without_setup_makes_no_request(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork,
) -> None:
    for source in ALL_SOURCES:
        response = await client.post(f"/collectors/{source}/run")
        assert response.status_code == 200
        assert response.json()["source"]["state"] == "needs_connection"
    assert net.requests == []


async def test_robots_refusal_reaches_the_status_endpoint(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork,
) -> None:
    net.answers = {"/robots.txt": reply(text="User-agent: *\nDisallow: /"), "/studio.xml": reply(text=FEED)}
    saved = await client.put("/collectors/naver_blog/config", json={"blog_id": "studio", "enabled": True})
    assert saved.json() == {"source": "naver_blog", "config": {"blog_id": "studio", "enabled": True}}
    assert (await client.post("/collectors/naver_blog/run")).json()["error"] == "needs_connection"
    blog = (await client.get("/collectors/status")).json()["sources"][2]
    assert (blog["id"], blog["state"]) == ("naver_blog", "needs_connection")
    assert "정책" in blog["message"]
    assert net.paths == ["/robots.txt"]
    assert (await client.get("/collectors/items")).json()["total"] == 0


async def test_allowed_feed_is_stored_once_and_shown_as_channel_activity(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork,
) -> None:
    net.answers = {"/robots.txt": reply(404), "/studio.xml": reply(text=FEED)}
    _ = await client.put("/collectors/naver_blog/config", json={"blog_id": "studio", "enabled": True})
    first = (await client.post("/collectors/naver_blog/run")).json()
    second = (await client.post("/collectors/naver_blog/run")).json()
    assert (first["collected"], first["inserted"], first["mapped"]) == (2, 2, 2)
    assert (second["collected"], second["inserted"], second["mapped"]) == (2, 0, 0)
    assert second["source"]["collected_today"] == 2
    assert second["source"]["last_collected_at"] == "2026-11-18T11:00:00+09:00"
    page = (await client.get("/collectors/items?source=naver_blog&limit=1")).json()
    assert (page["total"], page["has_more"], len(page["items"])) == (2, True, 1)
    assert "raw" not in page["items"][0]
    cards = (await client.get("/channels?section=channels")).json()["items"]
    card = next(each for each in cards if each["id"] == "channel-naver-blog")
    assert card["status"]["text"] == "연결됨"
    assert "최근 7일 새 글 1개" in card["lines"]


@pytest.mark.usefixtures("store_env")
async def test_store_data_reaches_existing_screens_once(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork,
) -> None:
    serve_store(net)
    first, second = await run_store(net.gateway), await run_store(net.gateway)
    assert (first.state, first.inserted, first.mapped) == ("idle", 2, 2)
    assert (second.inserted, second.mapped) == (0, 0)
    orders = (await client.get("/orders?limit=100")).json()["items"]
    mine = [order for order in orders if order["title"] == "조약돌 접시"]
    assert [order["id"] for order in mine] == ["order-collected-naver_smartstore-order-2026111800000001"]
    inquiries = (await client.get("/inquiries")).json()
    assert [entry["question"] for entry in inquiries] == ["언제 오나요?"]
    assert inquiries[0]["facts"] == ["문의 채널 · 네이버 스마트스토어"]
    activities = (await client.get("/assistant/activities")).json()
    assert not any(entry["targetId"] == inquiries[0]["id"] for entry in activities)


@pytest.mark.usefixtures("store_env")
async def test_real_rows_retire_only_untouched_seed_rows(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork,
) -> None:
    before_orders, before_inquiries = await ids(database, "orders"), await ids(database, "inquiries")
    edited = await client.patch(
        "/inquiries/inquiry-clay/draft", json={"draft": "사장님 답변", "expectedRevision": 0},
    )
    confirmed = await client.post("/orders/order-1042/confirm", json={"expectedRevision": 0})
    assert (edited.status_code, confirmed.status_code) == (200, 200)
    assert {"order-1043", "inquiry-group"} <= before_orders | before_inquiries
    serve_store(net)
    _ = await run_store(net.gateway)
    assert await ids(database, "inquiries") == {
        "inquiry-clay", "inquiry-collected-naver_smartstore-inquiry-3",
    }
    assert await ids(database, "orders") == {
        "order-1042", "order-collected-naver_smartstore-order-2026111800000001",
    }
    async with database.begin() as connection:
        assert await apply_seed(connection, NOW.date()) == 0
    assert "inquiry-group" not in await ids(database, "inquiries")
    assert "order-1043" not in await ids(database, "orders")


@pytest.mark.usefixtures("store_env")
async def test_owner_changes_survive_later_store_changes(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork,
) -> None:
    serve_store(net)
    _ = await run_store(net.gateway)
    order_id = "order-collected-naver_smartstore-order-2026111800000001"
    inquiry_id = "inquiry-collected-naver_smartstore-inquiry-3"
    confirmed = await client.post(f"/orders/{order_id}/confirm", json={"expectedRevision": 0})
    edited = await client.patch(
        f"/inquiries/{inquiry_id}/draft", json={"draft": "사장님 초안", "expectedRevision": 0},
    )
    assert (confirmed.status_code, edited.status_code) == (200, 200)
    serve_store(net, status="CANCELED", answered=True)
    assert (await run_store(net.gateway)).mapped == 2
    async with database.connect() as connection:
        order = await connection.scalar(text("SELECT status FROM orders WHERE id = :id"), {"id": order_id})
        row = (await connection.execute(
            text("SELECT status, draft, revision FROM inquiries WHERE id = :id"), {"id": inquiry_id},
        )).one()
    assert order == "processing"
    assert row == ("pending", "사장님 초안", 1)


@pytest.mark.usefixtures("store_env")
async def test_untouched_rows_follow_the_store(database: AsyncEngine, net: FakeNetwork) -> None:
    serve_store(net)
    _ = await run_store(net.gateway)
    serve_store(net, status="CANCELED", answered=True)
    _ = await run_store(net.gateway)
    async with database.connect() as connection:
        order = await connection.scalar(text("SELECT status FROM orders WHERE id LIKE 'order-collected-%'"))
        row = (await connection.execute(
            text("SELECT status, draft, revision FROM inquiries WHERE id LIKE 'inquiry-collected-%'"),
        )).one()
    assert order == "cancelled"
    assert row == ("approved", "내일 보내요.", 1)


async def test_instagram_questions_become_inquiries_and_praise_does_not(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("INSTAGRAM_USER_ID", "17")
    posted = "2026-11-17T01:00:00+0000"
    media = {"id": "5", "caption": "새 컵", "username": "studio", "timestamp": posted, "comments_count": 3}
    comments = [
        {"id": "1", "text": "얼마예요?", "username": "guest", "timestamp": posted},
        {"id": "2", "text": "예뻐요", "username": "guest", "timestamp": posted},
        {"id": "3", "text": "예약 가능해요", "username": "studio", "timestamp": posted},
    ]
    net.answers = {
        "/v27.0/17/media": json_reply({"data": [media]}),
        "/v27.0/5/comments": json_reply({"data": comments}),
        "/v27.0/17/insights": json_reply({"data": []}),
    }
    assert (await client.post("/collectors/instagram/run")).json()["inserted"] == 4
    collected = [row for row in await ids(database, "inquiries") if row.startswith("inquiry-collected-")]
    assert collected == ["inquiry-collected-instagram-comment-1"]
    assert "inquiry-group" in await ids(database, "inquiries")


async def test_one_failing_source_does_not_stop_the_others(
    database: AsyncEngine, net: FakeNetwork, monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("INSTAGRAM_USER_ID", "17")
    monkeypatch.setenv("NAVER_COMMERCE_CLIENT_ID", "synthetic-id")
    monkeypatch.setenv("NAVER_COMMERCE_CLIENT_SECRET", "$2a$04$abcdefghijklmnopqrstuv")
    serve_store(net)
    net.answers["/v27.0/17/media"] = reply(text=f"broken {TOKEN}")
    logging.getLogger("roundup").propagate = True
    with caplog.at_level(logging.DEBUG):
        outcomes = await run_all(ALL_SOURCES, net.gateway, clock)
    logging.getLogger("roundup").propagate = False
    states = {outcome.source: (outcome.state, outcome.error) for outcome in outcomes}
    assert states["instagram"] == ("error", "malformed")
    assert states["naver_smartstore"] == ("idle", None)
    body = (await client.get("/collectors/status")).text
    async with database.connect() as connection:
        runs = (await connection.execute(text("SELECT source_id, status, error FROM collector_runs"))).all()
    assert set(runs) == {("instagram", "failed", "malformed"), ("naver_smartstore", "succeeded", None)}
    roundup = "".join(str(record.__dict__) for record in caplog.records if record.name.startswith("roundup"))
    assert TOKEN not in body + str(runs) + roundup


async def test_refused_credentials_disconnect_the_channel(
    database: AsyncEngine, net: FakeNetwork, store_env: None,
) -> None:
    serve_store(net)
    _ = await run_store(net.gateway)
    net.answers[f"{API}/oauth2/token"] = json_reply({}, 401)
    assert (await run_store(net.gateway)).state == "needs_connection"
    async with database.connect() as connection:
        connected = await connection.scalar(
            text("SELECT connection FROM channels WHERE id = 'channel-naver-store'"),
        )
    assert connected == "not_connected"


@pytest.mark.parametrize(("age", "expected"), [(timedelta(minutes=1), 409), (timedelta(hours=1), 200)])
async def test_live_run_is_refused_and_an_abandoned_one_is_replaced(
    database: AsyncEngine, client: AsyncClient, net: FakeNetwork, age: timedelta, expected: int,
) -> None:
    net.answers = {"/robots.txt": reply(404), "/studio.xml": reply(text=FEED)}
    _ = await client.put("/collectors/naver_blog/config", json={"blog_id": "studio", "enabled": True})
    async with database.begin() as connection:
        _ = await connection.execute(
            text("UPDATE collector_sources SET state = 'collecting', last_run_at = :at"), {"at": NOW - age},
        )
        _ = await connection.execute(
            text(
                "INSERT INTO collector_runs (id, source_id, status, started_at) "
                "VALUES ('old', 'naver_blog', 'running', :at)",
            ),
            {"at": NOW - age},
        )
    shown = (await client.get("/collectors/status")).json()["sources"][2]["state"]
    assert shown == ("collecting" if expected == 409 else "error")
    assert (await client.post("/collectors/naver_blog/run")).status_code == expected
    async with database.connect() as connection:
        old = await connection.scalar(text("SELECT status FROM collector_runs WHERE id = 'old'"))
    assert old == ("running" if expected == 409 else "failed")


@pytest.mark.parametrize(
    ("source", "config"),
    [
        ("naver_blog", {"blog_id": "../etc"}),
        ("naver_blog", {"blog_id": "a" * 41}),
        ("naver_blog", {"blog_id": "studio", "enabled": "yes"}),
        ("instagram", {"access_token": "secret-value"}),
        ("naver_smartstore", {"client_secret": "secret-value"}),
        ("unknown", {}),
    ],
)
async def test_invalid_config_is_refused_without_echo(
    database: AsyncEngine, client: AsyncClient, source: str, config: dict[str, str],
) -> None:
    response = await client.put(f"/collectors/{source}/config", json=config)
    assert response.status_code == 422
    assert "secret-value" not in response.text
    assert await ids(database, "collector_sources") == set()


@pytest.mark.parametrize("query", ["source=unknown", "limit=0", "limit=101", "offset=-1"])
async def test_item_queries_are_bounded(database: AsyncEngine, client: AsyncClient, query: str) -> None:
    assert (await client.get(f"/collectors/items?{query}")).status_code == 422


@pytest.mark.usefixtures("store_env")
async def test_downgrade_keeps_mapped_work_and_upgrade_restores_tables(
    database: AsyncEngine, net: FakeNetwork,
) -> None:
    serve_store(net)
    _ = await run_store(net.gateway)
    await downgrade(database, "0004")
    assert "order-collected-naver_smartstore-order-2026111800000001" in await ids(database, "orders")
    async with database.connect() as connection:
        assert await connection.scalar(text("SELECT to_regclass('collected_items')")) is None
    await upgrade(database)
    assert await ids(database, "collected_items") == set()
