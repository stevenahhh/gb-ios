"""Carrier export files: read once, shown as rows, and registered only with one owner approval.

The file holds names, phones, and addresses, so its bytes are never stored. The approval sends the same
bytes again and they must hash to what the proposal kept. Nothing in a file is evidence by itself: every
row is a proposal, and a row that needs the owner is never part of the group.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, ClassVar, Final

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_approvals import open_proposal, require_on, require_tool_on
from agent_invoice import file_text, import_invoices
from agent_invoice_files import MAX_BYTES, InvoiceFileError
from agent_invoice_store import (
    InvoiceChoice,
    InvoiceRequest,
    InvoiceResult,
    clean,
    load_parcels,
    register_invoices,
)
from agent_invoice_types import PROBLEM_TEXT, InvoiceRow, Problem
from agent_mask import Masker
from agent_perform import ProposalSeed, proposal_row
from agent_store import StepDraft, add_step, new_run, proposal_view, step_view
from agent_tables import AgentProposalRow, AgentStepRow
from agent_tools import TOOLS
from agent_tools_read import customer_names
from agent_types import ProposalView, StepView, TargetKind, TargetRef
from common import Now
from contracts import ApiModel
from database import transaction

router = APIRouter(prefix="/agent/invoices")
FILE_STEP: Final = "송장 파일로 한 번에 넣기"
PAYLOAD: Final = TypeAdapter(dict[str, JsonValue])
type FileName = Annotated[str, Query(min_length=1, max_length=200)]
type AcceptedLines = Annotated[
    str,
    Query(alias="acceptFormat", max_length=400, description="길이 경고를 확인한 행 번호, 쉼표로 구분"),
]


class InvoiceTarget(ApiModel):
    """The parcel a row points at."""

    kind: TargetKind
    id: str
    label: str
    revision: int | None


class ProblemView(ApiModel):
    """Why a row needs the owner, in Korean."""

    code: str
    text: str


class InvoiceRowView(ApiModel):
    """One row of the file, without names, phones, or addresses."""

    line: int
    number: str
    match: str
    target: InvoiceTarget | None
    candidates: list[InvoiceTarget]
    carrier: str | None
    carrier_status: str
    problems: list[ProblemView]
    confidence: float
    needs_owner: bool


class InvoiceImport(ApiModel):
    """The file as rows, and the one group proposal when some rows may be registered."""

    rows: list[InvoiceRowView]
    ready_count: int
    proposal_count: int
    proposal_id: str | None


class InvoiceOutcome(ApiModel):
    """What one approval of a file registered; each step can be undone on its own."""

    registered: int
    proposal: ProposalView
    steps: list[StepView]


class ShownRow(BaseModel):
    """One registrable row as the owner was shown it; the approval must find exactly the same."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    line: int
    shipment_id: str
    number: str
    carrier: str


