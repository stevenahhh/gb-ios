"""Undo requests restore persisted state and shared screen counts."""

from dataclasses import dataclass
from typing import Final

import anyio
import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
type Body = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class RoundTrip:
    forward: str
    undo: str
    body: Body
    state: str


ROUND_TRIPS: Final = (
    RoundTrip("/bookings/booking-jieun/confirm-deposit", "/bookings/booking-jieun/undo-deposit", {}, """
        SELECT status, deposit_due_at, deposit_confirmed_at FROM bookings WHERE id = 'booking-jieun'
    """),
    RoundTrip("/orders/order-1042/confirm", "/orders/order-1042/undo-confirm", {}, """
        SELECT o.status, o.confirmed_at, s.id FROM orders o LEFT JOIN shipments s ON s.order_id = o.id
        WHERE o.id = 'order-1042'
    """),
    RoundTrip("/shipments/shipment-order-1040/pack", "/shipments/shipment-order-1040/undo", {}, """
        SELECT status, packed_at FROM shipments WHERE id = 'shipment-order-1040'
    """),
    RoundTrip(
        "/shipments/shipment-order-1041/invoice", "/shipments/shipment-order-1041/undo",
        {"carrier": "택배", "trackingNumber": "123456"}, """
        SELECT status, packed_at, carrier, tracking_number, shipped_at, expected_arrival_on
        FROM shipments WHERE id = 'shipment-order-1041'
    """),
    RoundTrip("/shipments/shipment-order-1038/deliver", "/shipments/shipment-order-1038/undo", {}, """
        SELECT s.status, s.delivered_at, o.status FROM shipments s JOIN orders o ON o.id = s.order_id
        WHERE s.id = 'shipment-order-1038'
    """),
    RoundTrip("/tasks/task-clay/completion", "/tasks/task-clay/undo", {"done": True}, """
        SELECT status, completed_at FROM tasks WHERE id = 'task-clay'
    """),
)


@pytest.mark.parametrize("case", ROUND_TRIPS, ids=lambda case: case.forward)
async def test_undo_round_trip_restores_state_and_screen_counts(
    database: AsyncEngine, client: AsyncClient, case: RoundTrip,
) -> None:
    async with database.connect() as connection:
        initial = (await connection.execute(text(case.state))).one()
    before = (await client.get("/operations")).json()
    today = (await client.get("/today")).json()
    forward = await client.post(case.forward, json={**case.body, "expectedRevision": 0})
    assert forward.status_code == 200, forward.text
    assert forward.json()["undo"] == {"label": "되돌리기", "path": case.undo}
    undone = await client.post(case.undo, json={"expectedRevision": 1})
    assert undone.status_code == 200, undone.text
    assert undone.json()["revision"] == 2
    kind, row_id = undone.json()["kind"], undone.json()["id"]
    detail_path = f"/bookings/{row_id}" if kind == "booking" else f"/cards/{kind}/{row_id}"
    reloaded = (await client.get(detail_path)).json()
    assert reloaded["revision"] == 2
    if kind != "booking":
        assert reloaded == undone.json()
    if case.forward.endswith("/deliver"):
        assert (await client.get("/cards/order/order-1038")).json()["revision"] == 2
    async with database.connect() as connection:
        assert (await connection.execute(text(case.state))).one() == initial
    assert (await client.get("/operations")).json() == before
    after = (await client.get("/today")).json()
    assert after["attentionCount"] == today["attentionCount"]
    assert after["tasks"]["metrics"] == today["tasks"]["metrics"]
    assert after["delivery"]["metrics"] == today["delivery"]["metrics"]


@pytest.mark.parametrize("case", ROUND_TRIPS, ids=lambda case: case.forward)
async def test_stale_undo_preserves_state(
    database: AsyncEngine, client: AsyncClient, case: RoundTrip,
) -> None:
    forward = await client.post(case.forward, json={**case.body, "expectedRevision": 0})
    assert forward.status_code == 200
    before = (await client.get("/today")).json()
    async with database.connect() as connection:
        state = (await connection.execute(text(case.state))).one()
    assert (await client.post(case.undo, json={"expectedRevision": 0})).status_code == 409
    assert (await client.get("/today")).json() == before
    card = forward.json()
    path = f"/bookings/{card['id']}" if card["kind"] == "booking" else f"/cards/{card['kind']}/{card['id']}"
    assert (await client.get(path)).json()["revision"] == 1
    async with database.connect() as connection:
        assert (await connection.execute(text(case.state))).one() == state


