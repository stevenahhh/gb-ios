"""Every tool acts through the app's own functions, and what it does can be undone the same way."""

from dataclasses import dataclass
from typing import Final

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_perform import perform
from agent_run import agent_session
from agent_settings import TOOL_TIERS
from agent_tools import TOOLS, registry, tool_definitions
from agent_types import ToolCall
from b_k14 import QuoteFields, QuoteInputs
from b_k14_models import OutreachQuoteRow
from tests.agent_core_support import ask, chat_of, execute, rows, says, scalar, set_mode, wants
from tests.agent_proactive_support import store
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
SEEDED: Final = (
    "정은주",
    "한유나",
    "오준호",
    "박지은",
    "최민우",
    "이수진",
    "문가영",
    "김서연",
    "김하늘",
    "이도윤",
)


@pytest.fixture
async def database(database: AsyncEngine) -> AsyncEngine:
    """Switch the assistant on; a new schema leaves it off."""
    await set_mode(database, "auto")
    return database


async def done(client: AsyncClient, question: str, *calls: object) -> dict[str, JsonValue]:
    body = await ask(client, chat_of(*calls, says("네")), question)  # type: ignore[arg-type]
    assert len(body["steps"]) == len(calls), body
    return body["steps"][-1]


async def undone(client: AsyncClient, step: dict[str, JsonValue]) -> None:
    response = await client.post(f"/agent/steps/{step['id']}/undo")
    assert response.status_code == 200, response.text


def test_the_registry_covers_every_tool_and_tier() -> None:
    assert {name: tool.rule.tier for name, tool in registry().items()} == dict(TOOL_TIERS)
    for definition in tool_definitions(TOOLS):
        function = definition["function"]
        assert isinstance(function, dict)
        assert set(function) == {"name", "description", "parameters"}
        parameters = function["parameters"]
        assert isinstance(parameters, dict)
        assert parameters["type"] == "object"
        assert "$defs" not in str(parameters)
        properties, required = parameters["properties"], parameters["required"]
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        assert set(required) <= set(properties), function["name"]


async def test_an_order_is_confirmed_and_put_back(database: AsyncEngine, client: AsyncClient) -> None:
    step = await done(client, "1042 주문 확인했어", wants("confirm_order", order="1042"))
    assert step["decision"] == "auto"
    assert await scalar(database, "SELECT status FROM orders WHERE id = 'order-1042'") == "processing"
    await undone(client, step)
    assert await scalar(database, "SELECT status FROM orders WHERE id = 'order-1042'") == "paid"
    assert await scalar(database, "SELECT count(*) FROM shipments WHERE order_id = 'order-1042'") == 0


async def test_a_parcel_arrives_and_comes_back(database: AsyncEngine, client: AsyncClient) -> None:
    step = await done(client, "1038 도착했어", wants("mark_delivered", order="1038"))
    assert step["decision"] == "auto"
    assert (
        await scalar(database, "SELECT status FROM shipments WHERE id = 'shipment-order-1038'") == "delivered"
    )
    await undone(client, step)
    assert (
        await scalar(database, "SELECT status FROM shipments WHERE id = 'shipment-order-1038'")
        == "in_transit"
    )


async def test_an_invoice_from_the_owners_words_is_registered_and_undone(
    database: AsyncEngine,
    client: AsyncClient,
) -> None:
    step = await done(
        client,
        "1041 CJ대한통운 610311119284 송장 등록해줘",
        wants("register_invoice", tracking_number="610311119284", order="1041", carrier="CJ대한통운"),
    )
    assert step["decision"] == "auto"
    row = await rows(
        database, "SELECT status, carrier, tracking_number FROM shipments WHERE id = 'shipment-order-1041'",
    )
    assert row == [("in_transit", "CJ대한통운", "610311119284")]
    await undone(client, step)
    assert await rows(
        database, "SELECT status, tracking_number FROM shipments WHERE id = 'shipment-order-1041'",
    ) == [
        ("invoice_pending", None),
    ]


@pytest.mark.parametrize(
    ("question", "number"),
    [
        ("1041 송장 번호 확인했어", "610311119284"),
        ("1041 CJ대한통운 61031111 송장 등록해줘", "61031111"),
    ],
)
async def test_an_invoice_the_owner_did_not_give_is_only_proposed(
    database: AsyncEngine,
    client: AsyncClient,
    question: str,
    number: str,
) -> None:
    step = await done(
        client,
        question,
        wants("register_invoice", tracking_number=number, order="1041", carrier="CJ대한통운"),
    )
    assert step["decision"] == "proposed"
    assert (
        await scalar(database, "SELECT status FROM shipments WHERE id = 'shipment-order-1041'")
        == "invoice_pending"
    )


