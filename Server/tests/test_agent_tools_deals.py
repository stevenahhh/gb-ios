"""Deal and parcel tools act only on the owner's own current words; anything else waits for the owner."""

from dataclasses import dataclass
from typing import Final

import pytest
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

import agent_perform
from agent_invoice_types import PROBLEM_TEXT, Problem
from ai import AskResponse
from b_k14 import QuoteFields
from b_k14_models import OutreachQuoteRow
from database import transaction
from tests.agent_core_support import Body, ask, chat_of, execute, rows, says, set_mode, wants
from tests.agent_corpora.harness import snapshot
from tests.agent_corpora.mutations import racing

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
TRACKING: Final = "682100042841"
TABLES: Final = {
    "booking": "bookings", "order": "orders", "shipment": "shipments", "quote": "outreach_quotes",
}


@dataclass(frozen=True, slots=True)
class Deal:
    """One tool, the words that allow it, the row it reads, and what it changes."""

    tool: str
    args: Body
    said: str
    table: str
    row: str
    probe: str
    before: tuple[JsonValue, ...]
    after: tuple[JsonValue, ...]


DEPOSIT: Final = Deal(
    "confirm_deposit", {"booking": "최민우"}, "최민우 님 예약금 30,000원 들어왔어",
    "bookings", "booking-minwoo",
    "SELECT status, deposit_confirmed_at IS NOT NULL FROM bookings WHERE id = 'booking-minwoo'",
    ("deposit_pending", False), ("confirmed", True),
)
BOOKING: Final = Deal(
    "create_booking",
    {
        "session": "주말 도자기 클래스", "day": "2026-11-21", "time": "10:00", "customer_name": "강새봄",
        "party_size": 2,
    },
    "토요일 10시 주말 도자기 클래스에 강새봄 님 2명 예약해 줘", "class_sessions", "session-weekend",
    "SELECT (SELECT count(*) FROM bookings WHERE session_id = 'session-weekend'),"
    " (SELECT count(*) FROM customers WHERE name = '강새봄')",
    (2, 0), (3, 1),
)
CANCEL: Final = Deal(
    "decide_cancellation", {"booking": "임도현", "decision": "full_refund", "reason": "몸이 아파서"},
    "임도현 님 몸이 아파서 예약 취소하고 전액 환불해 줘", "bookings", "booking-dohyun",
    "SELECT status, (SELECT max(decided_won) FROM cancellation_cases)"
    " FROM bookings WHERE id = 'booking-dohyun'",
    ("confirmed", None), ("cancelled", 20000),
)
QUOTE: Final = Deal(
    "record_quote_outcome",
    {"quote": "순천초등학교", "outcome": "accepted_adjusted", "final_total_krw": 1_200_000},
    "순천초등학교에서 1,200,000원으로 조정해서 하기로 했어", "outreach_quotes", "quote-school",
    "SELECT q.status, q.outcome, q.final_total_krw, t.status FROM outreach_quotes q"
    " JOIN tasks t ON t.id = q.follow_up_task_id WHERE q.id = 'quote-school'",
    ("sent", None, None, "open"), ("accepted_adjusted", "accepted_adjusted", 1_200_000, "done"),
)
CONFIRM: Final = Deal(
    "confirm_order", {"order": "1042"}, "1042 주문 확인했어", "orders", "order-1042",
    "SELECT status, (SELECT count(*) FROM shipments WHERE order_id = 'order-1042')"
    " FROM orders WHERE id = 'order-1042'",
    ("paid", 0), ("processing", 1),
)
PACK: Final = Deal(
    "mark_packed", {"order": "1040"}, "1040 포장 끝났어", "shipments", "shipment-order-1040",
    "SELECT status, packed_at IS NOT NULL FROM shipments WHERE id = 'shipment-order-1040'",
    ("packing", False), ("invoice_pending", True),
)
INVOICE: Final = Deal(
    "register_invoice", {"tracking_number": TRACKING, "order": "1041", "carrier": "CJ대한통운"},
    f"1041 CJ대한통운 {TRACKING}", "shipments", "shipment-order-1041",
    "SELECT status, carrier, tracking_number FROM shipments WHERE id = 'shipment-order-1041'",
    ("invoice_pending", None, None), ("in_transit", "CJ대한통운", TRACKING),
)
DELIVERED: Final = Deal(
    "mark_delivered", {"order": "1038"}, "1038 배송 완료됐어", "shipments", "shipment-order-1038",
    "SELECT s.status, o.status FROM shipments s JOIN orders o ON o.id = s.order_id WHERE o.id = 'order-1038'",
    ("in_transit", "processing"), ("delivered", "completed"),
)
DEALS: Final = (DEPOSIT, BOOKING, CANCEL, QUOTE, CONFIRM, PACK, INVOICE, DELIVERED)
every_deal = pytest.mark.parametrize("deal", DEALS, ids=lambda deal: deal.tool)


