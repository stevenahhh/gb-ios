"""Build a tool from its argument model, how it finds its target, its evidence rule, and what it does."""

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from typing import ClassVar, Final

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_mask import without_contacts
from agent_text import compact, without_particle
from agent_types import (
    BY_FULL_NAME,
    BY_PART_OF_NAME,
    Check,
    Claim,
    EvidenceRule,
    Outcome,
    Plan,
    Resolution,
    TargetKind,
    TargetRef,
    Tier,
    Tool,
    ToolEnv,
    ToolName,
    ToolRule,
    UndoStep,
    UndoTicket,
)
from display import SEOUL, masked
from models import Entity, ShipmentRow

MIN_PARTIAL: Final = 2
PARCEL: Final = "parcel"
WORD: Final = re.compile(r"[0-9A-Za-z가-힣]+")
OBJECT: Final = TypeAdapter(dict[str, JsonValue])
KNOWN_REFUSALS: Final[Mapping[str, str]] = {
    "action is not valid for the current state": "지금 상태에서는 할 수 없어요.",
    "class does not have enough seats": "남은 자리가 모자라요.",
    "resource not found": "맞는 건을 찾지 못했어요.",
    "quote not found": "견적을 찾지 못했어요.",
    "inquiry not found": "문의를 찾지 못했어요.",
    "the rules leave this to the owner": "규정으로 정하기 어려운 취소예요. 앱에서 직접 결정해 주세요.",
    "refund must be between zero and the paid amount": "환불 금액은 0원부터 받은 예약금까지 적어 주세요.",
    "an exception needs a reason": "예외로 처리하는 이유를 알려 주세요.",
    "final_total_krw is required": "최종 금액을 알려 주세요.",
    "verify the institution first": "기관 확인을 먼저 해 주세요.",
    "completed reply cannot be blank": "완료한 답장은 비워 둘 수 없어요.",
}
REFUSALS: Final[Mapping[int, str]] = {
    404: "맞는 건을 찾지 못했어요.",
    409: "지금 상태에서는 할 수 없어요.",
    422: "값을 다시 확인해 주세요.",
}


class ToolArgsError(ValueError):
    """The model's arguments do not fit the tool."""


class RevisionConflictError(Exception):
    """The row changed after the call was planned."""


class TargetGoneError(Exception):
    """The row the call pointed at no longer exists."""


class ToolRefusedError(Exception):
    """The service refused the call; the reason is Korean and safe to show."""

    def __init__(self, reason: str) -> None:
        """Keep the reason the owner sees."""
        super().__init__(reason)
        self.reason: str = reason


class ToolArgs(BaseModel):
    """Arguments the model sends; unknown fields are ignored and nothing is trusted as evidence."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore", str_strip_whitespace=True)


@dataclass(frozen=True, slots=True)
class Located:
    """What a call found before anything changes."""

    resolution: Resolution
    claims: tuple[Claim, ...] = ()
    checks: tuple[Check, ...] = ()
    preview: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Definition[A: ToolArgs]:
    """One tool, written once; `build` erases the argument type for the registry."""

    name: ToolName
    tier: Tier
    evidence: EvidenceRule
    title: str
    description: str
    args: type[A]
    locate: Callable[[AsyncSession, A, ToolEnv], Awaitable[Located]]
    run: Callable[[AsyncSession, A, TargetRef, ToolEnv], Awaitable[Outcome]]
    undo: UndoStep | None = None
    calls_model: bool = False


def inlined(node: JsonValue, definitions: Mapping[str, JsonValue]) -> JsonValue:
    """Put referenced definitions in place, so the model reads one flat schema."""
    if isinstance(node, list):
        return [inlined(part, definitions) for part in node]
    if not isinstance(node, dict):
        return node
    reference = node.get("$ref")
    if isinstance(reference, str):
        merged = {
            **_definition(definitions, reference),
            **{key: part for key, part in node.items() if key != "$ref"},
        }
        return inlined(merged, definitions)
    return {key: inlined(part, definitions) for key, part in node.items() if key not in {"title", "$defs"}}


def _definition(definitions: Mapping[str, JsonValue], reference: str) -> dict[str, JsonValue]:
    """Look up one referenced definition."""
    found = definitions.get(reference.removeprefix("#/$defs/"))
    return dict(found) if isinstance(found, dict) else {}


def schema_of(model: type[BaseModel]) -> dict[str, JsonValue]:
    """Describe the arguments as the plain JSON schema the model is shown."""
    raw = OBJECT.validate_python(model.model_json_schema())
    definitions = raw.get("$defs")
    flat = inlined(raw, definitions if isinstance(definitions, dict) else {})
    described = OBJECT.validate_python(flat)
    return {
        "type": "object",
        "properties": described.get("properties", {}),
        "required": described.get("required", []),
    }


def build[A: ToolArgs](definition: Definition[A]) -> Tool:
    """Turn a typed definition into the erased tool the registry holds."""

    async def plan(db: AsyncSession, raw: Mapping[str, JsonValue], env: ToolEnv) -> Plan:
        try:
            args = definition.args.model_validate(dict(raw))
        except ValidationError as error:
            message = f"{definition.name}: {error.error_count()} invalid argument(s)"
            raise ToolArgsError(message) from None
        located = (
            Located(Resolution((env.pinned,)))
            if env.pinned is not None
            else await definition.locate(db, args, env)
        )

        async def execute(session: AsyncSession, target: TargetRef) -> Outcome:
            return await definition.run(session, args, target, env)

        dumped: dict[str, JsonValue] = OBJECT.validate_python(args.model_dump(mode="json"))
        return Plan(
            args=dumped,
            resolution=located.resolution,
            claims=located.claims,
            checks=located.checks,
            preview=located.preview,
            execute=execute,
        )

    return Tool(
        rule=ToolRule(definition.name, definition.tier, definition.evidence),
        title=definition.title,
        description=definition.description,
        parameters=schema_of(definition.args),
        plan=plan,
        undo=definition.undo,
        calls_model=definition.calls_model,
    )


async def lock_row[T: Entity](
    db: AsyncSession,
    model: type[T],
    row_id: str,
    expected: int | None,
) -> T:
    """Lock a row and check it did not change since the call was planned."""
    row = await db.scalar(
        select(model).where(model.id == row_id).with_for_update().execution_options(populate_existing=True),
    )
    if row is None:
        raise TargetGoneError
    if expected is not None and row.revision != expected:
        raise RevisionConflictError
    return row


def parcel_made(shipment: ShipmentRow) -> str:
    """Tell a parcel from a later one of the same order, which reuses its id and restarts its revision."""
    return shipment.created_at.astimezone(UTC).isoformat()


def parcel_ticket(shipment: ShipmentRow) -> UndoTicket:
    """Let a step on this parcel be undone, and on no parcel made after it."""
    return UndoTicket(f"/shipments/{shipment.id}/undo", {PARCEL: parcel_made(shipment)})


def refusal_text(error: HTTPException) -> str:
    """Say a service's refusal in Korean, without its internals."""
    return KNOWN_REFUSALS.get(str(error.detail), REFUSALS.get(error.status_code, "처리하지 못했어요."))


