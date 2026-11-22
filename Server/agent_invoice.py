"""Match tracking numbers the owner typed, pasted, dictated, or uploaded to parcels awaiting an invoice.

A number is only ever read from the owner's own text or file; nothing here invents or repairs one.
Any row with a problem, an unclear match, or a carrier that is not certain needs the owner.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal

from agent_invoice_files import read_table
from agent_invoice_text import (
    MAX_ORDER_DIGITS,
    PHONE,
    Candidate,
    Entry,
    clauses,
    normalize,
    sentences,
    table_entries,
    text_rows,
    verbatim_numbers,
)
from agent_invoice_types import CarrierStatus, InvoiceRow, MatchKind, Parcel, Problem
from agent_types import BY_FULL_NAME, BY_IDENTIFIER
from carriers import (
    MIN_DIGITS,
    Carrier,
    CarrierMention,
    carriers_for_length,
    find_carriers,
    has_valid_format,
)

type MatchBasis = Literal["order", "person", "only_open", "none"]
BASIS_CONFIDENCE: Final[Mapping[MatchBasis, float]] = {
    "order": BY_IDENTIFIER, "person": BY_FULL_NAME, "only_open": 0.6, "none": 0.0,
}
CARRIER_CONFIDENCE: Final[Mapping[CarrierStatus, float]] = {"known": 1.0, "guessed": 0.8, "unknown": 0.6}
PROBLEM_CEILING: Final = 0.3
SEPARATORS: Final = re.compile(r"[ .-]")
BANK: Final = re.compile(
    (
        r"계좌|입금|은행|뱅크|카뱅|농협|수협|신협|새마을금고|신한|국민|토스|(?<![a-z])(?:kb|nh|ibk|sc제일)(?![a-z])"
        r"|(?:하나|우리|기업)\s*\d{2,6}-\d"
    ),
)


@dataclass(frozen=True, slots=True)
class Draft:
    """A number and everything its row or clause said about it."""

    line: int
    number: Candidate
    orders: tuple[int, ...]
    people: tuple[str, ...]
    phones: tuple[str, ...]
    carrier: CarrierMention | None
    spoken: bool
    swapped: bool = False
    unknown: tuple[int, ...] = ()


def compact(text: str) -> str:
    """Compare names and phones without spaces or separators."""
    return re.sub(r"[\s.-]", "", normalize(text)[0])


def is_verbatim(number: str, text: str) -> bool:
    """Tell whether the owner's text spells out exactly this number, separators aside."""
    return compact(number) in verbatim_numbers(text)


def nearest(mentions: Sequence[CarrierMention], position: int) -> CarrierMention | None:
    """Pick the carrier named closest before a number, else the first one after it."""
    before = [mention for mention in mentions if mention.start <= position]
    return before[-1] if before else next(iter(mentions), None)


def cell_draft(entry: Entry, parcels: Sequence[Parcel]) -> Draft | None:
    """Read a row under a header; a short number in the tracking column swaps with a long order number."""
    tracking, order = entry.cell("tracking") or "", entry.cell("order") or ""
    order_digits = len(re.sub(r"\D", "", order))
    swapped = len(re.sub(r"\D", "", tracking)) <= MAX_ORDER_DIGITS and order_digits >= MIN_DIGITS
    if swapped:
        tracking, order = order, tracking
    if not tracking:
        return None
    number = SEPARATORS.sub("", tracking)
    if not (number.isascii() and number.isdigit()) or PHONE.fullmatch(tracking):
        number = tracking = ""
    reference = re.search(r"\d{1,9}", order)
    orders = (int(reference.group()),) if reference else ()
    mentions = find_carriers(entry.cell("carrier") or without_people(entry.text, entry, parcels))
    person, phone = entry.cell("recipient"), entry.cell("phone")
    return Draft(
        entry.line, Candidate(number, tracking, 0), orders, (compact(person),) if person else (),
        (compact(phone),) if phone else (), next(iter(mentions), None), entry.spoken, swapped,
    )


