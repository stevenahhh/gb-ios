"""Registering uses the app's own invoice path: revisions hold, and refused rows change nothing."""

from dataclasses import replace
from typing import Final

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agent_invoice import file_text, import_invoices, parse_invoices
from agent_invoice_store import (
    DecidedBy,
    InvoiceChoice,
    InvoiceRequest,
    InvoiceResult,
    Source,
    clean_choices,
    clean_lines,
    load_parcels,
    register_invoices,
)
from agent_invoice_types import PROBLEM_TEXT, Problem
from database import transaction
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
WORDS: Final = "1041 CJ 6103-1111-9284\n1040 CJ 610311119285"
FIRST: Final = InvoiceChoice("shipment-order-1041", 0, "CJ대한통운", "6103-1111-9284")
SECOND: Final = InvoiceChoice("shipment-order-1040", 0, "CJ대한통운", "610311119285")


async def parcels(database: AsyncEngine) -> list[tuple[object, ...]]:
    query = text("SELECT id, status, carrier, tracking_number, revision FROM shipments ORDER BY id")
    async with database.connect() as connection:
        return [tuple(row) for row in (await connection.execute(query)).all()]


async def pack(db: AsyncSession) -> None:
    _ = await db.execute(text(
        "UPDATE shipments SET status = 'invoice_pending' WHERE id = 'shipment-order-1040'",
    ))


async def register(
    *choices: InvoiceChoice, together: bool = True, words: str = WORDS, by: DecidedBy = "owner",
    source: Source = "turn",
) -> list[InvoiceResult]:
    async with transaction() as db:
        return await register_invoices(db, InvoiceRequest(words, choices, together, by, source), NOW)


async def test_the_words_load_match_and_register(database: AsyncEngine) -> None:
    async with transaction() as db:
        await pack(db)
        rows = parse_invoices(WORDS, await load_parcels(db, WORDS), NOW)
        assert not any(row.needs_owner for row in rows)
        request = InvoiceRequest(
            WORDS, clean_choices(rows), all_or_nothing=True, decided_by="auto", source="turn",
        )
        results = await register_invoices(db, request, NOW)
    assert [(r.shipment_id, r.outcome, r.revision_before, r.revision_after) for r in results] == [
        ("shipment-order-1041", "registered", 0, 1), ("shipment-order-1040", "registered", 0, 1),
    ]
    assert results[0].undo_path == "/shipments/shipment-order-1041/undo"
    stored = {row[0]: row[1:] for row in await parcels(database)}
    assert stored["shipment-order-1041"] == ("in_transit", "CJ대한통운", "610311119284", 1)


@pytest.mark.parametrize("bad", [
    replace(FIRST, tracking_number="610311119299"),
    replace(FIRST, carrier="없는택배"),
    replace(FIRST, carrier="우체국택배"),
    replace(FIRST, expected_revision=7),
    replace(FIRST, shipment_id="missing"),
    replace(FIRST, shipment_id="shipment-order-1038"),
    replace(FIRST, shipment_id="shipment-order-1040"),
])
@pytest.mark.parametrize("together", [True, False])
async def test_a_refused_row_explains_itself_and_changes_nothing(
    database: AsyncEngine, bad: InvoiceChoice, *, together: bool,
) -> None:
    before = await parcels(database)
    result, = await register(bad, together=together)
    assert result.outcome == "refused"
    assert result.reason is not None
    assert result.reason.endswith("요.")
    assert await parcels(database) == before


async def test_together_means_one_refusal_stops_every_row(database: AsyncEngine) -> None:
    before = await parcels(database)
    results = await register(FIRST, SECOND)
    assert [result.outcome for result in results] == ["refused", "refused"]
    assert results[0].reason != results[1].reason
    assert await parcels(database) == before


async def test_together_means_a_number_refused_before_locking_stops_every_row(database: AsyncEngine) -> None:
    before = await parcels(database)
    results = await register(FIRST, replace(SECOND, tracking_number="610311119299"))
    assert [result.outcome for result in results] == ["refused", "refused"]
    assert await parcels(database) == before


async def test_together_undoes_rows_already_sent_when_a_later_one_is_stale(database: AsyncEngine) -> None:
    async with transaction() as db:
        await pack(db)
    before = await parcels(database)
    results = await register(SECOND, replace(FIRST, expected_revision=7))
    assert [result.outcome for result in results] == ["refused", "refused"]
    assert await parcels(database) == before


async def test_row_by_row_keeps_the_good_rows(database: AsyncEngine) -> None:
    results = await register(FIRST, SECOND, together=False)
    assert [result.outcome for result in results] == ["registered", "refused"]
    stored = {row[0]: row[1] for row in await parcels(database)}
    assert (stored["shipment-order-1041"], stored["shipment-order-1040"]) == ("in_transit", "packing")


async def test_a_number_already_stored_with_separators_is_refused(database: AsyncEngine) -> None:
    async with transaction() as db:
        _ = await db.execute(text(
            "UPDATE shipments SET tracking_number = '6103-1111-9284' WHERE id = 'shipment-order-1038'",
        ))
    result, = await register(FIRST)
    assert result.outcome == "refused"


