"""Order and parcel tools (T2); each needs the owner's current words for what it writes."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Final, Literal

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from agent_invoice import compact as compact_digits
from agent_invoice import parse_invoices
from agent_invoice_store import REFUSALS, InvoiceChoice, InvoiceRequest, load_parcels, register_invoices
from agent_invoice_types import PROBLEM_TEXT, InvoiceRow, Problem
from agent_text import mentions
from agent_toolkit import (
    PARCEL,
    Definition,
    Located,
    RevisionConflictError,
    ToolArgs,
    ToolRefusedError,
    build,
    lock_row,
    name_confidence,
    order_number_of,
    parcel_made,
    parcel_ticket,
)
from agent_types import (
    BY_FULL_NAME,
    BY_IDENTIFIER,
    Check,
    Claim,
    Outcome,
    Resolution,
    TargetRef,
    Tool,
    ToolEnv,
    UndoInput,
    UndoTicket,
)
from display import masked
from models import CustomerRow, OrderRow, ShipmentRow
from orders import confirm, order_records
from shipments import deliver_parcel, pack_parcel, shipment_records
from undo import step_back, unconfirm

type Reference = Annotated[str, Field(min_length=1, max_length=200)]
CLAUSE_END: Final = r"(?= *(?:[.,!~\n]|$))"
PAST: Final = r"(?![나을던었대더])"
FINISHED: Final = rf"완료(?:(?:했|됐|되었|하였){PAST}|(?:예요|이에요|입니다|됨|함)?{CLAUSE_END})"
ASKED: Final = rf" *(?:(?:줘요?|주세요|주십시오){CLAUSE_END}|주고(?= ))"
CONFIRM_WORDS: Final = re.compile(
    (
        rf"(?<![재선])주문(?:은|을|도)? *(?:"
        rf"(?:확인|확정)(?:은|을|도)? *(?:처리 *)?(?:(?:했|됐|되었|하였){PAST}|해{ASKED}|{FINISHED})|"
        rf"접수(?:는|를|도)? *(?:처리 *)?(?:(?:했|하였){PAST}|해{ASKED})|"
        rf"받아{ASKED})"
    ),
)
PACK_WORDS: Final = "|".join(
    (
        "쌌",
        *(
            f"{noun}{particle}{done}"
            for noun in ("포장", "패킹")
            for particle in ("", "은", "을", "이", "도", "다", "은다", "을다", "방금", "모두")
            for done in ("했", "됐", "끝났", "끝냈", "마쳤", "완료", "해놨", "해뒀")
        ),
    ),
)
DELIVER_WORDS: Final = re.compile(
    (
        rf"(?:배송|배달|도착|수령) *(?:{FINISHED}|"
        rf"완료(?:로)? *(?:처리 *)?(?:(?:했|됐|되었|하였){PAST}|(?:해|바꿔){ASKED}))|"
        rf"(?:(?:도착|수령|배달)(?:했|하였)|(?:배송|배달)(?:됐|되었)){PAST}|"
        rf"(?:택배|상품|물건|소포|작품)(?:은|는|을|를|도)? *(?:잘 *)?받으셨{PAST}"
    ),
)
OTHER_MATTER: Final = re.compile(
    "취소|환불|반품|반송|교환|회수|문자|카톡|메시지|알림|센터|터미널|영업소|대리점",
)


@dataclass(frozen=True, slots=True)
class Match:
    """A row a reference names, how sure that is, and the words that named it."""

    target: TargetRef
    score: float
    claim: Claim
    number: int | None = None


def order_named(
    reference: str,
    order_number: int,
    customer: str,
    product: str,
) -> tuple[float, Claim] | None:
    """Score a reference against an order number, the customer, and the product."""
    if order_number_of(reference) == order_number:
        return BY_IDENTIFIER, Claim("주문 번호", str(order_number), "number")
    named = [
        (score, Claim(label, value if score >= BY_FULL_NAME else reference, "text"))
        for label, value in (("손님", customer), ("상품", product))
        if (score := name_confidence(reference, value)) is not None
    ]
    return max(named, key=lambda found: found[0], default=None)


def parcel_label(shipment: ShipmentRow, order: OrderRow, customer: CustomerRow) -> str:
    """Describe a parcel for the owner, with the name masked."""
    del shipment
    return f"#{order.order_number} {order.product_name} · {masked(customer.name)}"


def found_one(matches: Sequence[Match], note: str) -> Located:
    """Collect the matches as one resolution; the policy accepts exactly one."""
    return Located(
        Resolution(
            tuple(match.target for match in matches),
            max((match.score for match in matches), default=BY_IDENTIFIER),
            note,
        ),
    )


def claims_for(matches: Sequence[Match], *extra: Claim) -> tuple[Claim, ...]:
    """Require the naming words and the facts of the single match."""
    return (*((matches[0].claim,) if len(matches) == 1 else ()), *extra)


def number_checks(matches: Sequence[Match], env: ToolEnv) -> tuple[Check, ...]:
    """Require any order number the owner stated to be the one that matched."""
    if len(matches) != 1:
        return ()
    number = matches[0].number
    stated = {
        found.value
        for found in mentions(env.turn or "")
        if found.unit in {"", "other"} and len(str(found.value)) == len(str(number))
    }
    return (Check("주문 번호", passed=stated <= {number}),)


def step_claim(label: str, words: re.Pattern[str], env: ToolEnv) -> Claim:
    """Require the owner's own words for this very step; a turn without them leaves the claim missing."""
    return Claim(label, "|".join(found.group() for found in words.finditer(env.turn or "")), "words")


