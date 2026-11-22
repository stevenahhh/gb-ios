"""Typed red-team cases: redteam.json holds the data, and this file only parses it."""

from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from agent_types import Decision, HttpRunSource, Mode
from prompts import HistoryTurn

HERE: Final = Path(__file__).resolve().parent
REDTEAM: Final = HERE / "redteam.json"


class Strict(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class SetOp(Strict):
    op: Literal["set"]
    table: str
    id: str | int
    values: dict[str, JsonValue]


class InsertOp(Strict):
    op: Literal["insert"]
    table: str
    values: dict[str, JsonValue]


class BumpOp(Strict):
    op: Literal["bump"]
    table: str
    id: str


class SettingsOp(Strict):
    op: Literal["settings"]
    values: dict[str, JsonValue]


class AutoStepsOp(Strict):
    op: Literal["auto_steps"]
    count: int


type Op = Annotated[SetOp | InsertOp | BumpOp | SettingsOp | AutoStepsOp, Field(discriminator="op")]


class Timed(Strict):
    before_model_call: int
    op: Op


class ScriptCall(Strict):
    tool: str
    args: dict[str, JsonValue]


class ScriptItem(Strict):
    calls: list[ScriptCall] = []
    text: str = ""
    raw: str | None = None


class StepExpect(Strict):
    tool: str
    decision: list[Decision]


class RowExpect(Strict):
    table: str
    id: str | int
    column: str
    value: JsonValue


class Expect(Strict):
    never_auto: list[str] = []
    steps: list[StepExpect] | None = None
    rows: list[RowExpect] = []
    unchanged: list[str] = []
    no_calls: bool = False
    max_tool_calls: int | None = None


class Case(Strict):
    id: str
    cls: str
    title: str
    setting: str
    mode: Mode = "auto"
    source: HttpRunSource = "chat"
    fixtures: list[Op] = []
    timed: list[Timed] = []
    history: list[HistoryTurn] = []
    turn: str
    script: list[ScriptItem]
    never: str
    allowed: str
    hard: bool = False
    expect: Expect
    rules: list[str] = []


CASES: Final = TypeAdapter(list[Case])


def load_cases(path: Path = REDTEAM) -> list[Case]:
    return CASES.validate_json(path.read_bytes())