class FileSeed(BaseModel):
    """What a file proposal keeps: the file's hash, its clean rows, and its rows with a length warning."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    digest: str
    clean: tuple[ShownRow, ...]
    warned: tuple[ShownRow, ...]


@dataclass(frozen=True, slots=True)
class FilePlan:
    """What a file can register: the rows as read, and the choices of each registrable line."""

    rows: Sequence[InvoiceRow]
    clean: tuple[tuple[int, InvoiceChoice], ...]
    warned: tuple[tuple[int, InvoiceChoice], ...]

    def seed(self, data: bytes) -> FileSeed:
        """Keep what the owner is shown, without any personal data."""
        return FileSeed(
            digest=hashlib.sha256(data).hexdigest(), clean=shown(self.clean), warned=shown(self.warned),
        )


async def read_file(request: Request) -> bytes:
    """Read the body and stop past the file limit."""
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > MAX_BYTES:
            raise HTTPException(413, "한 번에 2MB까지 불러와요. 파일을 쪼개서 다시 올려 주세요.")
    return bytes(received)


def target_of(found: TargetRef) -> InvoiceTarget:
    """Present a parcel reference."""
    return InvoiceTarget(kind=found.kind, id=found.id, label=found.label, revision=found.revision)


def row_view(row: InvoiceRow) -> InvoiceRowView:
    """Present one row."""
    single = row.candidates[0] if len(row.candidates) == 1 else None
    return InvoiceRowView(
        line=row.line,
        number=row.number,
        match=row.match,
        target=None if single is None else target_of(single),
        candidates=[target_of(found) for found in row.candidates],
        carrier=row.carrier,
        carrier_status=row.carrier_status,
        problems=[ProblemView(code=problem, text=PROBLEM_TEXT[problem]) for problem in row.problems],
        confidence=row.confidence,
        needs_owner=row.needs_owner,
    )


async def rows_of(db: AsyncSession, data: bytes, filename: str, now: datetime) -> list[InvoiceRow]:
    """Read the file against the parcels its own text names."""
    try:
        parcels = await load_parcels(db, file_text(data, filename))
        return import_invoices(data, filename, parcels, now)
    except InvoiceFileError as error:
        raise HTTPException(422, error.reason) from None


def shown(choices: Sequence[tuple[int, InvoiceChoice]]) -> tuple[ShownRow, ...]:
    """Name each choice by its line, parcel, number, and carrier."""
    return tuple(
        ShownRow(
            line=line, shipment_id=choice.shipment_id, number=choice.tracking_number, carrier=choice.carrier,
        )
        for line, choice in choices
    )


def plan_of(rows: Sequence[InvoiceRow]) -> FilePlan:
    """Read what one approval registers: the clean rows, and the warned rows it may confirm by line."""
    found = [(row.line, warned(row)) for row in rows]
    return FilePlan(
        rows, tuple(clean(rows)), tuple((line, choice) for line, choice in found if choice is not None),
    )


def warned(row: InvoiceRow) -> InvoiceChoice | None:
    """Read a row whose only problem is its number length, when one parcel and a carrier are known."""
    if row.problems != (Problem.WRONG_FORMAT,) or len(row.candidates) != 1:
        return None
    single, carrier = row.candidates[0], row.carrier
    if single.revision is None or carrier is None:
        return None
    return InvoiceChoice(single.id, single.revision, carrier, row.number, accept_format=True)


def confirmed_choices(plan: FilePlan, seed: FileSeed, lines: frozenset[int]) -> tuple[InvoiceChoice, ...]:
    """Choose what the owner approved; a row that is not what the owner was shown stops the approval."""
    accepted = [(line, choice) for line, choice in plan.warned if line in lines]
    expected = tuple(row for row in seed.warned if row.line in lines)
    if shown(plan.clean) != seed.clean or shown(accepted) != expected:
        raise HTTPException(409, "올리신 뒤 송장 내용이 바뀌었어요. 파일을 새로 불러와 주세요.")
    return tuple(choice for _, choice in (*plan.clean, *accepted))


def accepted_lines(text: str) -> frozenset[int]:
    """Read the row numbers the owner accepted despite a length warning."""
    found = [part.strip() for part in text.split(",") if part.strip()]
    if not all(part.isdecimal() for part in found):
        raise HTTPException(422, "보내 주신 줄 번호가 알아보기 어려워요.")
    return frozenset(int(part) for part in found)


def stored_file(proposal: AgentProposalRow) -> FileSeed:
    """Read what a file proposal kept, so an approval can be checked against it."""
    try:
        return FileSeed.model_validate(PAYLOAD.validate_python(proposal.args).get("args"))
    except ValidationError:
        raise HTTPException(409, "이건 파일로 만든 요청이 아니에요.") from None


@router.post("/import")
async def import_file(request: Request, filename: FileName, now: Now) -> InvoiceImport:
    """Read a carrier file as proposals only; the rows that may be registered become one group proposal."""
    data = await read_file(request)
    async with transaction() as db:
        await require_on(db)
        plan = plan_of(await rows_of(db, data, filename, now))
        proposal = None
        if plan.clean or plan.warned:
            proposal = await propose_file(db, filename, data, plan, now)
    return InvoiceImport(
        rows=[row_view(row) for row in plan.rows],
        ready_count=len(plan.clean),
        proposal_count=0 if proposal is None else 1,
        proposal_id=None if proposal is None else proposal.id,
    )


async def propose_file(
    db: AsyncSession,
    filename: str,
    data: bytes,
    plan: FilePlan,
    now: datetime,
) -> AgentProposalRow:
    """Keep the hash of the file and the rows one approval would register."""
    masker = Masker.of(await customer_names(db))
    confirmable = len(plan.warned)
    rest = len(plan.rows) - len(plan.clean) - confirmable
    run = new_run("chat", masker.text(f"{FILE_STEP}: {filename}"), "done", now)
    run.ended_at = now
    db.add(run)
    await db.flush()
    step = await add_step(
        db,
        run.id,
        StepDraft(
            "register_invoice",
            "T2",
            FILE_STEP,
            {"file": masker.text(filename), "rows": len(plan.rows), "ready": len(plan.clean)},
            "proposed",
            f"파일 속 송장 {len(plan.rows)}건 중 {len(plan.clean)}건은 바로 한꺼번에 넣어 드릴게요.",
        ),
        now,
    )
    row = proposal_row(
        step,
        ProposalSeed(
            TOOLS["register_invoice"],
            f"수락 한 번이면 송장 {len(plan.clean)}건이 한꺼번에 들어가요.",
            plan.seed(data).model_dump(mode="json"),
            None,
            (
                ("파일", filename),
                ("넣을 송장", f"{len(plan.clean)}건"),
                ("번호 길이 봐 주세요", f"{confirmable}건"),
                ("이번엔 빼 둘 송장", f"{rest}건"),
            ),
            (),
            title=FILE_STEP,
        ),
        now,
        masker,
    )
    db.add(row)
    await db.flush()
    return row


@router.post("/{proposal_id}/approve")
async def approve_file(
    proposal_id: str,
    request: Request,
    filename: FileName,
    now: Now,
    accept_format: AcceptedLines = "",
) -> InvoiceOutcome:
    """Register the rows the owner was shown, all together or none; the same file must be sent again."""
    data = await read_file(request)
    lines = accepted_lines(accept_format)
    async with transaction() as db:
        await require_on(db)
        await require_tool_on(db, "register_invoice")
        proposal = await open_proposal(db, proposal_id, now)
        seed = stored_file(proposal)
        if seed.digest != hashlib.sha256(data).hexdigest():
            raise HTTPException(409, "아까와 다른 파일이에요. 처음에 쓰신 그 파일로 올려 주세요.")
        rows = await rows_of(db, data, filename, now)
        choices = confirmed_choices(plan_of(rows), seed, lines)
        if not choices:
            raise HTTPException(409, "넣을 송장이 하나도 안 남았어요. 어느 줄을 보셨는지 알려 주세요.")
        results = await register_invoices(
            db,
            InvoiceRequest(
                file_text(data, filename),
                choices,
                all_or_nothing=True,
                decided_by="owner",
                source="file",
            ),
            now,
        )
        refused = [result for result in results if result.outcome == "refused"]
        if refused:
            reason = refused[0].reason or ""
            raise HTTPException(409, f"{len(refused)}건은 실패했어요. {reason}".strip())
        steps = await registered_steps(db, proposal, results, rows, now)
        text = f"송장 {len(results)}건, 주문에 넣어 뒀어요."
        group = await db.get_one(AgentStepRow, proposal.step_id, with_for_update=True)
        proposal.state, proposal.decided_at, proposal.result = "approved", now, text
        group.result = text
        await db.flush()
        view = proposal_view(proposal, group)
    return InvoiceOutcome(registered=len(results), proposal=view, steps=steps)


async def registered_steps(
    db: AsyncSession,
    proposal: AgentProposalRow,
    results: Sequence[InvoiceResult],
    rows: Sequence[InvoiceRow],
    now: datetime,
) -> list[StepView]:
    """Record one step per registered invoice in the import's run, each with its own undo."""
    labels = {found.id: found.label for row in rows for found in row.candidates}
    group = await db.get_one(AgentStepRow, proposal.step_id)
    tool = TOOLS["register_invoice"]
    views: list[StepView] = []
    for result in results:
        label = labels.get(result.shipment_id, "")
        row = await add_step(
            db,
            group.run_id,
            StepDraft(
                tool.rule.name,
                tool.rule.tier,
                tool.title,
                {"tracking_number": result.tracking_number},
                "proposed",
                "파일을 수락하셔서 송장을 넣었어요.",
                (),
                TargetRef("shipment", result.shipment_id, label, result.revision_before),
                result=f"송장 입력 끝: {label} · {result.tracking_number}",
                revision_after=result.revision_after,
                undo=result.undo,
            ),
            now,
        )
        views.append(step_view(row))
    return views