@pytest.mark.parametrize("path", [
    "/bookings/booking-jieun/undo-deposit", "/orders/order-1042/undo-confirm",
    "/shipments/shipment-order-1040/undo", "/tasks/task-clay/undo", "/inquiries/inquiry-clay/undo-completion",
])
async def test_invalid_undo_changes_nothing(
    database: AsyncEngine, client: AsyncClient, path: str,
) -> None:
    before = (await client.get("/today")).json()
    assert (await client.post(path, json={"expectedRevision": 0})).status_code == 409
    assert (await client.get("/today")).json() == before


@pytest.mark.parametrize("path", [
    "/bookings/missing/undo-deposit", "/orders/missing/undo-confirm",
    "/shipments/missing/undo", "/tasks/missing/undo", "/inquiries/missing/undo-completion",
])
async def test_missing_undo_is_404(database: AsyncEngine, client: AsyncClient, path: str) -> None:
    assert (await client.post(path, json={"expectedRevision": 0})).status_code == 404


async def test_order_undo_refused_after_packing(database: AsyncEngine, client: AsyncClient) -> None:
    assert (await client.post("/orders/order-1042/confirm", json={"expectedRevision": 0})).status_code == 200
    assert (
        await client.post("/shipments/shipment-order-1042/pack", json={"expectedRevision": 0})
    ).status_code == 200
    before = (await client.get("/shipments")).json()
    assert (
        await client.post("/orders/order-1042/undo-confirm", json={"expectedRevision": 1})
    ).status_code == 409
    assert (await client.get("/shipments")).json() == before
    assert (await client.get("/cards/order/order-1042")).json()["undo"] is None


@pytest.mark.parametrize(("booking_id", "deadline"), [
    ("booking-yuna", "입금 기한 오늘 14:00"), ("booking-sujin", "입금 기한 내일 11:00"),
])
async def test_deposit_undo_requires_money_and_restores_missing_deadline(
    database: AsyncEngine, client: AsyncClient, booking_id: str, deadline: str,
) -> None:
    undone = await client.post(f"/bookings/{booking_id}/undo-deposit", json={"expectedRevision": 0})
    assert undone.status_code == 200
    assert undone.json()["deadline"] == deadline
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE bookings SET deposit_won = 0 WHERE id = 'booking-junho'"))
    assert (await client.get("/bookings/booking-junho")).json()["undo"] is None
    assert (
        await client.post("/bookings/booking-junho/undo-deposit", json={"expectedRevision": 0})
    ).status_code == 409


async def test_reply_completion_undo_keeps_the_text_and_restores_attention(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    before = (await client.get("/operations")).json()["attentionCount"]
    completed = await client.post(
        "/inquiries/inquiry-clay/decision",
        json={"decision": "approve", "draft": "저장한 답변", "expectedRevision": 0},
    )
    assert completed.status_code == 200
    assert (await client.get("/operations")).json()["attentionCount"] == before - 1
    assert (
        await client.post("/inquiries/inquiry-clay/undo-completion", json={"expectedRevision": 0})
    ).status_code == 409
    undone = await client.post("/inquiries/inquiry-clay/undo-completion", json={"expectedRevision": 1})
    assert undone.status_code == 200
    assert (undone.json()["status"], undone.json()["draft"], undone.json()["revision"]) == (
        "pending", "저장한 답변", 2,
    )
    assert (await client.get("/operations")).json()["attentionCount"] == before


@pytest.mark.parametrize("case", ROUND_TRIPS, ids=lambda case: case.forward)
async def test_concurrent_undos_have_exactly_one_winner(
    database: AsyncEngine, client: AsyncClient, case: RoundTrip,
) -> None:
    assert (await client.post(case.forward, json={**case.body, "expectedRevision": 0})).status_code == 200
    statuses: list[int] = []
    start = anyio.Event()

    async def undo() -> None:
        await start.wait()
        statuses.append((await client.post(case.undo, json={"expectedRevision": 1})).status_code)

    async with anyio.create_task_group() as group:
        for _ in range(3):
            group.start_soon(undo)
        start.set()
    assert sorted(statuses) == [200, 409, 409]
