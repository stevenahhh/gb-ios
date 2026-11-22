"""QA ag06: an invoice line the owner wrote never reaches another parcel, phone number, or carrier."""

from typing import Final

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_invoice import is_verbatim, parse_invoices
from agent_invoice_types import Parcel, ParcelStatus
from tests.agent_core_support import ask, chat_of, execute, rows, says, set_mode, wants
from tests.conftest import NOW

NUMBER: Final = "610311119284"


def parcel(order: int, status: ParcelStatus = "invoice_pending", name: str = "박지은") -> Parcel:
    return Parcel(f"s{order}", f"o{order}", order, status, 0, name, None, None)


PARCELS: Final = (parcel(1041), parcel(1040, "packing", "최민우"), parcel(1042, name="한진우"))


@pytest.mark.parametrize("words", [
    f"1040 CJ {NUMBER} 1041", f"1040 CJ {NUMBER}, 1041은 나중에", f"1041 말고 1040 CJ {NUMBER}",
])
def test_two_named_orders_are_never_narrowed_to_the_waiting_one(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert row.match == "several"
    assert row.needs_owner


@pytest.mark.parametrize(("phone", "digits"), [
    ("0507-1234-5678", "050712345678"), ("+82 10-1234-5678", "821012345678"),
])
def test_a_phone_number_is_not_a_tracking_number(phone: str, digits: str) -> None:
    assert parse_invoices(f"1041 {phone} CJ", PARCELS, NOW) == []
    assert not is_verbatim(digits, f"1041 {phone} CJ")
    [row] = parse_invoices(f"1041 {phone} CJ {NUMBER}", PARCELS, NOW)
    assert (row.number, row.needs_owner) == (NUMBER, False)


@pytest.mark.parametrize("words", [
    f"1041 CJ 송장번호:{NUMBER}", f"1041 CJ 송장\uff1a{NUMBER}", f"1041:{NUMBER} CJ",
    f"2026-11-22 1041 CJ {NUMBER}", f"14:30 1041 CJ {NUMBER}", "1041 CJ ٦١٠٣١١١١٩٢٨٤",
])
def test_labels_dates_times_and_other_digits_leave_the_number_readable(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert (row.number, row.match, row.needs_owner) == (NUMBER, "one", False)
    assert is_verbatim(NUMBER, words)


@pytest.mark.parametrize("words", [f"1042 한진우 {NUMBER}", f"1041 CJ 한진 {NUMBER}"])
def test_a_name_or_a_second_carrier_is_not_a_certain_carrier(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert row.needs_owner


@pytest.mark.parametrize("words", [
    f"9999 CJ {NUMBER} 1041", f"9999, 1041 CJ {NUMBER}, 1042 CJ 610311119285",
])
def test_an_unknown_order_number_on_the_line_is_named_to_the_owner(words: str) -> None:
    for row in parse_invoices(words, PARCELS, NOW):
        assert (row.unknown_orders, row.needs_owner, row.blocks) == ((9999,), True, ())


@pytest.mark.parametrize("words", [
    f"1041 롯데캐슬 {NUMBER}", f"1041 롯데로 12 {NUMBER}",
    f"주문번호,송장번호,주소\n1041,{NUMBER},롯데캐슬 101동",
    f"주문번호,송장번호,주소\n1041,{NUMBER},롯데 캐슬", f"주문번호,송장번호,받는분\n1042,{NUMBER},한진우",
])
def test_an_address_or_a_recipient_never_gives_a_carrier(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert (row.carrier, row.needs_owner) == (None, True)


@pytest.mark.parametrize("words", [
    f"1041 CJ{NUMBER}", f"CJ로 보냈어\n1041 {NUMBER}", f"1041 cj택배 {NUMBER}",
    f"주문번호,송장번호,택배사,주소\n1041,{NUMBER},CJ,롯데캐슬",
])
def test_a_whole_carrier_name_still_counts(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert (row.carrier, row.needs_owner) == ("CJ대한통운", False)


@pytest.mark.parametrize("words", [
    "1041 CJ 110-123-456789 계좌", f"1041 CJ {NUMBER} 입금", f"1041 국민은행 {NUMBER} CJ",
    f"1041 농협 CJ {NUMBER}",
])
def test_a_bank_line_is_never_a_clear_invoice(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert (row.needs_owner, row.blocks) == (True, ())


@pytest.mark.anyio
@pytest.mark.postgres
@pytest.mark.parametrize(("words", "number", "shown"), [
    (f"9999 CJ {NUMBER} 1041", NUMBER, "9999"), ("1041 CJ 110-123-456789 계좌", "110123456789", "계좌"),
])
async def test_an_unclear_line_becomes_a_proposal_and_moves_nothing(
    database: AsyncEngine, client: AsyncClient, words: str, number: str, shown: str,
) -> None:
    await set_mode(database, "auto")
    query = "SELECT id, status, tracking_number, revision FROM shipments ORDER BY id"
    before = await rows(database, query)
    call = wants("register_invoice", tracking_number=number, order="1041", carrier="CJ대한통운")
    _ = await ask(client, chat_of(call, says("네")), words)
    [preview] = await rows(database, "SELECT cast(preview AS text) FROM agent_proposals WHERE state = 'open'")
    assert shown in str(preview[0])
    assert await rows(database, query) == before


OWNER_NUMBER: Final = "682100042841"


@pytest.mark.parametrize("words", [
    f"1040 포장 끝났어. 1041 CJ {NUMBER}", f"1041 CJ {NUMBER}. 1040 포장 끝났어",
    f"9999 끝났어. 1041 CJ {NUMBER}",
])
def test_an_order_in_another_sentence_is_not_ambiguous(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert (row.match, row.candidates[0].label, row.needs_owner) == ("one", "#1041", False)


@pytest.mark.parametrize("words", [
    f"1041 나갔어. CJ {NUMBER}", f"1041 CJ {NUMBER}. 계좌번호야", f"1040 CJ {NUMBER} 1041. 확인해 줘",
])
def test_a_sentence_without_its_own_clear_order_goes_to_the_owner(words: str) -> None:
    [row] = parse_invoices(words, PARCELS, NOW)
    assert row.needs_owner


@pytest.mark.anyio
@pytest.mark.postgres
@pytest.mark.parametrize(("words", "decision"), [
    (f"1040 포장 끝났어. 1041 송장번호 CJ대한통운 {OWNER_NUMBER}이야", "auto"),
    (f"1041 CJ대한통운 {OWNER_NUMBER} 송장 등록해 줘", "auto"),
    (f"CJ대한통운 {OWNER_NUMBER}", "proposed"),
])
async def test_the_owners_own_sentence_decides_the_invoice(
    database: AsyncEngine, client: AsyncClient, words: str, decision: str,
) -> None:
    await set_mode(database, "auto")
    call = wants("register_invoice", tracking_number=OWNER_NUMBER, order="1041", carrier="CJ대한통운")
    _ = await ask(client, chat_of(call, says("네")), words)
    assert await rows(database, "SELECT decision FROM agent_steps") == [(decision,)]
    query = "SELECT status, tracking_number FROM shipments WHERE id = 'shipment-order-1041'"
    expected = ("in_transit", OWNER_NUMBER) if decision == "auto" else ("invoice_pending", None)
    assert await rows(database, query) == [expected]


def test_many_short_groups_join_only_up_to_a_storable_number() -> None:
    assert not is_verbatim("1" * 41, "1 " * 41)
    assert is_verbatim("1" * 40, "1 " * 41)


@pytest.mark.anyio
@pytest.mark.postgres
@pytest.mark.parametrize("words", [f"1040 CJ {NUMBER} 1041", f"1040 CJ {NUMBER}"])
async def test_no_parcel_moves_for_an_unclear_or_unpacked_order(
    database: AsyncEngine, client: AsyncClient, words: str,
) -> None:
    await set_mode(database, "auto")
    query = "SELECT id, status, tracking_number, revision FROM shipments ORDER BY id"
    before = await rows(database, query)
    call = wants("register_invoice", tracking_number=NUMBER, order="1040", carrier="CJ대한통운")
    body = await ask(client, chat_of(call, says("네")), words)
    assert await rows(database, query) == before, body


@pytest.mark.anyio
@pytest.mark.postgres
async def test_a_number_stored_with_hyphens_is_already_used(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    await set_mode(database, "auto")
    await execute(
        database,
        """UPDATE shipments SET tracking_number = '6103-1111-9284', carrier = :carrier, status = 'in_transit'
        WHERE id = 'shipment-order-1040'""",
        carrier="CJ대한통운",
    )
    call = wants("register_invoice", tracking_number=NUMBER, order="1041", carrier="CJ대한통운")
    _ = await ask(client, chat_of(call, says("네")), f"1041 CJ {NUMBER}")
    query = "SELECT status, tracking_number FROM shipments WHERE id = 'shipment-order-1041'"
    assert await rows(database, query) == [("invoice_pending", None)]