def deal_id(value: Deal | Body | str) -> str | None:
    return value.tool if isinstance(value, Deal) else None


async def add_quote(quote_id: str, task_id: str | None = None) -> None:
    async with transaction() as db:
        db.add(OutreachQuoteRow(
            id=quote_id, status="sent", class_id="도자기 원데이 클래스",
            fields=QuoteFields(org_type="school", org_name="순천초등학교").model_dump(mode="json"), inputs={},
            signals=[], locked=False, snapshot={}, missing_costs=[], ab_arm="B", follow_up_task_id=task_id,
        ))


@pytest.fixture
async def database(database: AsyncEngine) -> AsyncEngine:
    """Switch the assistant on; a new schema leaves it off."""
    await set_mode(database, "auto")
    return database


@pytest.fixture
async def shop(database: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncEngine:
    async def answered(body: JsonValue, now: JsonValue) -> AskResponse:
        del body, now
        return AskResponse(answer="읽어서 알려 드릴게요.", intent="lookup")

    monkeypatch.setattr("agent_run.ask", answered)
    await add_quote("quote-school", "task-market")
    return database


async def turn(
    client: AsyncClient, deal: Deal, words: str, *, args: Body | None = None,
    history: list[JsonValue] | None = None,
) -> tuple[Body, list[Body]]:
    """The owner says `words` and the model asks for the deal's tool; return the step and any proposals."""
    chat = chat_of(wants(deal.tool, **{**deal.args, **(args or {})}), says("네"))
    body = await ask(client, chat, words, history=history or [])
    [step] = body["steps"]
    assert step["tool"] == deal.tool
    return step, body["proposals"]


async def state(engine: AsyncEngine, deal: Deal) -> tuple[object, ...]:
    [row] = await rows(engine, deal.probe)
    return row


async def everything(engine: AsyncEngine) -> dict[tuple[str, str], tuple[object, ...]]:
    async with engine.connect() as connection:
        return await snapshot(connection)


async def refuses_to_act(
    engine: AsyncEngine, client: AsyncClient, deal: Deal, words: str, args: Body | None = None,
) -> Body:
    """Require a proposal or a question back, and that no business row changed."""
    before = await everything(engine)
    step, _ = await turn(client, deal, words, args=args)
    assert step["decision"] in {"proposed", "clarify"}, step
    assert step["undoable"] is False
    assert await everything(engine) == before
    return step


@every_deal
async def test_the_owners_words_run_it_and_undo_restores_everything(
    shop: AsyncEngine, client: AsyncClient, deal: Deal,
) -> None:
    assert await state(shop, deal) == deal.before
    step, proposals = await turn(client, deal, deal.said)
    assert (step["decision"], step["undoable"], proposals) == ("auto", True, []), step["reason"]
    assert {item["kind"] for item in step["evidence"]} == {"owner_turn"}
    assert await state(shop, deal) == deal.after
    undone = await client.post(f"/agent/steps/{step['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert await state(shop, deal) == deal.before
    assert (await client.post(f"/agent/steps/{step['id']}/undo")).status_code == 409


@every_deal
async def test_words_from_an_earlier_turn_only_raise_a_proposal(
    shop: AsyncEngine, client: AsyncClient, deal: Deal,
) -> None:
    step, [proposal] = await turn(
        client, deal, "응 그거 처리해 줘", history=[{"role": "owner", "text": deal.said}],
    )
    assert step["decision"] == "proposed"
    assert await state(shop, deal) == deal.before
    approved = await client.post(
        f"/agent/proposals/{proposal['id']}/approve", json={"expectedRevision": proposal["expectedRevision"]},
    )
    # A tracking number must come from the owner's words, so approval alone never registers one.
    wanted = (409, deal.before) if deal is INVOICE else (200, deal.after)
    assert (approved.status_code, await state(shop, deal)) == wanted, approved.text


NOT_WHAT_WAS_SAID: Final[tuple[tuple[Deal, str, Body], ...]] = (
    (DEPOSIT, "최민우 님 20,000원 들어왔어", {}),
    (DEPOSIT, "최민우 님 예약금 30,000원 중에 10,000원 들어왔어", {}),
    (BOOKING, "토요일 10시 주말 도자기 클래스에 강새봄 님 3명 예약해 줘", {}),
    (BOOKING, "토요일 11시 주말 도자기 클래스에 강새봄 님 2명 예약해 줘", {}),
    (BOOKING, "토요일 10시 주말 도자기 클래스에 강가을 님 2명 예약해 줘", {}),
    (BOOKING, "다음 주 토요일 10시 주말 도자기 클래스에 강새봄 님 2명 예약해 줘", {"day": None}),
    (CANCEL, "임도현 님 몸이 아파서 예약 취소하고 이월해 줘", {}),
    (CANCEL, "임도현 님 예약 취소하고 전액 환불해 줘", {}),
    (
        CANCEL, "임도현 님 몸이 아파서 예약 취소하고 10,000원 환불해 줘",
        {"decision": "custom", "refund_won": 15000},
    ),
    (QUOTE, "순천초등학교에서 1,000,000원으로 조정해서 하기로 했어", {}),
    (QUOTE, "순천초등학교 견적 거절됐어", {"outcome": "accepted", "final_total_krw": None}),
    (CONFIRM, "1043 주문 확인했어", {}),
    (PACK, "김서연 님 1042 포장 끝났어", {"order": "김서연"}),
    (INVOICE, "1041 CJ대한통운 682100042814", {}),
    (INVOICE, f"1040 CJ대한통운 {TRACKING}", {}),
    (DELIVERED, "최하서 님 1039 배송 완료됐어", {"order": "최하서"}),
)


@pytest.mark.parametrize(("deal", "words", "args"), NOT_WHAT_WAS_SAID, ids=deal_id)
async def test_a_value_the_owner_did_not_state_is_never_written(
    shop: AsyncEngine, client: AsyncClient, deal: Deal, words: str, args: Body,
) -> None:
    _ = await refuses_to_act(shop, client, deal, words, args)


NOT_A_STATEMENT: Final[tuple[tuple[Deal, str], ...]] = (
    (DEPOSIT, "최민우 님 예약금 30,000원 들어왔어?"),
    (DEPOSIT, "최민우 님 예약금. 들어왔어?"),
    (DEPOSIT, "최민우 님 예약금 알려 줘"),
    (DEPOSIT, "최민우 님 예약금 안 들어왔어"),
    (DEPOSIT, "최민우 님 예약금 안들어왔어"),
    (DEPOSIT, "최민우 님 예약금 못받았어"),
    (BOOKING, "토요일 10시 주말 도자기 클래스에 강새봄 님 2명 예약했나"),
    (BOOKING, "토요일 10시 주말 도자기 클래스 강새봄 님 2명 예약 내역 보여 줘"),
    (BOOKING, "토요일 10시 주말 도자기 클래스에 강새봄 님 2명 예약하지 마"),
    (CANCEL, "임도현 님 몸이 아파서 예약 취소하고 전액 환불했어?"),
    (CANCEL, "임도현 님 몸이 아파서 전액 환불 취소 안하기로 했어"),
    (QUOTE, "순천초등학교에서 1,200,000원으로 조정했을까"),
    (QUOTE, "순천초등학교에서 1,200,000원 조정 안됐어"),
    (CONFIRM, "1042 주문 확인했어?"),
    (CONFIRM, "1042 주문 확인 못했어"),
    (CONFIRM, "1042 주문 확인 상태 보여 줘"),
    (PACK, "1040 포장 끝났나"),
    (PACK, "1040 포장 방법 알려 줘"),
    (PACK, "1040 포장 못 끝냈어"),
    (PACK, "1040 포장 못했어"),
    (PACK, "1040 포장 덜 끝났어"),
    (PACK, "1040 포장 끝났어. 아 아니다 아직이야"),
    (INVOICE, f"1041 CJ대한통운 {TRACKING} 맞아?"),
    (INVOICE, f"1041 CJ대한통운 {TRACKING} 아니야"),
    (INVOICE, f"1041 CJ대한통운 {TRACKING} 등록하지 마"),
    (DELIVERED, "1038 배송 완료됐을까"),
    (DELIVERED, "1038 도착 시간 알려 줘"),
    (DELIVERED, "1038 배송 완료 안 됐어"),
    (DELIVERED, "1038 배송 완료 안됐어"),
)


@pytest.mark.parametrize(("deal", "words"), NOT_A_STATEMENT)
async def test_a_question_or_denial_never_acts(
    shop: AsyncEngine, client: AsyncClient, deal: Deal, words: str,
) -> None:
    _ = await refuses_to_act(shop, client, deal, words)


CUSTOMER: Final = "INSERT INTO customers (id, name) VALUES ('customer-twin', '{}')"
ORDER: Final = (
    "INSERT INTO orders (id, order_number, customer_id, product_name, quantity, amount_won, status,"
    " ordered_at) VALUES ('order-1099', 1099, 'customer-twin', '핸드메이드 접시', 1, 30000, '{}', now())"
)
PARCEL: Final = (
    "INSERT INTO shipments (id, order_id, status, ship_by_at, packed_at, shipped_at, carrier,"
    " tracking_number) SELECT 'shipment-order-1099', 'order-1099', status, ship_by_at, packed_at,"
    " shipped_at, carrier, CASE WHEN tracking_number IS NOT NULL THEN '688800001111' END"
    " FROM shipments WHERE id = '{}'"
)
SEAT: Final = (
    "INSERT INTO bookings (id, session_id, customer_id, party_size, deposit_won, status, deposit_due_at,"
    " deposit_confirmed_at) SELECT 'booking-twin', 'session-weekend', 'customer-twin', 1, deposit_won,"
    " status, deposit_due_at, deposit_confirmed_at FROM bookings WHERE id = '{}'"
)


@dataclass(frozen=True, slots=True)
class Twin:
    """A second customer of the same name with the same kind of row, and words that fit both."""

    deal: Deal
    name: str
    words: str
    args: Body
    setup: tuple[str, ...]


def parcel_twin(deal: Deal, name: str, words: str) -> Twin:
    return Twin(deal, name, words, {"order": name}, (ORDER.format("processing"), PARCEL.format(deal.row)))


PACKED_TWIN: Final = parcel_twin(PACK, "김서연", "김서연 님 포장 끝났어")
TWINS: Final = (
    Twin(DEPOSIT, "최민우", DEPOSIT.said, {}, (SEAT.format(DEPOSIT.row),)),
    Twin(CANCEL, "임도현", CANCEL.said, {}, (SEAT.format(CANCEL.row),)),
    Twin(CONFIRM, "정태우", "정태우 님 주문 확인했어", {"order": "정태우"}, (ORDER.format("paid"),)),
    PACKED_TWIN,
    parcel_twin(INVOICE, "이수진", f"이수진 님 CJ대한통운 {TRACKING}"),
    parcel_twin(DELIVERED, "최하서", "최하서 님 배송 완료됐어"),
)


async def add_twin(engine: AsyncEngine, twin: Twin) -> None:
    for query in (CUSTOMER.format(twin.name), *twin.setup):
        await execute(engine, query)


@pytest.mark.parametrize("twin", TWINS, ids=lambda twin: twin.deal.tool)
async def test_two_customers_with_one_name_make_the_agent_ask(
    shop: AsyncEngine, client: AsyncClient, twin: Twin,
) -> None:
    await add_twin(shop, twin)
    step = await refuses_to_act(shop, client, twin.deal, twin.words, twin.args)
    assert (step["decision"], step["target"]) == ("clarify", None)


async def test_two_open_quotes_of_one_institution_make_the_agent_ask(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    await add_quote("quote-twin")
    step = await refuses_to_act(shop, client, QUOTE, QUOTE.said)
    assert step["decision"] == "clarify"


async def test_the_model_cannot_choose_between_two_parcels_of_one_name(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    await add_twin(shop, PACKED_TWIN)
    step = await refuses_to_act(shop, client, PACK, PACKED_TWIN.words, {"order": "1040"})
    assert step["decision"] == "proposed"


OUT_OF_ORDER: Final[tuple[tuple[Deal, str, Body], ...]] = (
    (DEPOSIT, "한유나 님 예약금 20,000원 들어왔어", {"booking": "한유나"}),
    (CONFIRM, "1040 주문 확인했어", {"order": "1040"}),
    (PACK, "1042 포장 끝났어", {"order": "1042"}),
    (PACK, "1041 포장 끝났어", {"order": "1041"}),
    (DELIVERED, "1042 배송 완료됐어", {"order": "1042"}),
    (DELIVERED, "1040 배송 완료됐어", {"order": "1040"}),
    (DELIVERED, "1041 배송 완료됐어", {"order": "1041"}),
    (DELIVERED, "1031 배송 완료됐어", {"order": "1031"}),
)


@pytest.mark.parametrize(("deal", "words", "args"), OUT_OF_ORDER)
async def test_a_step_out_of_order_finds_nothing_to_do(
    shop: AsyncEngine, client: AsyncClient, deal: Deal, words: str, args: Body,
) -> None:
    step = await refuses_to_act(shop, client, deal, words, args)
    assert (step["decision"], step["target"]) == ("clarify", None)


async def test_a_deposit_confirmed_in_the_app_stops_the_waiting_proposal(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    _, [proposal] = await turn(client, DEPOSIT, "예약 정리해 줘")
    confirmed = await client.post("/bookings/booking-minwoo/confirm-deposit", json={"expectedRevision": 0})
    assert confirmed.status_code == 200
    before = await everything(shop)
    approved = await client.post(
        f"/agent/proposals/{proposal['id']}/approve", json={"expectedRevision": proposal["expectedRevision"]},
    )
    assert approved.status_code == 409
    assert await everything(shop) == before


USED: Final = "UPDATE shipments SET tracking_number = '6821-0004-2841' WHERE id = 'shipment-order-1038'"


@pytest.mark.parametrize(
    ("words", "setup"), [(INVOICE.said, (USED,)), (f"1040 CJ대한통운 {TRACKING}", ())],
    ids=["number already used", "parcel not packed"],
)
async def test_an_invoice_that_cannot_stand_is_refused_even_on_approval(
    shop: AsyncEngine, client: AsyncClient, words: str, setup: tuple[str, ...],
) -> None:
    for query in setup:
        await execute(shop, query)
    before = await everything(shop)
    step, [proposal] = await turn(client, INVOICE, words)
    assert step["decision"] == "proposed"
    approved = await client.post(
        f"/agent/proposals/{proposal['id']}/approve", json={"expectedRevision": proposal["expectedRevision"]},
    )
    assert approved.status_code == 409
    assert await everything(shop) == before


async def test_the_carrier_comes_from_the_owners_words_and_not_from_the_model(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    step, _ = await turn(client, INVOICE, INVOICE.said, args={"carrier": "한진택배"})
    assert step["decision"] == "auto", step["reason"]
    assert await state(shop, INVOICE) == INVOICE.after


async def test_approving_a_shown_format_warning_registers_the_number(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    odd = TRACKING[:-1]
    step, [proposal] = await turn(client, INVOICE, f"1041 CJ대한통운 {odd}", args={"tracking_number": odd})
    assert step["decision"] == "proposed"
    assert PROBLEM_TEXT[Problem.WRONG_FORMAT] in {line["value"] for line in proposal["preview"]}
    assert await state(shop, INVOICE) == INVOICE.before
    approved = await client.post(
        f"/agent/proposals/{proposal['id']}/approve", json={"expectedRevision": proposal["expectedRevision"]},
    )
    assert approved.status_code == 200, approved.text
    assert await state(shop, INVOICE) == ("in_transit", "CJ대한통운", odd)


async def test_a_quote_proposal_never_shows_the_stored_outcome_code(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    _, [proposal] = await turn(client, QUOTE, "견적 정리해 줘")
    assert str(QUOTE.args["outcome"]) not in str(proposal["preview"])


async def test_a_number_the_agent_registered_is_not_used_for_a_second_parcel(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    for deal in (PACK, INVOICE):
        step, _ = await turn(client, deal, deal.said)
        assert step["decision"] == "auto"
    _ = await refuses_to_act(shop, client, INVOICE, f"1040 CJ대한통운 {TRACKING}", {"order": "1040"})


@every_deal
async def test_a_row_that_changes_while_acting_becomes_a_proposal(
    shop: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, deal: Deal,
) -> None:
    monkeypatch.setattr(agent_perform, "run_auto", racing(agent_perform.run_auto, shop, deal.table, deal.row))
    step, [proposal] = await turn(client, deal, deal.said)
    assert (step["decision"], proposal["expectedRevision"]) == ("proposed", 1)
    assert await state(shop, deal) == deal.before


@every_deal
async def test_undo_is_refused_once_someone_changed_the_row(
    shop: AsyncEngine, client: AsyncClient, deal: Deal,
) -> None:
    step, _ = await turn(client, deal, deal.said)
    assert step["decision"] == "auto"
    table = TABLES[step["target"]["kind"]]
    bump = f"UPDATE {table} SET revision = revision + 1 WHERE id = :id"  # noqa: S608
    await execute(shop, bump, id=step["target"]["id"])
    before = await everything(shop)
    assert (await client.post(f"/agent/steps/{step['id']}/undo")).status_code == 409
    assert await everything(shop) == before


async def test_an_order_confirmation_is_not_undone_after_packing(
    shop: AsyncEngine, client: AsyncClient,
) -> None:
    step, _ = await turn(client, CONFIRM, CONFIRM.said)
    packed, _ = await turn(client, PACK, "1042 포장 끝났어", args={"order": "1042"})
    assert (step["decision"], packed["decision"]) == ("auto", "auto")
    before = await everything(shop)
    assert (await client.post(f"/agent/steps/{step['id']}/undo")).status_code == 409
    assert await everything(shop) == before
