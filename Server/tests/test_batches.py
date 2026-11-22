"""Batch fulfilment writes change every listed row or none, and orders carry their parcel's step."""

from typing import Final

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
type Body = dict[str, JsonValue]
PARCELS: Final = """
    SELECT id, status, packed_at, carrier, tracking_number, shipped_at, delivered_at, revision
    FROM shipments ORDER BY id
"""
ORDERS: Final = """
    SELECT o.id, o.status, o.revision, s.id
    FROM orders o LEFT JOIN shipments s ON s.order_id = o.id ORDER BY o.id
"""


def rows(*pairs: tuple[str, int]) -> Body:
    return {"items": [{"id": row_id, "expectedRevision": revision} for row_id, revision in pairs]}


async def snapshot(database: AsyncEngine, query: str) -> list[tuple[object, ...]]:
    async with database.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(query))).all()]


async def test_confirm_then_pack_then_invoice_then_deliver_in_batches(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    confirmed = await client.post("/orders/confirm", json=rows(("order-1043", 0), ("order-1042", 0)))
    assert confirmed.status_code == 200, confirmed.text
    cards = confirmed.json()["items"]
    assert [card["id"] for card in cards] == ["order-1043", "order-1042"]
    assert {card["status"]["text"] for card in cards} == {"포장 전"}

    parcels = (("shipment-order-1042", 0), ("shipment-order-1043", 0))
    packed = (await client.post("/shipments/pack", json=rows(*parcels))).json()["items"]
    assert [(card["status"]["text"], card["revision"]) for card in packed] == [("송장 넣기 전", 1)] * 2

    invoice = {
        "carrier": "우체국택배",
        "items": [
            {"id": "shipment-order-1042", "expectedRevision": 1, "trackingNumber": "6865123456789"},
            {"id": "shipment-order-1043", "expectedRevision": 1, "trackingNumber": "6865123456790"},
        ],
    }
    sent = (await client.post("/shipments/invoice", json=invoice)).json()["items"]
    assert [card["lines"][1] for card in sent] == ["우체국택배 6865123456789", "우체국택배 6865123456790"]

    delivered = await client.post("/shipments/deliver", json=rows(*((row_id, 2) for row_id, _ in parcels)))
    assert {card["status"]["text"] for card in delivered.json()["items"]} == {"배송 완료"}
    orders = (await client.get("/orders", params={"q": "#104"})).json()["items"]
    assert {card["id"]: card["status"]["text"] for card in orders}["order-1043"] == "배송 완료"


@pytest.mark.parametrize(("path", "body"), [
    ("/shipments/pack", rows(("shipment-order-1040", 0), ("shipment-order-1041", 0))),
    ("/shipments/pack", rows(("shipment-order-1040", 0), ("shipment-order-1041", 3))),
    ("/shipments/deliver", rows(("shipment-order-1038", 0), ("shipment-order-1040", 0))),
    ("/shipments/undo", rows(("shipment-order-1041", 0), ("shipment-order-1040", 0))),
    ("/orders/confirm", rows(("order-1042", 0), ("order-1040", 0))),
    ("/orders/undo-confirm", rows(("order-1040", 0), ("order-1042", 0))),
])
async def test_one_refused_row_changes_nothing(
    database: AsyncEngine, client: AsyncClient, path: str, body: Body,
) -> None:
    before = (await snapshot(database, PARCELS), await snapshot(database, ORDERS))
    today = (await client.get("/today")).json()
    assert (await client.post(path, json=body)).status_code == 409
    assert (await snapshot(database, PARCELS), await snapshot(database, ORDERS)) == before
    assert (await client.get("/today")).json() == today


@pytest.mark.parametrize(("path", "body", "status"), [
    ("/shipments/pack", rows(("shipment-order-1040", 0), ("shipment-order-1040", 0)), 422),
    ("/shipments/pack", {"items": []}, 422),
    ("/shipments/pack", rows(("shipment-order-1040", 0), ("missing", 0)), 404),
    ("/orders/confirm", rows(("missing", 0)), 404),
    ("/shipments/invoice", {"carrier": " ", "items": [
        {"id": "shipment-order-1041", "expectedRevision": 0, "trackingNumber": "682100042841"},
    ]}, 422),
    ("/shipments/invoice", {"carrier": "CJ대한통운", "items": [
        {"id": "shipment-order-1041", "expectedRevision": 0},
    ]}, 422),
])
async def test_invalid_batches_are_refused(
    database: AsyncEngine, client: AsyncClient, path: str, body: Body, status: int,
) -> None:
    before = await snapshot(database, PARCELS)
    assert (await client.post(path, json=body)).status_code == status
    assert await snapshot(database, PARCELS) == before


async def test_batch_undo_restores_state_and_screen_counts(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    parcels, orders = await snapshot(database, PARCELS), await snapshot(database, ORDERS)
    operations = (await client.get("/operations")).json()
    confirmed = await client.post("/orders/confirm", json=rows(("order-1042", 0), ("order-1044", 0)))
    assert confirmed.status_code == 200
    undone = await client.post("/orders/undo-confirm", json=rows(("order-1042", 1), ("order-1044", 1)))
    assert [card["status"]["text"] for card in undone.json()["items"]] == ["결제 완료"] * 2

    sent = await client.post("/shipments/pack", json=rows(("shipment-order-1040", 0)))
    assert sent.status_code == 200
    assert (await client.post("/shipments/deliver", json=rows(("shipment-order-1038", 0)))).status_code == 200
    back = await client.post("/shipments/undo", json=rows(
        ("shipment-order-1040", 1), ("shipment-order-1038", 1),
    ))
    assert back.status_code == 200, back.text
    assert [card["status"]["text"] for card in back.json()["items"]] == ["포장 전", "배송 중"]
    restored = await snapshot(database, PARCELS)
    assert [row[:7] for row in restored] == [row[:7] for row in parcels]
    assert [row[:2] for row in await snapshot(database, ORDERS)] == [row[:2] for row in orders]
    assert (await client.get("/operations")).json() == operations


async def test_order_card_offers_its_parcel_step(database: AsyncEngine, client: AsyncClient) -> None:
    order = (await client.get("/cards/order/order-1040")).json()
    assert order["status"] == {"text": "포장 전", "tone": "attention"}
    assert order["action"] == {
        "code": "pack", "label": "포장 완료하기",
        "target": {"kind": "shipment", "id": "shipment-order-1040", "revision": 0},
    }
    target = order["action"]["target"]
    packed = await client.post(
        f"/shipments/{target['id']}/pack", json={"expectedRevision": target["revision"]},
    )
    assert packed.status_code == 200
    order = (await client.get("/cards/order/order-1040")).json()
    assert (order["status"]["text"], order["action"]["code"]) == ("송장 넣기 전", "registerInvoice")
    assert order["action"]["target"]["revision"] == 1
    assert (await client.get("/cards/order/order-1042")).json()["action"] == {
        "code": "confirmOrder", "label": "주문 확인하기", "target": None,
    }
    assert (await client.get("/cards/order/order-1031")).json()["action"] is None
