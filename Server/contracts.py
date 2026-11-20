"""JSON contracts shared by the read and action endpoints."""

from datetime import date
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

type Tone = Literal["attention", "done", "progress", "neutral"]
type EventKind = Literal["booking", "order", "delivery", "todo"]
type CardKind = Literal["booking", "order", "shipment", "channel", "content", "task", "recommendation"]
type DraftKind = Literal["content", "recommendation"]
type DraftStatus = Literal["pending", "approved", "rejected"]
type ActionCode = Literal[
    "confirmDeposit", "confirmOrder", "pack", "registerInvoice", "markDelivered",
    "reviewContent", "completeTask", "acknowledgeRecommendation",
]


class ApiModel(BaseModel):
    """Immutable response serialized with camelCase keys."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, alias_generator=to_camel, populate_by_name=True,
    )


class ApiRequest(BaseModel):
    """Strict request body; unknown fields are rejected."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True,
    )


class CardDue(ApiModel):
    """A deadline sent as a moment, so clients phrase 오늘/어제 and 기한 지남 when they draw it."""

    at: str
    prefix: str | None = None
    suffix: str = ""
    missed: str | None = None


class Metric(ApiModel):
    """A computed number and its server-formatted text."""

    key: str
    label: str
    value: int | None
    display: str
    detail: str | None = None
    due: CardDue | None = None


class Status(ApiModel):
    """A status badge; tone selects its symbol and color."""

    text: str
    tone: Tone


class CardAction(ApiModel):
    """The state change currently valid for a card."""

    code: ActionCode
    label: str


class CardUndo(ApiModel):
    """A separate undo path that keeps installed action enums compatible."""

    label: Literal["되돌리기"] = "되돌리기"
    path: str


class CardDraft(ApiModel):
    """The editable assistant draft targeted by a card."""

    kind: DraftKind
    id: str
    status: DraftStatus
    preview: str


class CardBooking(ApiModel):
    """Structured booking facts for the redesigned booking row."""

    day: date
    day_title: str
    time: str
    customer: str
    people: int


class CardField(ApiModel):
    """One labelled value on a detail screen."""

    label: str
    value: str


class CardProgress(ApiModel):
    """Fixed steps; ``current`` is the index of the first unfinished step."""

    steps: list[str]
    current: int


class Card(ApiModel):
    """One list row, fully derived from database rows."""

    id: str
    kind: CardKind
    title: str
    status: Status | None = None
    lines: list[str]
    deadline: str | None = None
    tag: str | None = None
    revision: int
    action: CardAction | None = None
    undo: CardUndo | None = None
    draft: CardDraft | None = None
    booking: CardBooking | None = None
    due: CardDue | None = None
    source: str | None = None
    fields: list[CardField] | None = None
    progress: CardProgress | None = None


class Page(ApiModel):
    """One page of a searchable work area."""

    metrics: list[Metric]
    items: list[Card]
    total: int
    limit: int
    offset: int
    has_more: bool


class Moved(ApiModel):
    """The revision after a reschedule, so the client can undo it."""

    revision: int
