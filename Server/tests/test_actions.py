"""Every action persists, returns new state, and refuses stale or invalid writes."""

from dataclasses import dataclass
from typing import Final

import anyio
import pytest
from httpx2 import AsyncClient, Response
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
type Body = dict[str, JsonValue]
INVOICE: Final[Body] = {"carrier": "CJ대한통운", "trackingNumber": "682100042841"}


@dataclass(frozen=True, slots=True)
class Action:
    path: str
    body: Body
    status_text: str


ACTIONS: Final = (
    Action("/bookings/booking-jieun/confirm-deposit", {}, "확정"),
    Action("/orders/order-1042/confirm", {}, "처리 중"),
    Action("/shipments/shipment-order-1040/pack", {}, "송장 대기"),
    Action("/shipments/shipment-order-1041/invoice", INVOICE, "배송 중"),
    Action("/shipments/shipment-order-1038/deliver", {}, "배송 완료"),
    Action("/content-drafts/draft-weekend-class/review", {"body": "검토한 글"}, "검토 완료"),
    Action("/tasks/task-keyring/completion", {"done": True}, "완료"),
    Action("/recommendations/recommendation-weekend/acknowledge", {}, "확인함"),
)


async def act(client: AsyncClient, action: Action, revision: int = 0) -> Response:
    return await client.post(action.path, json={**action.body, "expectedRevision": revision})


@pytest.mark.parametrize("action", ACTIONS, ids=lambda item: item.path)
async def test_action_returns_new_state_then_refuses_repeat(
    database: AsyncEngine,
    client: AsyncClient,
    action: Action,
) -> None:
    response = await act(client, action)
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["status"]["text"] == action.status_text
    assert card["revision"] == 1
    assert (await act(client, action)).status_code == 409
    assert (await act(client, action, 1)).status_code == 409


@pytest.mark.parametrize("action", ACTIONS, ids=lambda item: item.path)
async def test_stale_revision_changes_nothing(
    database: AsyncEngine, client: AsyncClient, action: Action,
) -> None:
    before = (await client.get("/today")).json()
    assert (await act(client, action, 7)).status_code == 409
    assert (await client.get("/today")).json() == before


@pytest.mark.parametrize("action", ACTIONS, ids=lambda item: item.path)
async def test_missing_resource_is_404(database: AsyncEngine, client: AsyncClient, action: Action) -> None:
    parts = action.path.split("/")
    parts[2] = "missing"
    assert (await act(client, Action("/".join(parts), action.body, ""))).status_code == 404


async def test_action_is_visible_to_the_next_read(database: AsyncEngine, client: AsyncClient) -> None:
    assert (await act(client, ACTIONS[0])).status_code == 200
    operations = (await client.get("/operations")).json()
    assert operations["attentionCount"] == 6
    pending = (await client.get("/bookings", params={"status": "deposit_pending"})).json()
    assert [item["id"] for item in pending["items"]] == ["booking-minwoo"]


async def test_order_confirmation_opens_fulfilment(database: AsyncEngine, client: AsyncClient) -> None:
    assert (await act(client, ACTIONS[1])).status_code == 200
    shipments = (await client.get("/shipments", params={"q": "#1042"})).json()["items"]
    assert [item["status"]["text"] for item in shipments] == ["포장 대기"]
    assert shipments[0]["deadline"] == "오늘 16:00 택배 수거"


async def test_shipment_walks_to_completed_order(database: AsyncEngine, client: AsyncClient) -> None:
    base = "/shipments/shipment-order-1040"
    assert (await client.post(f"{base}/invoice", json={**INVOICE, "expectedRevision": 0})).status_code == 409
    assert (await client.post(f"{base}/pack", json={"expectedRevision": 0})).status_code == 200
    invoiced = await client.post(f"{base}/invoice", json={**INVOICE, "expectedRevision": 1})
    assert invoiced.json()["lines"][2] == "11월 20일 도착 예정"
    assert (await client.post(f"{base}/deliver", json={"expectedRevision": 2})).status_code == 200
    orders = (await client.get("/orders", params={"q": "#1040"})).json()["items"]
    assert orders[0]["status"]["text"] == "배송 완료"


@pytest.mark.parametrize("field", [{"carrier": "   "}, {"trackingNumber": "    "}, {"trackingNumber": "1"}])
async def test_blank_invoice_fields_are_422(database: AsyncEngine, client: AsyncClient, field: Body) -> None:
    response = await client.post(
        "/shipments/shipment-order-1041/invoice",
        json={**INVOICE, **field, "expectedRevision": 0},
    )
    assert response.status_code == 422


async def test_blank_content_review_is_422(database: AsyncEngine, client: AsyncClient) -> None:
    response = await client.post(
        "/content-drafts/draft-weekend-class/review",
        json={"body": "  ", "expectedRevision": 0},
    )
    assert response.status_code == 422