def without_people(text: str, entry: Entry, parcels: Sequence[Parcel]) -> str:
    """Blank out recipients and address cells, so neither is read as a carrier."""
    hidden = [normalize(parcel.recipient)[0].strip() for parcel in parcels]
    hidden += [value for role, value in entry.cells if role in {"address", "recipient"}]
    for words in hidden:
        text = text.replace(words, "_" * len(words))
    return text


def free_drafts(entry: Entry, parcels: Sequence[Parcel], known: frozenset[int]) -> list[Draft]:
    """Read free text clause by clause, pairing order numbers with numbers when the counts agree."""
    drafts: list[Draft] = []
    parts = clauses(entry, known)
    unknown = tuple(sorted({order for _, mentions in parts for order in mentions.orders} - known))
    for text, mentions in parts:
        flat = compact(text)
        people = tuple(sorted({compact(p.recipient) for p in parcels if compact(p.recipient) in flat}))
        carriers = find_carriers(without_people(text, entry, parcels))
        if len(mentions.numbers) == 1 and len({mention.carrier for mention in carriers}) > 1:
            carriers = [replace(mention, certainty="guessed") for mention in carriers]
        paired = len(mentions.orders) == len(mentions.numbers)
        for index, number in enumerate(mentions.numbers):
            orders = (mentions.orders[index],) if paired else mentions.orders
            carrier = nearest(carriers, number.start)
            drafts.append(Draft(
                entry.line, number, orders, people, mentions.phones, carrier, entry.spoken,
                unknown=unknown,
            ))
    return drafts


def same_person(parcel: Parcel, draft: Draft) -> bool:
    """Tell whether the name or phone the owner gave belongs to this parcel's recipient."""
    return compact(parcel.recipient) in draft.people or (
        parcel.phone is not None and compact(parcel.phone) in draft.phones
    )


def pool_for(draft: Draft, parcels: Sequence[Parcel]) -> tuple[list[Parcel], MatchBasis]:
    """Choose the parcels a row can mean, and on what basis."""
    if draft.orders:
        return [p for p in parcels if p.order_number in draft.orders], "order"
    if draft.people or draft.phones:
        return [p for p in parcels if same_person(p, draft)], "person"
    return list(parcels), "only_open"


def resolve(draft: Draft, parcels: Sequence[Parcel]) -> tuple[MatchKind, list[Parcel], MatchBasis, bool]:
    """Match one row: exactly one awaiting parcel, none, or several; and whether the person disagrees."""
    pool, basis = pool_for(draft, parcels)
    waiting = [p for p in pool if p.status == "invoice_pending"]
    single = len(set(draft.orders)) <= 1
    chosen = waiting if (waiting and single) or basis == "only_open" else pool
    kind: MatchKind = "one" if len(chosen) == 1 else "several" if chosen else "none"
    mismatch = basis == "order" and bool(draft.people or draft.phones) and not any(
        same_person(parcel, draft) for parcel in pool
    )
    return kind, chosen, basis if kind == "one" else "none", mismatch


@dataclass(frozen=True, slots=True)
class CarrierDefault:
    """The one carrier named elsewhere: stated for every parcel, or only beside another number."""

    carrier: Carrier
    status: CarrierStatus


def carrier_of(draft: Draft, default: CarrierDefault | None) -> tuple[Carrier | None, CarrierStatus]:
    """Take the carrier the row named, the one carrier the whole text named, or a unique length."""
    if draft.carrier is not None:
        return draft.carrier.carrier, draft.carrier.certainty
    if default is not None:
        return default.carrier, default.status
    by_length = carriers_for_length(len(draft.number.digits))
    return (by_length[0], "guessed") if len(by_length) == 1 else (None, "unknown")


@dataclass(frozen=True, slots=True)
class Context:
    """What every row is checked against."""

    parcels: Sequence[Parcel]
    used: frozenset[str]
    default: CarrierDefault | None
    bank_lines: frozenset[int]
    now: datetime