@pytest.mark.parametrize("together", [True, False])
async def test_one_number_for_two_parcels_is_refused(database: AsyncEngine, *, together: bool) -> None:
    before = await parcels(database)
    results = await register(FIRST, replace(SECOND, tracking_number="610311119284"), together=together)
    assert [result.outcome for result in results] == ["refused", "refused"]
    assert await parcels(database) == before


async def test_shipped_parcels_load_only_when_the_words_name_them(database: AsyncEngine) -> None:
    async with transaction() as db:
        plain = await load_parcels(db, "CJ 610311119284")
        named = await load_parcels(db, "1038 CJ 610311119284")
        person = await load_parcels(db, "최하서 CJ 610311119284")
    assert 1038 in {parcel.order_number for parcel in person}
    assert 1038 not in {parcel.order_number for parcel in plain}
    assert {parcel.order_number for parcel in named} >= {1038, 1040, 1041}


SHORT: Final = replace(FIRST, tracking_number="61031111928", accept_format=True)


async def test_approval_that_accepts_the_format_registers_an_odd_length(database: AsyncEngine) -> None:
    words = "1041 CJ 61031111928"
    warned, = await register(replace(SHORT, accept_format=False), words=words)
    assert (warned.outcome, warned.reason) == ("refused", PROBLEM_TEXT[Problem.WRONG_FORMAT])
    sent, = await register(SHORT, words=words)
    assert (sent.outcome, sent.revision_after) == ("registered", 1)
    stored = {row[0]: row[3] for row in await parcels(database)}
    assert stored["shipment-order-1041"] == "61031111928"


@pytest.mark.parametrize(("words", "choice"), [
    ("1041 CJ 61031111928\n1041 CJ 61031111928", SHORT),
    ("1041 CJ 61031111928\n1041 CJ 610311119284", SHORT),
    ("1038 CJ 61031111928", replace(SHORT, shipment_id="shipment-order-1038")),
    ("1040 CJ 61031111928", replace(SHORT, shipment_id="shipment-order-1040")),
    ("1040 CJ 61031111928", SHORT),
    ("1099 CJ 61031111928", SHORT),
    ("1041 최하서 CJ 61031111928", SHORT),
    ("1041 CJ 61031111929", SHORT),
    ("1041 CJ", SHORT),
    ("1041 CJ 61031111928", replace(SHORT, carrier="없는택배")),
    ("1041 CJ 61031111928", replace(SHORT, expected_revision=7)),
    ("1041 CJ " + "6" * 41, replace(SHORT, tracking_number="6" * 41)),
])
async def test_accepting_the_format_never_lifts_a_hard_block(
    database: AsyncEngine, words: str, choice: InvoiceChoice,
) -> None:
    before = await parcels(database)
    result, = await register(choice, words=words)
    assert result.outcome == "refused"
    assert await parcels(database) == before


async def test_accepting_the_format_never_reuses_a_stored_number(database: AsyncEngine) -> None:
    async with transaction() as db:
        _ = await db.execute(text(
            "UPDATE shipments SET tracking_number = '6103-1111-928' WHERE id = 'shipment-order-1038'",
        ))
    result, = await register(SHORT, words="1041 CJ 61031111928")
    assert (result.outcome, result.reason) == ("refused", PROBLEM_TEXT[Problem.ALREADY_USED])


@pytest.mark.parametrize(("words", "choice", "source"), [
    ("1041 CJ 61031111928", SHORT, "turn"),
    ("1041 CJ 육일공삼일일일일구이팔사", replace(FIRST, accept_format=True), "turn"),
    ("CJ 610311119284", FIRST, "turn"),
    ("1041 610311119284", FIRST, "turn"),
    ("1041 한진 610311119284", FIRST, "turn"),
    ("1041 CJ 610311119284", FIRST, "file"),
])
async def test_the_automatic_path_refuses_what_approval_allows(
    database: AsyncEngine, words: str, choice: InvoiceChoice, source: Source,
) -> None:
    before = await parcels(database)
    result, = await register(choice, words=words, by="auto", source=source)
    assert result.outcome == "refused"
    assert await parcels(database) == before
    approved, = await register(choice, words=words, by="owner", source=source)
    assert approved.outcome == "registered"


async def test_one_approval_registers_only_the_clean_rows_of_a_file(database: AsyncEngine) -> None:
    data = (
        "발송 목록\n주문번호,송장번호,택배사,받는분\n1041,610311119284,CJ대한통운,\n"
        "1040,61031111928,CJ대한통운,\n"
    ).encode()
    words = file_text(data, "a.csv")
    async with transaction() as db:
        await pack(db)
        known = await load_parcels(db, words)
    rows = import_invoices(data, "a.csv", known, NOW)
    assert parse_invoices(words, known, NOW) == rows
    assert clean_lines(rows) == [3]
    results = await register(*clean_choices(rows), words=words, source="file")
    assert [(r.shipment_id, r.outcome) for r in results] == [("shipment-order-1041", "registered")]
    assert {row[0]: row[1] for row in await parcels(database)}["shipment-order-1040"] == "invoice_pending"
