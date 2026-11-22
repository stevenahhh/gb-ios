"""Load the parcels an invoice text may mean, and register numbers through the existing invoice path."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from fastapi import HTTPException
from sqlalchemy import ColumnElement, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from agent_invoice import compact, parse_invoices
from agent_invoice_text import MAX_ORDER_DIGITS, SPOKEN_ORDER, normalize, verbatim_numbers
from agent_invoice_types import PROBLEM_TEXT, InvoiceRow, Parcel, ParcelStatus, Problem
from agent_toolkit import parcel_ticket
from agent_types import UndoTicket
from b_k25_numbers import sino
from carriers import carrier_named, has_valid_format
from common import locked
from metrics import UNSHIPPED
from models import CustomerRow, OrderRow, ShipmentRow
from orders import MAX_BATCH
from shipments import hold_invoice_lock, send_parcel, shipment_records

type DecidedBy = Literal["auto", "owner"]
type Source = Literal["turn", "file"]
type Outcome = Literal["registered", "refused"]
STATUSES: Final[Mapping[str, ParcelStatus]] = {
    "packing": "packing", "invoice_pending": "invoice_pending", "in_transit": "in_transit",
    "delivered": "delivered",
}
MIN_STORED: Final = 4
MAX_STORED: Final = 40
STOPPED: Final = "함께 넣던 송장 하나가 걸려서 모두 멈췄어요."
REFUSALS: Final = {
    404: "그 주문이 없어요.",
    409: "그새 주문이 달라졌거나 지금은 송장을 넣을 때가 아니에요.",
    422: "적으신 내용에 틀린 데가 있어요. 한 번 더 봐 주세요.",
}


@dataclass(frozen=True, slots=True)
class InvoiceChoice:
    """One number for one parcel, with the revision the caller saw."""

    shipment_id: str
    expected_revision: int
    carrier: str
    tracking_number: str
    accept_format: bool = False


@dataclass(frozen=True, slots=True)
class InvoiceRequest:
    """Numbers to register, the words or file they were read from, and who decided."""

    owner_text: str
    choices: tuple[InvoiceChoice, ...]
    all_or_nothing: bool
    decided_by: DecidedBy
    source: Source


@dataclass(frozen=True, slots=True)
class InvoiceResult:
    """What happened to one parcel; a refusal carries a Korean reason."""

    shipment_id: str
    tracking_number: str
    outcome: Outcome
    reason: str | None = None
    revision_before: int | None = None
    revision_after: int | None = None
    undo: UndoTicket | None = None

    @property
    def undo_path(self) -> str | None:
        """Name the app's own undo of this parcel."""
        return None if self.undo is None else self.undo.path


async def load_parcels(db: AsyncSession, text: str) -> list[Parcel]:
    """Load every unshipped parcel, plus shipped ones whose order, tracking number, or recipient is named."""
    numbers = verbatim_numbers(text)
    orders = {int(number) for number in numbers if len(number) <= MAX_ORDER_DIGITS}
    orders |= {sino(match.group(1)) for match in SPOKEN_ORDER.finditer(normalize(text)[0])}
    records = await db.execute(shipment_records().where(or_(
        ShipmentRow.status.in_(UNSHIPPED), OrderRow.order_number.in_(orders), digits_of().in_(numbers),
        func.strpos(compact(text), func.replace(func.lower(CustomerRow.name), " ", "")) > 0,
    )).order_by(OrderRow.order_number))
    return [
        Parcel(
            shipment.id, order.id, order.order_number, STATUSES[shipment.status], shipment.revision,
            customer.name, customer.phone, shipment.tracking_number,
        )
        for shipment, order, customer in records.tuples()
    ]


def digits_of() -> ColumnElement[str]:
    """Compare stored tracking numbers without the separators someone typed."""
    return func.regexp_replace(ShipmentRow.tracking_number, "[^0-9]", "", "g")


def hard_block(choice: InvoiceChoice, row: InvoiceRow, counts: Counter[str]) -> str | None:
    """Explain what even the owner's approval cannot override."""
    if row.blocks:
        return PROBLEM_TEXT[row.blocks[0]]
    if choice.shipment_id not in {target.id for target in row.candidates}:
        return "알려 주신 주문이 아니에요."
    if counts[row.number] > 1 or counts[choice.shipment_id] > 1:
        return "목록에 같은 송장번호나 주문이 겹쳐요."
    if carrier_named(choice.carrier) is None:
        return "보낼 택배사부터 정해 주세요."
    return None if MIN_STORED <= len(row.number) <= MAX_STORED else REFUSALS[422]