def step_checks(matches: Sequence[Match], env: ToolEnv) -> tuple[Check, ...]:
    """Add to the number check that the turn is not also about a return, a message, or a stop on the way."""
    other = OTHER_MATTER.search(env.turn or "")
    return (*number_checks(matches, env), Check("다른 일", passed=other is None))


async def parcel_matches(
    db: AsyncSession,
    reference: str,
    status: Literal["packing", "invoice_pending", "in_transit"],
) -> list[Match]:
    """Find the parcels in one state that a reference names."""
    records = (
        await db.execute(
            shipment_records().where(ShipmentRow.status == status).order_by(ShipmentRow.ship_by_at),
        )
    ).tuples()
    matches: list[Match] = []
    for shipment, order, customer in records:
        named = order_named(reference, order.order_number, customer.name, order.product_name)
        if named is not None:
            label = parcel_label(shipment, order, customer)
            target = TargetRef("shipment", shipment.id, label, shipment.revision)
            matches.append(Match(target, *named, order.order_number))
    return matches


class OrderArgs(ToolArgs):
    """One order, named by its number, customer, or product."""

    order: Reference = Field(description="주문 번호(예: 1040), 손님 이름, 상품 이름 중 하나")


class ConfirmArgs(OrderArgs):
    """An order to accept."""


async def locate_paid(db: AsyncSession, args: ConfirmArgs, env: ToolEnv) -> Located:
    """Find the paid order to accept."""
    records = (await db.execute(order_records().where(OrderRow.status == "paid"))).tuples()
    matches: list[Match] = []
    for order, customer, _, _ in records:
        named = order_named(args.order, order.order_number, customer.name, order.product_name)
        if named is not None:
            label = f"#{order.order_number} {order.product_name} · {masked(customer.name)}"
            target = TargetRef("order", order.id, label, order.revision)
            matches.append(Match(target, *named, order.order_number))
    preview = ()
    if len(matches) == 1:
        preview = (("할 일", "주문 확인"), ("주문", matches[0].target.label))
    located = found_one(matches, "결제 완료된 주문 중에서 찾지 못했어요.")
    return Located(
        located.resolution,
        claims_for(matches, step_claim("확인", CONFIRM_WORDS, env)),
        step_checks(matches, env),
        preview,
    )