async def test_a_number_that_is_already_used_is_not_registered_twice(
    database: AsyncEngine,
    client: AsyncClient,
) -> None:
    await execute(
        database,
        "UPDATE shipments SET carrier = 'CJ대한통운', tracking_number = '610311119284', status = 'in_transit'"
        " WHERE id = 'shipment-order-1039'",
    )
    step = await done(
        client,
        "1041 CJ대한통운 610311119284 송장 등록해줘",
        wants("register_invoice", tracking_number="610311119284", order="1041", carrier="CJ대한통운"),
    )
    assert step["decision"] == "proposed"


async def test_a_booking_is_made_for_the_class_the_owner_named_and_taken_back(
    database: AsyncEngine,
    client: AsyncClient,
) -> None:
    step = await done(
        client,
        "토요일 10시 주말 도자기 클래스에 박새봄 2명 예약해줘",
        wants(
            "create_booking",
            session="주말 도자기 클래스",
            day="2026-11-21",
            time="10:00",
            customer_name="박새봄",
            party_size=2,
        ),
    )
    assert step["decision"] == "auto"
    booked = await rows(
        database,
        "SELECT b.party_size, b.status, c.name FROM bookings b JOIN customers c ON c.id = b.customer_id"
        " WHERE c.name = '박새봄'",
    )
    assert booked == [(2, "deposit_pending", "박새봄")]
    await undone(client, step)
    assert (
        await rows(
            database,
            "SELECT 1 FROM customers c JOIN bookings b ON b.customer_id = c.id WHERE c.name = '박새봄'",
        )
        == []
    )


