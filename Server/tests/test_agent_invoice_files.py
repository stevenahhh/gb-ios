"""A carrier program's export is read as text; anything that could run or reach outside is refused."""

import io
import zipfile
from datetime import datetime
from typing import Final

import pytest

import agent_invoice_files
from agent_invoice import file_text, import_invoices, is_verbatim, parse_invoices
from agent_invoice_files import InvoiceFileError, read_table
from agent_invoice_types import Parcel, Problem
from display import SEOUL

NOW: Final = datetime(2026, 11, 18, 11, 0, tzinfo=SEOUL)
OPEN: Final = [
    Parcel("s1040", "o1040", 1040, "invoice_pending", 1, "김가상", "010-0000-1040", None),
    Parcel("s1041", "o1041", 1041, "invoice_pending", 1, "이가상", None, None),
]
CSV: Final = (
    "발송 목록\n주문번호,운송장번호,택배사,수취인,전화,주소\n"
    "1040,6103-1111-9284,CJ대한통운,김가상,010-0000-1040,서울 가상로 12345\n"
    "1041,6865123456789,우체국택배,이가상,,\n합계,2건,,,,\n"
)
MAIN: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
SHEET: Final = (
    '<row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="D1" t="s"><v>2</v></c></row>'
    '<row><c r="A2"><v>1040</v></c><c r="B2"><v>610311119284</v></c>'
    '<c r="D2" t="inlineStr"><is><t>CJ대한통운</t></is></c></row>'
)


def workbook(rows: str = SHEET, extra: dict[str, str] | None = None) -> bytes:
    shared = "".join(f"<si><r><t>{word[:2]}</t></r><r><t>{word[2:]}</t></r></si>" for word in (
        "주문번호", "송장번호", "택배사",
    ))
    parts = {
        "xl/workbook.xml": (
            f'<workbook xmlns="{MAIN}" xmlns:r="{OFFICE}"><sheets>'
            '<sheet name="s" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{PACKAGE}">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
        ),
        "xl/sharedStrings.xml": f'<sst xmlns="{MAIN}">{shared}</sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{MAIN}"><sheetData>{rows}</sheetData></worksheet>',
        **(extra or {}),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as book:
        for name, body in parts.items():
            book.writestr(name, body)
    return buffer.getvalue()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp949"])
def test_csv_exports_match_like_pasted_text(encoding: str) -> None:
    rows = import_invoices(CSV.encode(encoding), "발송.CSV", OPEN, NOW)
    assert [(r.parcel.label if r.parcel else None, r.number, r.needs_owner) for r in rows] == [
        ("#1040", "610311119284", False), ("#1041", "6865123456789", False),
    ]
    assert not any(word in repr(rows) for word in ("가상", "0000", "12345 "))


def test_tab_separated_exports_are_read() -> None:
    tabbed = CSV.replace(",", "\t").replace("발송 목록", "발송\t목록").encode()
    assert len(import_invoices(tabbed, "a.csv", OPEN, NOW)) == 2


def test_xlsx_keeps_numbers_as_text_and_gaps_in_place() -> None:
    assert read_table(workbook(), "a.xlsx") == [
        ["주문번호", "송장번호", "", "택배사"], ["1040", "610311119284", "", "CJ대한통운"],
    ]
    row, = import_invoices(workbook(), "a.xlsx", OPEN, NOW)
    assert (row.number, row.carrier, row.needs_owner) == ("610311119284", "CJ대한통운", False)


def test_a_rounded_spreadsheet_number_is_not_restored() -> None:
    row, = import_invoices(workbook(SHEET.replace("610311119284", "6.10311E+11")), "a.xlsx", OPEN, NOW)
    assert (row.number, row.problems) == ("", (Problem.WRONG_FORMAT,))


@pytest.mark.parametrize(("data", "name"), [
    (CSV.replace("6103-1111-9284", "=1+1").encode(), "a.csv"),
    (b"\xff\xfe\xff\x00\x81", "a.csv"),
    (b"\xd0\xcf\x11\xe0", "a.xls"),
    (workbook(), "a.xlsm"),
    (b"not a zip", "a.xlsx"),
    (workbook()[:200], "a.xlsx"),
    (workbook(SHEET.replace("<v>1040</v>", "<f>1+1</f><v>1040</v>")), "a.xlsx"),
    (workbook(SHEET.replace("<v>0</v>", "<v>99</v>")), "a.xlsx"),
    (workbook(SHEET.replace('r="D1"', 'r="ZZ1"')), "a.xlsx"),
    (workbook(extra={"xl/vbaProject.bin": "x"}), "a.xlsx"),
    (workbook(extra={"xl/externalLinks/externalLink1.xml": "<x/>"}), "a.xlsx"),
    (workbook(extra={"xl/worksheets/_rels/sheet1.xml.rels": (
        f'<Relationships xmlns="{PACKAGE}"><Relationship Id="r" TargetMode="External" Target="http://x"/>'
        "</Relationships>"
    )}), "a.xlsx"),
    (workbook(extra={"xl/sharedStrings.xml": '<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'}), "a.xlsx"),
    (workbook(extra={f"xl/p{index}": "" for index in range(201)}), "a.xlsx"),
])
def test_unsafe_or_broken_files_are_refused_in_korean(data: bytes, name: str) -> None:
    with pytest.raises(InvoiceFileError) as caught:
        _ = import_invoices(data, name, OPEN, NOW)
    assert caught.value.reason.endswith("요.")


@pytest.mark.parametrize(("limit", "value"), [("MAX_BYTES", 10), ("MAX_ROWS", 2), ("MAX_COLUMNS", 3)])
def test_size_limits_refuse_the_file(monkeypatch: pytest.MonkeyPatch, limit: str, value: int) -> None:
    monkeypatch.setattr(agent_invoice_files, limit, value)
    with pytest.raises(InvoiceFileError):
        _ = read_table(CSV.encode(), "a.csv")


def test_an_unpacked_size_limit_refuses_the_workbook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_invoice_files, "MAX_UNZIPPED", 100)
    with pytest.raises(InvoiceFileError):
        _ = read_table(workbook(), "a.xlsx")


def test_a_number_in_the_file_is_verbatim_for_registration() -> None:
    text = file_text(workbook(), "a.xlsx")
    assert is_verbatim("610311119284", text)
    assert not is_verbatim("610311119285", text)


def test_a_file_read_again_as_text_keeps_its_columns_and_their_problems() -> None:
    data = CSV.replace("이가상", "홍가상").encode()
    rows = import_invoices(data, "a.csv", OPEN, NOW)
    assert rows[1].problems == (Problem.RECIPIENT_MISMATCH,)
    assert parse_invoices(file_text(data, "a.csv"), OPEN, NOW) == rows
