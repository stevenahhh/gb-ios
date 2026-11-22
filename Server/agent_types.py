"""Shared names of the assistant agent; every lane builds on these.

The model only proposes a tool call. `agent_policy.decide` turns the call, the rows it resolved to,
and the owner's current turn into a decision, and nothing the model writes can change that decision.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Annotated, Final, Literal, Self

from pydantic import Field, JsonValue, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import ApiModel, ApiRequest
from prompts import HistoryTurn, Intent

type Tier = Literal["T0", "T1", "T2"]
type Mode = Literal["off", "ask", "auto"]
type Decision = Literal["auto", "proposed", "refused", "clarify"]
type RunSource = Literal["chat", "voice", "proactive"]
type HttpRunSource = Literal["chat", "voice"]
type RunStatus = Literal["queued", "running", "done", "fallback", "failed", "stopped"]
type ProposalState = Literal["open", "approved", "dismissed", "expired"]
type EvidenceKind = Literal["owner_turn", "adapter"]
type EvidenceRule = Literal["none", "propose", "refuse"]
type ClaimKind = Literal["text", "quote", "words", "number", "money", "tracking", "time", "date"]
type MemoryKind = Literal["fact", "preference", "rule_of_thumb"]
type TargetKind = Literal[
    "booking",
    "order",
    "shipment",
    "inquiry",
    "session",
    "event",
    "task",
    "content",
    "quote",
    "memory",
]
type ToolName = Literal[
    "find_bookings",
    "find_orders",
    "find_shipments",
    "find_inquiries",
    "find_sessions",
    "read_calendar",
    "read_fact_cards",
    "read_rules",
    "find_quotes",
    "recall",
    "save_reply_draft",
    "add_event",
    "move_event",
    "complete_task",
    "reopen_task",
    "save_content_draft",
    "remember",
    "forget",
    "confirm_order",
    "mark_packed",
    "register_invoice",
    "mark_delivered",
    "confirm_deposit",
    "create_booking",
    "decide_cancellation",
    "record_quote_outcome",
]

MAX_TOOL_CALLS: Final = 6
MODEL_SECONDS: Final = 45.0
MAX_OUTPUT_TOKENS: Final = 1024
DEFAULT_DAILY_CAP: Final = 20
PROPOSAL_LIFETIME: Final = timedelta(hours=24)
MAX_PROMPT_MEMORIES: Final = 20
CONFIDENCE_THRESHOLD: Final = 0.85
BY_IDENTIFIER: Final = 1.0
"""An order number, tracking number, or row id named the row."""
BY_FULL_NAME: Final = 0.9
"""The whole customer name, product, or title named exactly one row."""
BY_PART_OF_NAME: Final = 0.7
"""Only part of a name fits, so the call becomes a proposal."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One call the model asked for; the name may not exist and the arguments are unchecked."""

    id: str
    name: str
    arguments: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class Claim:
    """One value a call would write, the words that named its target, or (`words`) the fact it states."""

    label: str
    value: str
    kind: ClaimKind


@dataclass(frozen=True, slots=True)
class TargetRef:
    """A row a call acts on; `revision` is the one the server read, None when the call creates the row."""

    kind: TargetKind
    id: str
    label: str
    revision: int | None = None


@dataclass(frozen=True, slots=True)
class Resolution:
    """What a call's reference matched; only exactly one candidate lets a write continue."""

    candidates: tuple[TargetRef, ...]
    confidence: float = BY_IDENTIFIER
    note: str = ""


@dataclass(frozen=True, slots=True)
class Check:
    """A server-side fact about a call besides the owner's words, such as a valid carrier format."""

    label: str
    passed: bool


@dataclass(frozen=True, slots=True)
class AdapterFact:
    """A claim confirmed by a trusted, configured adapter; none is configured today."""

    source: str
    claim: Claim


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """The words (masked) or adapter result that supported a decision."""

    kind: EvidenceKind
    excerpt: str


@dataclass(frozen=True, slots=True)
class ToolRule:
    """What the policy needs to know about a tool."""

    name: ToolName
    tier: Tier
    evidence: EvidenceRule


@dataclass(frozen=True, slots=True)
class PolicySettings:
    """The owner's switches that a decision depends on."""

    mode: Mode
    per_tool: Mapping[str, Mode] = field(default_factory=dict[str, Mode])
    daily_cap: int = DEFAULT_DAILY_CAP


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Everything `decide` may rely on besides the call itself; nothing else is evidence."""

    turn: str | None
    today: date
    settings: PolicySettings
    resolution: Resolution
    auto_today: int = 0
    checks: tuple[Check, ...] = ()
    adapter: tuple[AdapterFact, ...] = ()
    source: RunSource = "chat"


@dataclass(frozen=True, slots=True)
class Verdict:
    """The policy's decision, its Korean reason, the evidence found, and the claims still missing."""

    decision: Decision
    reason: str
    evidence: tuple[EvidenceItem, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolEnv:
    """What a tool may read besides the database: the clock, the owner's turn, and a pinned target.

    `owner_text` is the original turn a proposal came from. `aliases` maps the masked names the model
    was shown to the real names the owner wrote.
    """

    now: datetime
    turn: str | None = None
    pinned: TargetRef | None = None
    owner_text: str | None = None
    aliases: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True, slots=True)
