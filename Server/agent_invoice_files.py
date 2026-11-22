"""Read a carrier program's CSV or XLSX export as text cells; formulas, macros, and links are refused."""

import csv
import io
import posixpath
import zipfile
import zlib
from collections.abc import Iterator
from pathlib import PurePath
from typing import Final
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

MAX_BYTES: Final = 2 * 1024 * 1024
MAX_UNZIPPED: Final = 20 * 1024 * 1024
MAX_MEMBERS: Final = 200
MAX_ROWS: Final = 2000
MAX_COLUMNS: Final = 60
MAIN: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELS: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"
REL_ID: Final = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class InvoiceFileError(Exception):
    """A file that cannot be read safely; the message is written for the owner in Korean."""

    def __init__(self, reason: str) -> None:
        """Keep the Korean reason the caller shows."""
        super().__init__(reason)
        self.reason: Final = reason


def read_table(data: bytes, filename: str) -> list[list[str]]:
    """Return the rows of a CSV or XLSX file with every value kept as text."""
    if len(data) > MAX_BYTES:
        msg = "한 번에 2MB까지 불러와요. 파일을 쪼개서 다시 올려 주세요."
        raise InvoiceFileError(msg)
    match PurePath(filename).suffix.lower():
        case ".csv":
            return read_csv(data)
        case ".xlsx":
            return read_xlsx(data)
        case _:
            msg = "엑셀 파일, 그러니까 CSV나 XLSX만 열어 볼 수 있어요."
            raise InvoiceFileError(msg)


def checked(rows: Iterator[list[str]]) -> list[list[str]]:
    """Apply the row and column limits while reading."""
    kept: list[list[str]] = []
    for row in rows:
        if len(kept) >= MAX_ROWS or len(row) > MAX_COLUMNS:
            msg = "줄과 칸이 한도를 넘었어요. 파일을 여러 개로 쪼개 주세요."
            raise InvoiceFileError(msg)
        kept.append(row)
    return kept


def decoded(data: bytes) -> str:
    """Decode UTF-8 or the CP949 that Korean Excel writes."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\0" not in text:
            return text
    msg = "글자가 깨져 보여요. 엑셀에서 UTF-8 CSV 형식으로 바꿔 올려 주세요."
    raise InvoiceFileError(msg)


def read_csv(data: bytes) -> list[list[str]]:
    """Read comma or tab separated text; a formula cell refuses the file."""
    text = decoded(data)
    delimiter = "\t" if "\t" in text.partition("\n")[0] else ","
    try:
        rows = checked(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as error:
        msg = "규칙에 안 맞는 CSV 파일이에요."
        raise InvoiceFileError(msg) from error
    if any(cell.lstrip().startswith("=") for row in rows for cell in row):
        msg = "수식이 들어간 칸이 있으면 못 열어요. 수식 대신 결과값만 남겨 올려 주세요."
        raise InvoiceFileError(msg)
    return rows


def read_xlsx(data: bytes) -> list[list[str]]:
    """Read the first sheet of a workbook that has no macros, external links, or formulas."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            refuse_unsafe(book)
            return checked(sheet_rows(fromstring(book.read(first_sheet(book))), shared_strings(book)))
    except (
        zipfile.BadZipFile, KeyError, IndexError, ValueError, RuntimeError, NotImplementedError, EOFError,
        ParseError, DefusedXmlException, zlib.error,
    ) as error:
        msg = "엑셀이 망가졌거나 다른 종류 파일 같아요."
        raise InvoiceFileError(msg) from error


def refuse_unsafe(book: zipfile.ZipFile) -> None:
    """Refuse oversized archives, macros, and links to other files before reading any sheet."""
    members = book.infolist()
    if len(members) > MAX_MEMBERS or sum(member.file_size for member in members) > MAX_UNZIPPED:
        msg = "압축을 풀었더니 용량이 너무 커요."
        raise InvoiceFileError(msg)
    names = [member.filename.lower() for member in members]
    if any("vbaproject" in name or "macrosheets/" in name for name in names):
        msg = "엑셀에 매크로가 있으면 열지 않아요."
        raise InvoiceFileError(msg)
    external = any(
        rel.get("TargetMode") == "External"
        for member in members if member.filename.endswith(".rels")
        for rel in fromstring(book.read(member)).iter(f"{RELS}Relationship")
    )
    if external or any("externallinks/" in name for name in names):
        msg = "외부 파일을 끌어다 쓰는 엑셀은 안 받아요."
        raise InvoiceFileError(msg)


def first_sheet(book: zipfile.ZipFile) -> str:
    """Find the archive path of the first sheet the workbook lists."""
    sheet = next(fromstring(book.read("xl/workbook.xml")).iter(f"{MAIN}sheet"), None)
    wanted = sheet.get(REL_ID) if sheet is not None else None
    for rel in fromstring(book.read("xl/_rels/workbook.xml.rels")).iter(f"{RELS}Relationship"):
        if rel.get("Id") == wanted:
            return posixpath.normpath(posixpath.join("/xl", rel.get("Target", ""))).lstrip("/")
    raise KeyError(wanted)


def spelled(node: Element) -> str:
    """Join the text runs of one string."""
    return "".join(part.text or "" for part in node.iter(f"{MAIN}t"))


def shared_strings(book: zipfile.ZipFile) -> list[str]:
    """Read the workbook's shared strings, if it has any."""
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    return [spelled(item) for item in fromstring(book.read("xl/sharedStrings.xml")).iter(f"{MAIN}si")]


def column(reference: str) -> int:
    """Turn the letters of a cell reference such as C7 into a zero-based column."""
    index = 0
    for letter in reference:
        if not letter.isalpha():
            break
        index = index * 26 + ord(letter.upper()) - ord("A") + 1
    return index - 1


def cell_text(cell: Element, strings: list[str]) -> str:
    """Return a cell's value as the text the file stores."""
    if cell.find(f"{MAIN}f") is not None:
        msg = "수식이 들어간 칸이 있으면 못 열어요. 수식 대신 결과값만 남겨 올려 주세요."
        raise InvoiceFileError(msg)
    if cell.get("t") == "inlineStr":
        return spelled(cell)
    value = cell.findtext(f"{MAIN}v") or ""
    return strings[int(value)] if cell.get("t") == "s" else value


def sheet_rows(sheet: Element, strings: list[str]) -> Iterator[list[str]]:
    """Yield each row with blanks where the sheet skips a cell."""
    for row in sheet.iter(f"{MAIN}row"):
        cells: dict[int, str] = {}
        for place, cell in enumerate(row.iter(f"{MAIN}c")):
            reference = cell.get("r")
            index = column(reference) if reference else place
            if not 0 <= index < MAX_COLUMNS:
                msg = "줄과 칸이 한도를 넘었어요. 파일을 여러 개로 쪼개 주세요."
                raise InvoiceFileError(msg)
            cells[index] = cell_text(cell, strings)
        yield [cells.get(index, "") for index in range(max(cells, default=-1) + 1)]