async def test_task_can_be_reopened(database: AsyncEngine, client: AsyncClient) -> None:
    path = "/tasks/task-clay/completion"
    assert (await client.post(path, json={"done": True, "expectedRevision": 0})).status_code == 200
    assert (await client.post(path, json={"done": False, "expectedRevision": 1})).status_code == 200
    assert (await client.post(path, json={"done": False, "expectedRevision": 2})).status_code == 409


def booking(party: int, session: str = "session-wheel") -> Body:
    return {"sessionId": session, "customerName": "새 손님", "phone": "010-0000-0000", "partySize": party}


async def test_created_booking_waits_for_deposit_and_takes_seats(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    created = await client.post("/bookings", json=booking(3))
    assert created.status_code == 201
    assert created.json()["status"]["text"] == "예약금 대기"
    assert created.json()["deadline"] == "입금 기한 내일 11:00"
    assert (await client.post("/bookings", json=booking(1))).status_code == 409


async def test_booking_in_finished_class_is_refused(database: AsyncEngine, client: AsyncClient) -> None:
    assert (await client.post("/bookings", json=booking(1, "session-past-mug"))).status_code == 409


async def test_concurrent_bookings_cannot_oversell(database: AsyncEngine, client: AsyncClient) -> None:
    statuses: list[int] = []

    async def reserve() -> None:
        statuses.append((await client.post("/bookings", json=booking(2))).status_code)

    async with anyio.create_task_group() as group:
        for _ in range(4):
            group.start_soon(reserve)
    assert sorted(statuses) == [201, 409, 409, 409]
    async with database.connect() as connection:
        seats = await connection.scalar(
            text(
                "SELECT sum(party_size) FROM bookings WHERE session_id = 'session-wheel'",
            ),
        )
    assert seats == 3


async def test_concurrent_actions_have_one_winner(database: AsyncEngine, client: AsyncClient) -> None:
    statuses: list[int] = []

    async def confirm() -> None:
        statuses.append((await act(client, ACTIONS[1])).status_code)

    async with anyio.create_task_group() as group:
        for _ in range(3):
            group.start_soon(confirm)
    assert sorted(statuses) == [200, 409, 409]


async def test_calendar_event_appears_on_its_day(database: AsyncEngine, client: AsyncClient) -> None:
    created = await client.post(
        "/calendar/events",
        json={
            "title": "  공방 대청소 ",
            "startsAt": "2026-11-26T09:30:00+09:00",
            "detail": "선반 정리",
        },
    )
    assert created.status_code == 201
    body = (await client.get("/calendar", params={"start": "2026-11-26", "end": "2026-11-26"})).json()
    assert [(item["time"], item["title"]) for item in body["days"][0]["items"]] == [("09:30", "공방 대청소")]
    naive = await client.post("/calendar/events", json={"title": "x", "startsAt": "2026-11-26T09:30:00"})
    assert naive.status_code == 422


async def agenda(client: AsyncClient) -> dict[str, dict[str, JsonValue]]:
    day = f"{NOW:%Y-%m-%d}"
    body = (await client.get("/calendar", params={"start": day, "end": day})).json()
    return {str(item["id"]).split(":", 1)[0]: item for item in body["days"][0]["items"]}


async def test_calendar_rows_toggle_only_owner_checkable_work(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    created = (await client.post(
        "/calendar/events", json={"title": "가마 점검", "startsAt": NOW.isoformat()},
    )).json()
    assert (created["isDone"], created["revision"]) == (False, 0)
    event_id = str(created["id"]).split(":", 1)[1]
    path = f"/calendar/events/{event_id}/completion"
    done = await client.post(path, json={"done": True, "expectedRevision": 0})
    assert (done.status_code, done.json()["isDone"]) == (200, True)
    assert (await client.post(path, json={"done": True, "expectedRevision": 0})).status_code == 409
    assert (await client.post(path, json={"done": True, "expectedRevision": 1})).status_code == 409
    undone = await client.post(path, json={"done": False, "expectedRevision": 1})
    assert (undone.status_code, undone.json()["isDone"]) == (200, False)

    _ = await client.post(path, json={"done": True, "expectedRevision": 2})
    items = await agenda(client)
    assert items["event"]["isDone"] is True
    assert items["session"]["isDone"] is False
    assert items["task"]["isDone"] is False
    assert items["order"]["isDone"] is None


async def test_workshop_and_setting_edits_use_revisions(database: AsyncEngine, client: AsyncClient) -> None:
    settings = (await client.get("/settings")).json()
    workshop = {**settings["workshop"], "name": "오롯 도예", "expectedRevision": 0}
    del workshop["revision"]
    assert (await client.put("/workshop", json=workshop)).json()["revision"] == 1
    assert (await client.put("/workshop", json=workshop)).status_code == 409
    policy = await client.patch("/settings/booking_policy", json={"body": "새 규정", "expectedRevision": 0})
    assert policy.json()["body"] == "새 규정"
    assert (
        await client.patch("/settings/help", json={"body": "x", "expectedRevision": 0})
    ).status_code == 409