class UndoTicket:
    """How to reverse a finished call: the existing endpoint's path and what that reversal needs."""

    path: str
    data: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UndoInput:
    """A recorded step to reverse; `target.revision` is the revision the step left behind."""

    target: TargetRef
    data: Mapping[str, JsonValue]
    now: datetime


@dataclass(frozen=True, slots=True)
class Outcome:
    """What an executed call did, as a masked line for the model and the step record."""

    summary: str
    target: TargetRef | None = None
    undo: UndoTicket | None = None


type Execute = Callable[[AsyncSession, TargetRef], Awaitable[Outcome]]
type UndoStep = Callable[[AsyncSession, UndoInput], Awaitable[Outcome]]
type PlanStep = Callable[[AsyncSession, Mapping[str, JsonValue], ToolEnv], Awaitable["Plan"]]


@dataclass(frozen=True, slots=True)
class Plan:
    """A validated, resolved call: what the policy judges and, when allowed, what runs."""

    args: dict[str, JsonValue]
    resolution: Resolution
    claims: tuple[Claim, ...]
    checks: tuple[Check, ...]
    preview: tuple[tuple[str, str], ...]
    execute: Execute


@dataclass(frozen=True, slots=True)
class Tool:
    """One tool the agent may offer; `plan` validates, resolves, and binds `execute`.

    `calls_model` marks a tool whose work includes a model call, so its time counts toward the run's.
    `card_per` names the argument that, with the target, tells one open card from another.
    """

    rule: ToolRule
    title: str
    description: str
    parameters: dict[str, JsonValue]
    plan: PlanStep
    undo: UndoStep | None = None
    calls_model: bool = False
    card_per: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    """A proposal raised without a model call, such as one proactive finding."""

    tool: ToolName
    title: str
    reason: str
    target: TargetRef
    args: dict[str, JsonValue]
    preview: tuple[tuple[str, str], ...] = ()
    evidence_needed: tuple[str, ...] = ()
    dedupe_key: str | None = None


class RunRequest(ApiRequest):
    """The owner's message; workshop facts are always loaded by the server, never accepted here.

    `requestId` is the app's own id for one send: the same id always returns the same run.
    """

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    request_id: Annotated[str, Field(min_length=8, max_length=64)] | None = None
    history: Annotated[list[HistoryTurn], Field(default_factory=list, max_length=40)]
    source: HttpRunSource = "chat"
    background: bool = False

    @model_validator(mode="after")
    def without_nul(self) -> Self:
        """Refuse text PostgreSQL cannot store."""
        if any("\0" in text for text in (self.question, *(turn.text for turn in self.history))):
            message = "NUL is not text"
            raise ValueError(message)
        return self


class TargetView(ApiModel):
    """The row a step or proposal acts on; the label is masked."""

    kind: TargetKind
    id: str
    label: str


class EvidenceView(ApiModel):
    """One piece of evidence, with its masked excerpt."""

    kind: EvidenceKind
    excerpt: str


class StepView(ApiModel):
    """One recorded step of a run."""

    id: str
    tool: str
    title: str
    decision: Decision
    reason: str
    target: TargetView | None
    evidence: list[EvidenceView]
    undoable: bool
    undone: bool


class PreviewLine(ApiModel):
    """One label and value shown on a proposal."""

    label: str
    value: str


class ProposalView(ApiModel):
    """A call waiting for the owner; approving sends `expectedRevision` back unchanged.

    `stepId` is the step that raised it, and `step` is that step once the owner approved it.
    """

    id: str
    step_id: str
    title: str
    reason: str
    preview: list[PreviewLine]
    evidence_needed: list[str]
    expires_at: str
    expected_revision: int | None
    tool: str
    state: ProposalState
    target: TargetView | None
    step: StepView | None = None


class RunResponse(ApiModel):
    """The answer and everything this run did; a background run returns at once with status queued."""

    run_id: str
    status: RunStatus
    answer: str | None
    steps: list[StepView]
    proposals: list[ProposalView]
    intent: Intent | None
    mode: Mode


class RunView(ApiModel):
    """A stored run; `question` is masked and `answer` appears when the run finished."""

    id: str
    status: RunStatus
    source: RunSource
    question: str
    answer: str | None
    intent: Intent | None
    model_calls: int
    tokens: int
    error: str | None
    created_at: str
    started_at: str | None
    ended_at: str | None
    steps: list[StepView] = Field(default_factory=list)
    proposals: list[ProposalView] = Field(default_factory=list)


class ApproveRequest(ApiRequest):
    """Approve what the app showed; `expectedRevision` is the proposal's own value.

    An approval runs exactly the stored call. A missing value, such as a tracking number, is said in the
    owner's next turn, where the evidence policy decides.
    """

    expected_revision: Annotated[int, Field(ge=0)] | None = None


class MemoryView(ApiModel):
    """One of the owner's own notes."""

    id: str
    kind: MemoryKind
    text: str
    source_quote: str
    created_at: str
    last_used_at: str | None


class MemoryList(ApiModel):
    """The owner's notes, newest first."""

    items: list[MemoryView]


class RunList(ApiModel):
    """Recent runs, newest first."""

    items: list[RunView]


class ProposalList(ApiModel):
    """Open proposals, soonest to expire first."""

    items: list[ProposalView]


class UndoResult(ApiModel):
    """What undoing a step did."""

    step: StepView
    summary: str