def refusal(
    choice: InvoiceChoice, row: InvoiceRow | None, request: InvoiceRequest, counts: Counter[str],
) -> str | None:
    """Explain why a number must not be registered, before any row is locked."""
    if row is None:
        return "알려 주신 목록에는 이 송장번호가 없어요."
    if reason := hard_block(choice, row, counts):
        return reason
    if request.decided_by == "auto" and (
        request.source == "file" or row.needs_owner or choice.carrier != row.carrier
    ):
        return "이 송장은 사장님이 먼저 봐 주셔야 넣을 수 있어요."
    if not choice.accept_format and not has_valid_format(carrier_named(choice.carrier), row.number):
        return PROBLEM_TEXT[Problem.WRONG_FORMAT]
    return None


def clean(rows: Sequence[InvoiceRow]) -> list[tuple[int, InvoiceChoice]]:
    """Pair each row one approval may cover with its line: no problem, one parcel, a certain carrier."""
    return [
        (row.line, InvoiceChoice(row.parcel.id, row.parcel.revision, row.carrier, row.number))
        for row in rows
        if not row.needs_owner and row.parcel and row.parcel.revision is not None and row.carrier
    ]


def clean_choices(rows: Sequence[InvoiceRow]) -> tuple[InvoiceChoice, ...]:
    """Collect the choices one approval may cover."""
    return tuple(choice for _, choice in clean(rows))


def clean_lines(rows: Sequence[InvoiceRow]) -> list[int]:
    """List the lines of those choices in file order, ready to store as JSON and compare at approval."""
    return [line for line, _ in clean(rows)]


async def send(db: AsyncSession, choice: InvoiceChoice, now: datetime) -> InvoiceResult:
    """Register one number through the same lock, revision check, and transition the app uses."""
    digits = compact(choice.tracking_number)
    shipment = await locked(db, ShipmentRow, choice.shipment_id, choice.expected_revision)
    send_parcel(shipment, choice.carrier, digits, now)
    await db.flush()
    return InvoiceResult(
        choice.shipment_id, digits, "registered", None, choice.expected_revision, shipment.revision,
        parcel_ticket(shipment),
    )


def refused(choice: InvoiceChoice, reason: str) -> InvoiceResult:
    """Report a parcel that was left unchanged."""
    return InvoiceResult(choice.shipment_id, compact(choice.tracking_number), "refused", reason)


def reason_for(error: HTTPException) -> str:
    """Turn the invoice path's own refusal into Korean; anything unexpected keeps propagating."""
    if error.status_code not in REFUSALS:
        raise error
    return REFUSALS[error.status_code]


async def register_together(
    db: AsyncSession, choices: Sequence[InvoiceChoice], now: datetime,
) -> list[InvoiceResult]:
    """Register every parcel in one savepoint, or none."""
    sent: list[InvoiceResult] = []
    current = choices[0]
    try:
        async with db.begin_nested():
            for choice in choices:
                current = choice
                sent.append(await send(db, choice, now))
    except HTTPException as error:
        reason = reason_for(error)
        return [refused(choice, reason if choice is current else STOPPED) for choice in choices]
    return sent


async def register_each(
    db: AsyncSession, choices: Sequence[InvoiceChoice], now: datetime,
) -> list[InvoiceResult]:
    """Register every parcel in its own savepoint and report each one."""
    results: list[InvoiceResult] = []
    for choice in choices:
        try:
            async with db.begin_nested():
                results.append(await send(db, choice, now))
        except HTTPException as error:
            results.append(refused(choice, reason_for(error)))
    return results


async def register_invoices(
    db: AsyncSession, request: InvoiceRequest, now: datetime,
) -> list[InvoiceResult]:
    """Register numbers found verbatim in the owner's words, all together or row by row, in request order."""
    if not 1 <= len(request.choices) <= MAX_BATCH:
        raise HTTPException(422, REFUSALS[422])
    await hold_invoice_lock(db)
    counts = Counter(compact(choice.tracking_number) for choice in request.choices)
    counts.update(choice.shipment_id for choice in request.choices)
    parcels = await load_parcels(db, request.owner_text)
    rows = {row.number: row for row in parse_invoices(request.owner_text, parcels, now) if row.number}
    reasons = {
        choice: refusal(choice, rows.get(compact(choice.tracking_number)), request, counts)
        for choice in request.choices
    }
    ready = sorted((c for c, reason in reasons.items() if reason is None), key=lambda c: c.shipment_id)
    if request.all_or_nothing and len(ready) < len(reasons):
        return [refused(choice, reasons[choice] or STOPPED) for choice in request.choices]
    register = register_together if request.all_or_nothing else register_each
    done = {result.shipment_id: result for result in await register(db, ready, now)} if ready else {}
    return [
        refused(choice, reason) if (reason := reasons[choice]) else done[choice.shipment_id]
        for choice in request.choices
    ]