async def test_a_booking_without_the_party_size_is_proposed(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    step = await done(
        client,
        "토요일 10시 주말 도자기 클래스에 박새봄 예약해줘",
        wants(
            "create_booking",
            session="주말 도자기 클래스",
            day="2026-11-21",
            time="10:00",
            customer_name="박새봄",
            party_size=2,
        ),
    )
    assert step["decision"] == "proposed"
    assert "인원" in step["reason"]


async def test_a_deposit_comes_back_to_waiting_when_undone(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    step = await done(client, "박지은 예약금 들어왔어", wants("confirm_deposit", booking="박지은"))
    assert step["decision"] == "auto"
    await undone(client, step)
    assert await rows(
        database,
        "SELECT status, deposit_due_at IS NOT NULL FROM bookings WHERE id = 'booking-jieun'",
    ) == [("deposit_pending", True)]


async def test_a_wrong_deposit_amount_waits_for_the_owner(database: AsyncEngine, client: AsyncClient) -> None:
    step = await done(client, "박지은 예약금 5,000원 들어왔어", wants("confirm_deposit", booking="박지은"))
    assert step["decision"] == "proposed"
    assert (
        await scalar(database, "SELECT status FROM bookings WHERE id = 'booking-jieun'") == "deposit_pending"
    )


async def test_a_cancellation_keeps_its_case_and_can_be_given_back(
    database: AsyncEngine,
    client: AsyncClient,
) -> None:
    step = await done(
        client,
        "이수진 예약 사정이 있어서 전액 환불로 취소해줘",
        wants("decide_cancellation", booking="이수진", decision="full_refund", reason="사정이 있어서"),
    )
    assert step["decision"] == "auto", step
    assert await scalar(database, "SELECT status FROM bookings WHERE id = 'booking-sujin'") == "cancelled"
    assert await scalar(database, "SELECT count(*) FROM cancellation_cases") == 1
    await undone(client, step)
    assert await scalar(database, "SELECT status FROM bookings WHERE id = 'booking-sujin'") == "confirmed"


async def test_a_quote_answer_is_recorded_and_restored(database: AsyncEngine, client: AsyncClient) -> None:
    await store(
        database,
        OutreachQuoteRow(
            id="quote-hall",
            status="sent",
            class_id="도자기 원데이 클래스",
            fields=QuoteFields(org_name="순천시청소년문화의집").model_dump(mode="json"),
            inputs=QuoteInputs(headcount=10).model_dump(mode="json"),
            signals=[],
            locked=False,
            snapshot={},
            missing_costs=[],
            ab_arm="A",
        ),
    )
    step = await done(
        client,
        "순천시청소년문화의집에서 수락했어",
        wants("record_quote_outcome", quote="순천시청소년문화의집", outcome="accepted"),
    )
    assert step["decision"] == "auto", step
    assert await scalar(database, "SELECT outcome FROM outreach_quotes WHERE id = 'quote-hall'") == "accepted"
    await undone(client, step)
    assert await scalar(database, "SELECT outcome FROM outreach_quotes WHERE id = 'quote-hall'") is None
    assert await scalar(database, "SELECT status FROM outreach_quotes WHERE id = 'quote-hall'") == "sent"


@dataclass(frozen=True, slots=True)
class FakeDraft:
    """A grounded draft without a model call."""

    draft: str
    judgment: None
    lock: str


async def test_a_reply_draft_is_kept_with_its_lock_and_restored(
    database: AsyncEngine,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def written(inquiry_id: str, now: object) -> FakeDraft:
        del inquiry_id, now
        return FakeDraft("김하늘 님, 안내 드려요.", None, "locked")

    monkeypatch.setattr("agent_tools_drafts.write_draft", written)
    before = await scalar(database, "SELECT draft FROM inquiries WHERE id = 'inquiry-clay'")
    step = await done(
        client, "도자기 체험 문의 답장 초안 써줘", wants("save_reply_draft", inquiry="도자기 체험 준비물"),
    )
    assert step["decision"] == "auto"
    assert (
        await scalar(database, "SELECT draft FROM inquiries WHERE id = 'inquiry-clay'")
        == "김하늘 님, 안내 드려요."
    )
    assert await scalar(database, "SELECT status FROM inquiries WHERE id = 'inquiry-clay'") == "pending"
    await undone(client, step)
    assert await scalar(database, "SELECT draft FROM inquiries WHERE id = 'inquiry-clay'") == before


async def test_the_owners_tasks_and_drafts_move_and_come_back(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    closed = await done(client, "가마 온도 점검 끝냈어", wants("complete_task", task="가마 온도 점검"))
    assert await scalar(database, "SELECT status FROM tasks WHERE id = 'task-kiln'") == "done"
    reopened = await done(client, "가마 온도 점검 다시 열어", wants("reopen_task", task="가마 온도 점검"))
    assert await scalar(database, "SELECT status FROM tasks WHERE id = 'task-kiln'") == "open"
    assert {closed["decision"], reopened["decision"]} == {"auto"}
    before = await scalar(database, "SELECT body FROM content_drafts WHERE id = 'draft-weekend-class'")
    step = await done(
        client,
        "주말 클래스 모집 글을 바꿔줘",
        wants("save_content_draft", draft="주말 클래스 모집 글", text="새 본문이에요."),
    )
    assert (
        await scalar(database, "SELECT body FROM content_drafts WHERE id = 'draft-weekend-class'")
        == "새 본문이에요."
    )
    await undone(client, step)
    assert (
        await scalar(database, "SELECT body FROM content_drafts WHERE id = 'draft-weekend-class'") == before
    )


async def test_an_entry_moves_and_comes_back(database: AsyncEngine, client: AsyncClient) -> None:
    added = await done(
        client,
        "금요일 3시에 재고 확인 일정 넣어줘",
        wants("add_event", title="재고 확인", day="2026-11-20", time="15:00"),
    )
    moved = await done(
        client,
        "재고 확인 22일로 옮겨줘",
        wants("move_event", event="재고 확인", day="2026-11-22"),
    )
    assert moved["decision"] == "auto"
    start = await scalar(
        database, "SELECT starts_at FROM calendar_events WHERE id = :id", id=added["target"]["id"],
    )
    assert start.astimezone(NOW.tzinfo).isoformat().startswith("2026-11-22T15:00")  # type: ignore[attr-defined]
    await undone(client, moved)
    start = await scalar(
        database, "SELECT starts_at FROM calendar_events WHERE id = :id", id=added["target"]["id"],
    )
    assert start.astimezone(NOW.tzinfo).isoformat().startswith("2026-11-20T15:00")  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", sorted(name for name, tier in TOOL_TIERS.items() if tier == "T0"))
async def test_reads_never_show_a_name_or_a_phone(database: AsyncEngine, name: str) -> None:
    args: dict[str, JsonValue] = (
        {"start": "2026-11-16", "end": "2026-11-28"} if name == "read_calendar" else {}
    )
    async with agent_session("proactive", "점검", NOW) as session:
        result = await perform(session.context, ToolCall("1", name, args))
    assert result.step.decision == "auto", result.step
    assert not any(person in result.for_model for person in SEEDED), name
    assert "010-" not in result.for_model
    async with database.connect() as connection:
        stored = (await connection.execute(text("SELECT result FROM agent_steps"))).scalar_one()
    assert not any(person in stored for person in SEEDED)