async def confirm_one(db: AsyncSession, args: ConfirmArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Accept one paid order."""
    del args
    order = await lock_row(db, OrderRow, target.id, target.revision)
    confirm(db, order, env.now)
    await db.flush()
    return Outcome(
        f"#{order.order_number} 주문을 확인했어요. 포장 대기로 넘어갔어요.",
        TargetRef("order", order.id, target.label, order.revision),
        UndoTicket(f"/orders/{order.id}/undo-confirm"),
    )


async def undo_confirm_order(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Return an order to paid while nothing was packed."""
    revision = undo.target.revision
    await unconfirm(db, undo.target.id, 0 if revision is None else revision)
    await db.flush()
    return Outcome("주문 확인을 되돌렸어요.")


async def parcel_back(db: AsyncSession, undo: UndoInput) -> Outcome:
    """Move a parcel back one step, the way the app's own undo does."""
    shipment = await lock_row(db, ShipmentRow, undo.target.id, undo.target.revision)
    if undo.data.get(PARCEL) != parcel_made(shipment):
        raise RevisionConflictError
    await step_back(db, shipment)
    await db.flush()
    return Outcome("발송 상태를 한 단계 되돌렸어요.")


class PackArgs(OrderArgs):
    """A packing that finished."""


async def locate_packing(db: AsyncSession, args: PackArgs, env: ToolEnv) -> Located:
    """Find the parcel that was packed."""
    matches = await parcel_matches(db, args.order, "packing")
    preview = (("할 일", "포장 완료"), ("주문", matches[0].target.label)) if len(matches) == 1 else ()
    located = found_one(matches, "포장 중인 주문에서 찾지 못했어요.")
    return Located(
        located.resolution,
        claims_for(matches, Claim("포장", PACK_WORDS, "words")),
        number_checks(matches, env),
        preview,
    )


async def pack(db: AsyncSession, args: PackArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Record that the parcel is packed."""
    del args
    shipment = await lock_row(db, ShipmentRow, target.id, target.revision)
    pack_parcel(shipment, env.now)
    await db.flush()
    return Outcome(
        f"포장 완료로 바꿨어요: {target.label}",
        TargetRef("shipment", shipment.id, target.label, shipment.revision),
        parcel_ticket(shipment),
    )


class DeliveredArgs(OrderArgs):
    """A parcel that arrived."""


async def locate_in_transit(db: AsyncSession, args: DeliveredArgs, env: ToolEnv) -> Located:
    """Find the parcel on its way."""
    matches = await parcel_matches(db, args.order, "in_transit")
    preview = (("할 일", "배송 완료"), ("주문", matches[0].target.label)) if len(matches) == 1 else ()
    located = found_one(matches, "배송 중인 주문에서 찾지 못했어요.")
    return Located(
        located.resolution,
        claims_for(matches, step_claim("도착", DELIVER_WORDS, env)),
        step_checks(matches, env),
        preview,
    )


async def deliver(db: AsyncSession, args: DeliveredArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Record delivery and complete the order."""
    del args
    shipment = await lock_row(db, ShipmentRow, target.id, target.revision)
    await deliver_parcel(db, shipment, env.now)
    await db.flush()
    return Outcome(
        f"배송 완료로 바꿨어요: {target.label}",
        TargetRef("shipment", shipment.id, target.label, shipment.revision),
        parcel_ticket(shipment),
    )


class InvoiceArgs(ToolArgs):
    """A tracking number for one parcel."""

    tracking_number: Annotated[
        str,
        Field(min_length=4, max_length=40, description="사장님이 준 송장번호 그대로"),
    ]
    order: Annotated[str, Field(max_length=200, description="주문 번호나 손님 이름. 없으면 비움.")] = ""
    carrier: Annotated[str, Field(max_length=40, description="택배사 이름 (CJ대한통운, 한진택배 등)")] = ""


async def read_row(db: AsyncSession, args: InvoiceArgs, env: ToolEnv) -> InvoiceRow | None:
    """Find the number in the owner's own words: this turn, or the turn a proposal came from."""
    text = env.turn or env.owner_text or ""
    wanted = compact_digits(args.tracking_number)
    rows = parse_invoices(text, await load_parcels(db, text), env.now)
    return next((row for row in rows if compact_digits(row.number) == wanted), None)


async def locate_invoice(db: AsyncSession, args: InvoiceArgs, env: ToolEnv) -> Located:
    """Read the owner's turn for this number and find the parcel it belongs to."""
    row = await read_row(db, args, env)
    claim = Claim("송장번호", args.tracking_number, "tracking")
    if row is not None:
        order = (("주문", row.candidates[0].label),) if len(row.candidates) == 1 else ()
        warnings = (
            *(("확인", PROBLEM_TEXT[problem]) for problem in row.problems),
            *(("없는 주문번호", str(number)) for number in row.unknown_orders),
        )
        preview = (("송장번호", row.number), ("택배사", row.carrier or "알 수 없음"), *order, *warnings)
        return Located(row.resolution, (claim,), row.checks, preview)
    matches = await parcel_matches(db, args.order or "", "invoice_pending") if args.order else []
    preview = (
        (("송장번호", args.tracking_number), ("주문", matches[0].target.label)) if len(matches) == 1 else ()
    )
    located = found_one(matches, "송장을 등록할 주문을 찾지 못했어요. 주문 번호를 알려 주세요.")
    unread = Check("송장번호 형식", passed=False)
    return Located(located.resolution, (claim,), (unread,), preview)


async def register_one(db: AsyncSession, args: InvoiceArgs, target: TargetRef, env: ToolEnv) -> Outcome:
    """Register one number through the same lock and checks as the invoice import."""
    row = await read_row(db, args, env)
    approved = env.pinned is not None
    owner_text = env.turn or env.owner_text or ""
    choice = InvoiceChoice(
        target.id,
        0 if target.revision is None else target.revision,
        (row.carrier or "") if row else "",
        args.tracking_number,
        accept_format=approved and row is not None and Problem.WRONG_FORMAT in row.problems,
    )
    results = await register_invoices(
        db,
        InvoiceRequest(
            owner_text,
            (choice,),
            all_or_nothing=True,
            decided_by="owner" if approved else "auto",
            source="turn",
        ),
        env.now,
    )
    [result] = results
    if result.outcome == "refused":
        if result.reason == REFUSALS[409]:
            raise RevisionConflictError
        raise ToolRefusedError(result.reason or "송장을 등록하지 못했어요.")
    return Outcome(
        f"송장을 등록했어요: {target.label} · {args.tracking_number}",
        TargetRef("shipment", target.id, target.label, result.revision_after),
        result.undo,
    )


ORDERS: Final[tuple[Tool, ...]] = (
    build(
        Definition(
            "confirm_order",
            "T2",
            "propose",
            "주문 확인",
            "결제된 주문을 확인하고 포장 대기로 넘깁니다.",
            ConfirmArgs,
            locate_paid,
            confirm_one,
            undo_confirm_order,
        ),
    ),
    build(
        Definition(
            "mark_packed",
            "T2",
            "propose",
            "포장 완료",
            "포장을 마친 주문을 송장 대기로 넘깁니다.",
            PackArgs,
            locate_packing,
            pack,
            parcel_back,
        ),
    ),
    build(
        Definition(
            "register_invoice",
            "T2",
            "propose",
            "송장 등록",
            "사장님이 준 송장번호를 주문에 등록합니다. 번호를 만들거나 고치지 않습니다.",
            InvoiceArgs,
            locate_invoice,
            register_one,
            parcel_back,
        ),
    ),
    build(
        Definition(
            "mark_delivered",
            "T2",
            "propose",
            "배송 완료",
            "도착한 주문을 배송 완료로 바꿉니다.",
            DeliveredArgs,
            locate_in_transit,
            deliver,
            parcel_back,
        ),
    ),
)