def row_for(draft: Draft, context: Context) -> InvoiceRow:
    """Turn a draft into a checked row with its problems and confidence."""
    kind, chosen, basis, mismatch = resolve(draft, context.parcels)
    carrier, status = carrier_of(draft, context.default)
    target = chosen[0] if kind == "one" else None
    problems = [
        problem for problem, present in (
            (Problem.ALREADY_USED, draft.number.digits in context.used),
            (Problem.ALREADY_SHIPPED, target is not None and target.status in {"in_transit", "delivered"}),
            (Problem.NOT_PACKED, target is not None and target.status == "packing"),
            (Problem.WRONG_FORMAT, not has_valid_format(carrier, draft.number.digits)),
            (Problem.RECIPIENT_MISMATCH, mismatch),
            (Problem.SPOKEN_DIGITS, draft.spoken),
            (Problem.COLUMNS_SWAPPED, draft.swapped),
            (Problem.UNKNOWN_ORDER, bool(draft.unknown)),
            (Problem.BANK_LINE, draft.line in context.bank_lines),
        ) if present
    ]
    trust = BASIS_CONFIDENCE[basis] * CARRIER_CONFIDENCE[status]
    confidence = round(min(trust, PROBLEM_CEILING) if problems else trust, 2)
    return InvoiceRow(
        line=draft.line, number=draft.number.digits, excerpt=draft.number.excerpt.strip(), match=kind,
        candidates=tuple(parcel.target for parcel in chosen),
        carrier=carrier.name if carrier else None, carrier_status=status, check="format_only",
        problems=tuple(problems), confidence=confidence, checked_at=context.now,
        unknown_orders=draft.unknown,
    )


def flag_duplicates(rows: list[InvoiceRow]) -> list[InvoiceRow]:
    """Mark rows whose number, or whose matched parcel, appears more than once."""
    numbers = Counter(row.number for row in rows if row.number)
    targets = Counter(row.parcel.id for row in rows if row.parcel)
    flagged: list[InvoiceRow] = []
    for row in rows:
        repeated = numbers[row.number] > 1 or (row.parcel and targets[row.parcel.id] > 1)
        problems = (*row.problems, Problem.DUPLICATE_IN_TEXT) if repeated else row.problems
        ceiling = PROBLEM_CEILING if repeated else 1.0
        flagged.append(replace(row, problems=problems, confidence=min(row.confidence, ceiling)))
    return flagged


def rows_for(entries: Sequence[Entry], parcels: Sequence[Parcel], now: datetime) -> list[InvoiceRow]:
    """Check every number the entries name against the parcels."""
    known = frozenset(parcel.order_number for parcel in parcels)
    drafts: list[Draft] = []
    stated: set[Carrier] = set()
    beside: set[Carrier] = set()
    for entry in entries:
        if entry.cell("tracking") is not None:
            single = cell_draft(entry, parcels)
            found = [single] if single else []
        else:
            found = free_drafts(entry, parcels, known)
        drafts.extend(found)
        words = entry.cell("carrier") or without_people(entry.text, entry, parcels)
        named = {m.carrier for m in find_carriers(words) if m.certainty == "known"}
        (beside if found else stated).update(named)
    used = frozenset(compact(p.tracking_number) for p in parcels if p.tracking_number)
    source, status = (stated, "known") if stated else (beside, "guessed")
    default = CarrierDefault(next(iter(source)), status) if len(source) == 1 else None
    bank_lines = frozenset(entry.line for entry in entries if BANK.search(entry.text))
    context = Context(parcels, used, default, bank_lines, now)
    return flag_duplicates([row_for(draft, context) for draft in drafts])


def parse_invoices(text: str, open_orders: Sequence[Parcel], now: datetime) -> list[InvoiceRow]:
    """Read tracking numbers from what the owner typed, pasted, or dictated and match each one."""
    return rows_for(sentences(table_entries(text_rows(text))), open_orders, now)


def import_invoices(
    data: bytes, filename: str, open_orders: Sequence[Parcel], now: datetime,
) -> list[InvoiceRow]:
    """Read a carrier program's CSV or XLSX export and match each row the same way as pasted text."""
    return rows_for(table_entries(read_table(data, filename)), open_orders, now)


def file_text(data: bytes, filename: str) -> str:
    """Spell out an export as text, so a number can be checked against what the owner uploaded."""
    return "\n".join("\t".join(" ".join(cell.split()) for cell in row) for row in read_table(data, filename))
