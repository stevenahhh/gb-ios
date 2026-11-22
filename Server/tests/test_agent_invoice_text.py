"""Tracking numbers are read from the owner's words exactly, matched to one parcel, or handed back."""

from datetime import datetime
from typing import Final

import pytest

from agent_invoice import is_verbatim, parse_invoices
from agent_invoice_types import CHECK_LABEL, InvoiceRow, Parcel, ParcelStatus, Problem
from display import SEOUL

NOW: Final = datetime(2026, 11, 18, 11, 0, tzinfo=SEOUL)
CJ: Final = "CJ대한통운"
FULL_WIDTH: Final = {code: code + 0xFEE0 for code in range(0x21, 0x7F)}


def parcel(
    number: int, recipient: str = "김서연", status: ParcelStatus = "invoice_pending", used: str | None = None,
) -> Parcel:
    return Parcel(f"s{number}", f"o{number}", number, status, 1, recipient, f"010-{number}-2222", used)


OPEN: Final = [
    parcel(1040), parcel(1041, "이수진"), parcel(1038, "최하서", "in_transit", "6103-1111-9200"),
    parcel(1031, "윤수아", "delivered", "682100042841"), parcel(1045, "박지은", "packing"),
]
ONE: Final = [parcel(1041, "이수진")]
TWINS: Final = [parcel(1040), parcel(1046)]


def only(text: str, parcels: list[Parcel]) -> InvoiceRow:
    rows = parse_invoices(text, parcels, NOW)
    assert len(rows) == 1, rows
    return rows[0]


def target(row: InvoiceRow) -> int | None:
    return int(row.parcel.label.removeprefix("#")) if row.parcel else None


@pytest.mark.parametrize(("text", "order", "number", "carrier"), [
    ("1040 CJ 610311119284", 1040, "610311119284", CJ),
    ("610311119284 CJ 1040", 1040, "610311119284", CJ),
    ("#1040 cj대한통운 6103-1111-9284", 1040, "610311119284", CJ),
    ("1040 CJ 6103 1111 9284", 1040, "610311119284", CJ),
    ("1040 6103 1111 9284 CJ", 1040, "610311119284", CJ),
    ("1040,CJ,610311119284", 1040, "610311119284", CJ),
    ("1040 씨제이 6103.1111.9284", 1040, "610311119284", CJ),
    ("1040 CJ 6103\u20131111\u20139284", 1040, "610311119284", CJ),
    ("1040 CJ 610311119284".translate(FULL_WIDTH), 1040, "610311119284", CJ),
    ("1041번 한진택배 610311119284", 1041, "610311119284", "한진택배"),
    ("1041번 주문 롯데로 보냈어 610311119284야", 1041, "610311119284", "롯데택배"),
    ("1041 우체국 6865-1234-56789", 1041, "6865123456789", "우체국택배"),
    ("1041건은 로젠 61031111928", 1041, "61031111928", "로젠택배"),
    ("천사십번 CJ 610311119284예요", 1040, "610311119284", CJ),
    ("2026년 11월 18일 16:00에 1040 CJ 610311119284", 1040, "610311119284", CJ),
    ("1040 머그컵 2개 42000원 CJ 610311119284", 1040, "610311119284", CJ),
    ("이수진님 거 CJ 610311119284", 1041, "610311119284", CJ),
    ("이수진 010-1041-2222 CJ 610311119284", 1041, "610311119284", CJ),
    ("010-1041-2222 CJ 610311119284", 1041, "610311119284", CJ),
    ("1040 김서연 CJ 610311119284", 1040, "610311119284", CJ),
])
def test_a_clear_row_is_ready(text: str, order: int, number: str, carrier: str) -> None:
    row = only(text, OPEN)
    assert (target(row), row.number, row.carrier, row.carrier_status) == (order, number, carrier, "known")
    assert (row.problems, row.needs_owner, row.check, row.checked_at) == ((), False, "format_only", NOW)
    assert row.confidence >= 0.85


@pytest.mark.parametrize("text", ["CJ 610311119284", "송장 CJ 610311119284 이거야"])
def test_a_bare_number_proposes_the_only_open_order(text: str) -> None:
    row = only(text, ONE)
    assert (target(row), row.problems, row.confidence) == (1041, (), 0.6)
    assert row.needs_owner