def name_confidence(reference: str, *names: str | None) -> float | None:
    """Score how well a reference names one of these values; nothing when it does not.

    The reference is tried as written before a trailing particle is dropped, because many names end in
    a syllable that looks like one.
    """
    wanted = [
        found for found in dict.fromkeys((compact(reference), compact(without_particle(reference)))) if found
    ]
    scores: list[float] = []
    for name in names:
        if not name:
            continue
        whole = compact(name)
        if any(found in {whole, compact(masked(name))} for found in wanted):
            scores.append(BY_FULL_NAME)
        elif any(len(found) >= MIN_PARTIAL and found in whole for found in wanted):
            scores.append(BY_PART_OF_NAME)
    return max(scores, default=None)


def order_number_of(reference: str) -> int | None:
    """Read an order number such as #1040 or 1040번 from a reference."""
    digits = without_particle(reference).strip().lstrip("#").removesuffix("번").strip()
    return int(digits) if digits.isdigit() else None


def said(label: str, reference: str, *, is_number: bool = False) -> Claim:
    """Require the words that named the target to be in the owner's turn."""
    if is_number:
        return Claim(label, str(order_number_of(reference) or reference), "number")
    return Claim(label, reference, "text")


def target(kind: TargetKind, row: Entity, label: str) -> TargetRef:
    """Name a row as a target at the revision it was read."""
    return TargetRef(kind, row.id, label, row.revision)


def replace_revision(ref: TargetRef, revision: int) -> TargetRef:
    """Record the revision a write left behind."""
    return replace(ref, revision=revision)


def moment_at(day: datetime, clock: time) -> datetime:
    """Place a Seoul wall-clock time on a date."""
    return datetime.combine(day.date(), clock, SEOUL)


def local_date(value: str) -> datetime | None:
    """Read YYYY-MM-DD as a Seoul midnight, or nothing."""
    try:
        return datetime.combine(datetime.fromisoformat(value).date(), time.min, SEOUL)
    except ValueError:
        return None


def local_clock(value: str) -> time | None:
    """Read HH:MM, or nothing."""
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def named_in(label: str, reference: str) -> Claim:
    """Require a word of the reference in the owner's own statement; the kind's own name tells nothing."""
    words = [without_particle(match.group()) for match in WORD.finditer(reference)]
    kept = [word for word in dict.fromkeys(words) if len(word) >= MIN_PARTIAL and word != compact(label)]
    return Claim(label, "|".join(kept) or reference, "words")


def clipped(text: str, limit: int = 60) -> str:
    """Keep a label readable on one line; a longer text hides contacts first and is cut at whitespace."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    hidden = without_contacts(flat)
    if len(hidden) <= limit:
        return hidden
    cut = hidden.rfind(" ", 0, limit)
    return f"{hidden[: cut if cut > 0 else limit - 1]}…"
