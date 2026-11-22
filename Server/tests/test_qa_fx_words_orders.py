"""Orders are confirmed and delivered only on a done fact or a request that names that very step."""

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from ai import AskResponse
from tests.agent_core_support import ask, chat_of, rows, says, set_mode, wants

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


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
        ("1042 주문 확인했어", "auto"),
        ("1042번 주문을 확인했습니다", "auto"),
        ("1042 주문 확정했어요", "auto"),
        ("1042 주문 접수했어", "auto"),
        ("1042 주문 확인 완료", "auto"),
        ("1042 주문 확인 처리했어", "auto"),
        ("1042 주문 확인해줘", "auto"),
        ("1042 주문 확인해 주세요.", "auto"),
        ("1042 주문 확인 처리해 줘", "auto"),
        ("1042 주문 확인해 주고 점토 주문도 끝났어 할 일 완료로 바꿔 줘", "auto"),
        ("정태우 님 미니 화병 주문 받아 줘", "auto"),
        ("1042 환불 처리했어", "proposed"),
        ("1042 취소 확인했어", "proposed"),
        ("1042 취소 접수됐어", "proposed"),
        ("1042 입금 확인했어", "proposed"),
        ("1042 문의 받았어", "proposed"),
        ("1042 주소 확인했어", "proposed"),
        ("1042 입금 확인해 줘", "proposed"),
        ("1042 확인했어", "proposed"),
        ("1042 주문 들어왔어", "proposed"),
        ("1042 주문 접수됐어", "proposed"),
        ("1042 주문 받았어", "proposed"),
        ("1042 주문 처리해 줘", "proposed"),
        ("1042 주문 내용 확인했어", "proposed"),
        ("1042 주문 취소 확인했어", "proposed"),
        ("1042 재주문 확인했어", "proposed"),
        ("1042 주문 확인해 줘야 해", "proposed"),
        ("1042 주문 확인 완료해야 해", "proposed"),
        ("1042 주문 확인했나 봐", "proposed"),
        ("1042 주문 확인 문자 보냈어", "proposed"),
        ("1042 주문 확인했어요 문자 보냈어", "proposed"),
        ("1042 손님이 주문 확인해 주세요 하셨어", "proposed"),
        ("1042 주문 확인했는데 환불했어", "proposed"),
    ],
)
async def test_an_order_is_confirmed_only_by_words_about_its_confirmation(
    shop: AsyncEngine, client: AsyncClient, words: str, decision: str,
) -> None:
    order = "정태우" if "정태우" in words else "1042"
    body = await ask(client, chat_of(wants("confirm_order", order=order), says("네")), words)
    [step] = body["steps"]
    assert step["decision"] == decision, step["reason"]
    row = "order-1043" if order == "정태우" else "order-1042"
    [(status,)] = await rows(shop, "SELECT status FROM orders WHERE id = :id", id=row)
    assert status == ("processing" if decision == "auto" else "paid")


@pytest.mark.parametrize(
    ("words", "decision"),
    [
        ("1038 도착했어", "auto"),
        ("1038 배송 완료됐어", "auto"),
        ("1038 배송 완료", "auto"),
        ("1038 배송됐어요", "auto"),
        ("1038 배달됐어", "auto"),
        ("1038 배달 완료했습니다", "auto"),
        ("1038 손님이 택배 잘 받으셨어", "auto"),
        ("1038 수령했어", "auto"),
        ("1038 배송 완료 처리해 줘", "auto"),
        ("1038 배송 완료로 바꿔 주세요", "auto"),
        ("1038 내일 도착해", "proposed"),
        ("1038 반품 도착했어", "proposed"),
        ("1038 반송 받았어", "proposed"),
        ("1038 입금 받았어", "proposed"),
        ("1038 기사님께 전달했어", "proposed"),
        ("1038 배달 중이야", "proposed"),
        ("1038 배달 출발했어", "proposed"),
        ("1038 배송 완료 문자 보냈어", "proposed"),
        ("1038 도착 예정", "proposed"),
        ("1038 곧 도착", "proposed"),
        ("1038 도착 확인해 줘", "proposed"),
        ("1038 잘 받았어", "proposed"),
        ("1038 손님이 문자 잘 받으셨어", "proposed"),
        ("1038 배송 완료해야 해", "proposed"),
        ("1038 배송 완료 처리해 줘야 해", "proposed"),
        ("1038 배송 완료됐나 봐", "proposed"),
        ("1038 물류센터에 도착했어", "proposed"),
        ("1038 교환 상품 도착했어", "proposed"),
        ("1038 도착했다고 문자 왔어", "proposed"),
        ("1038 배송해 줘", "proposed"),
    ],
)
async def test_a_parcel_is_delivered_only_by_words_about_its_arrival(
    shop: AsyncEngine, client: AsyncClient, words: str, decision: str,
) -> None:
    body = await ask(client, chat_of(wants("mark_delivered", order="1038"), says("네")), words)
    [step] = body["steps"]
    assert step["decision"] == decision, step["reason"]
    [(status,)] = await rows(shop, "SELECT status FROM shipments WHERE id = 'shipment-order-1038'")
    assert status == ("delivered" if decision == "auto" else "in_transit")