@pytest.mark.parametrize(("text", "parcels", "match"), [
    ("CJ 610311119284", OPEN, "several"),
    ("김서연 CJ 610311119284", TWINS, "several"),
    ("CJ 610311119284", [], "none"),
    ("1099 CJ 610311119284", ONE, "none"),
    ("주문 99999 CJ 610311119284", ONE, "none"),
    ("CJ 610311119284", [parcel(1045, "박지은", "packing")], "none"),
])
def test_an_unclear_order_is_never_chosen(text: str, parcels: list[Parcel], match: str) -> None:
    row = only(text, parcels)
    assert (row.match, row.parcel, row.needs_owner, row.confidence) == (match, None, True, 0)
    assert (len(row.candidates) == 2) == (match == "several")


def test_an_order_number_settles_two_orders_of_one_recipient() -> None:
    assert target(only("1046 김서연 CJ 610311119284", TWINS)) == 1046


@pytest.mark.parametrize(("text", "problem"), [
    ("1038 CJ 610311119284", Problem.ALREADY_SHIPPED),
    ("1031 CJ 610311119284", Problem.ALREADY_SHIPPED),
    ("1045 CJ 610311119284", Problem.NOT_PACKED),
    ("1040 CJ 610311119200", Problem.ALREADY_USED),
    ("1040 CJ 6821-0004-2841", Problem.ALREADY_USED),
    ("1040 CJ 61031111928", Problem.WRONG_FORMAT),
    ("1040 우체국 610311119284", Problem.WRONG_FORMAT),
    ("1040 로젠 610311119284", Problem.WRONG_FORMAT),
    ("1040 CJ 6103111192841234", Problem.WRONG_FORMAT),
    ("1040 61031111", Problem.WRONG_FORMAT),
    ("1040 이수진 CJ 610311119284", Problem.RECIPIENT_MISMATCH),
    ("1040 CJ 610311119284 010-9999-8888", Problem.RECIPIENT_MISMATCH),
    ("1040 CJ 육일공삼 일일일일 구이팔사", Problem.SPOKEN_DIGITS),
])
def test_every_problem_goes_to_the_owner(text: str, problem: Problem) -> None:
    row = only(text, OPEN)
    assert row.problems == (problem,)
    assert CHECK_LABEL[problem] in {check.label for check in row.checks if not check.passed}
    assert row.needs_owner
    assert row.confidence <= 0.3


@pytest.mark.parametrize("text", [
    "1040 CJ 610311119284\n1041 CJ 610311119284",
    "1040 CJ 610311119284\n1040 CJ 610311119285",
    "1040 CJ 610311119284 CJ 610311119284",
])
def test_a_repeated_number_or_order_flags_both_rows(text: str) -> None:
    rows = parse_invoices(text, OPEN, NOW)
    assert [Problem.DUPLICATE_IN_TEXT in row.problems for row in rows] == [True, True]


@pytest.mark.parametrize(("text", "number"), [
    ("1040 씨제이 육일공삼 일일일일 구이팔사예요", "610311119284"),
    ("1040 CJ 육일영삼일일일일구이팔사이고", "610311119284"),
    ("1040 CJ 륙칠팔구공오사삼이일빵육", "678905432106"),
])
def test_dictated_digits_keep_every_digit_and_drop_particles(text: str, number: str) -> None:
    row = only(text, OPEN)
    assert (row.number, target(row)) == (number, 1040)


@pytest.mark.parametrize(("text", "carrier"), [
    ("1040 대한퉁운 610311119284", CJ), ("1040 로잰택배 61031111928", "로젠택배"),
    ("1040 롯대택배 610311119284", "롯데택배"), ("1040 우채국 6865123456789", "우체국택배"),
    ("1040 6865123456789", "우체국택배"),
])
def test_a_misspelled_or_implied_carrier_is_only_a_guess(text: str, carrier: str) -> None:
    row = only(text, OPEN)
    assert (row.carrier, row.carrier_status, row.needs_owner) == (carrier, "guessed", True)


def test_a_length_several_carriers_share_stays_unknown() -> None:
    row = only("1040 610311119284", OPEN)
    assert (row.carrier, row.carrier_status, row.needs_owner) == (None, "unknown", True)


def test_a_carrier_for_everything_is_known_but_a_neighbour_is_a_guess() -> None:
    stated = parse_invoices("오늘 다 CJ로 보냈어\n1040 610311119284\n1041 610311119285", OPEN, NOW)
    assert [row.carrier_status for row in stated] == ["known", "known"]
    beside = parse_invoices("1040 CJ 610311119284\n1041 610311119285", OPEN, NOW)
    assert [row.carrier_status for row in beside] == ["known", "guessed"]


@pytest.mark.parametrize("text", [
    "1040 CJ 610311119284\n1041 한진 610311119285",
    "1040 CJ 610311119284, 1041 한진 610311119285",
    "1040 CJ 610311119284 1041 한진 610311119285",
    """주문번호\t송장번호\t택배사\t받는분
1040\t610311119284\tCJ대한통운\t김서연
1041\t6103-1111-9285\t한진택배\t이수진
합계\t2건\t\t""",
    "받는분,택배사,운송장번호,주문번호\n김서연,CJ,610311119284,1040\n이수진,한진,610311119285,1041",
])
def test_several_rows_keep_their_own_order_and_carrier(text: str) -> None:
    rows = parse_invoices(text, OPEN, NOW)
    assert [(target(row), row.number, row.carrier) for row in rows] == [
        (1040, "610311119284", CJ), (1041, "610311119285", "한진택배"),
    ]
    assert not any(row.needs_owner for row in rows)


def test_values_under_the_wrong_headers_are_only_proposed() -> None:
    row = only("송장번호,주문번호,택배사\n1040,610311119284,CJ대한통운", OPEN)
    assert (target(row), row.number, row.problems) == (1040, "610311119284", (Problem.COLUMNS_SWAPPED,))


@pytest.mark.parametrize("value", ["010-1234-5678", "6.10311E+11", "김서연"])
def test_a_tracking_column_without_a_number_is_not_repaired(value: str) -> None:
    row = only(f"주문번호,송장번호,택배사\n1040,{value},CJ", OPEN)
    assert (row.number, row.excerpt, row.problems) == ("", "", (Problem.WRONG_FORMAT,))


def test_a_header_row_checks_the_recipient() -> None:
    row = only("주문번호,송장번호,택배사,수취인\n1040,610311119284,CJ,홍길동", OPEN)
    assert row.problems == (Problem.RECIPIENT_MISMATCH,)


@pytest.mark.parametrize("text", [
    "", "포장할 거 있어?", "이번 주 일정 알려 줘", "1040 포장 끝났어", "1040 010-1234-5678",
    "02-1234-5678로 전화 줘", "01012345678", "1040 42000원", "#1041", "합계 610311119284",
])
def test_text_without_a_tracking_number_gives_no_row(text: str) -> None:
    assert parse_invoices(text, OPEN, NOW) == []


def test_rows_carry_no_personal_data() -> None:
    row = only("1040 김서연 010-1040-2222 CJ 610311119284", OPEN)
    assert "김서연" not in repr(row)
    assert "2222" not in repr(row)
    assert "서연" not in repr(only("송장번호,주문번호\n김서연,1040", OPEN))


@pytest.mark.parametrize(("number", "text", "expected"), [
    ("610311119284", "1040 CJ 6103-1111-9284", True),
    ("6103-1111-9284", "1040 CJ 610311119284", True),
    ("610311119284", "육일공삼 일일일일 구이팔사", True),
    ("610311119285", "1040 CJ 610311119284", False),
    ("61031111928", "1040 CJ 610311119284", False),
    ("1040610311119284", "1040 610311119284", False),
    ("01012345678", "010-1234-5678", False),
    ("", "1040", False),
])
def test_verbatim_means_the_whole_number_as_written(number: str, text: str, *, expected: bool) -> None:
    assert is_verbatim(number, text) is expected


def test_dictated_single_digit_syllables_map_one_to_one() -> None:
    row = only("1040 CJ 공일이삼사오육칠팔구영일", OPEN)
    assert row.number == "012345678901"
