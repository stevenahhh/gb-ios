"""The owner's edits of the assistant's settings, and the settings screen's shape."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from typing import Annotated, Final, assert_never

from fastapi import HTTPException
from pydantic import Field, JsonValue, TypeAdapter, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_settings import (
    DEFAULT_SETTINGS,
    MAX_DAILY_CAP,
    MAX_INTERVAL,
    MIN_INTERVAL,
    QUIET_END,
    QUIET_START,
    SETTINGS_ID,
    TOOL_TIERS,
    AgentSettings,
    SettingField,
    settings_of,
)
from agent_tables import AgentSettingChangeRow, AgentSettingsRow
from agent_types import Mode, Tier, ToolName
from contracts import ApiModel, ApiRequest
from display import local

TOOLS: Final[TypeAdapter[ToolName]] = TypeAdapter(ToolName)


class QuietHoursBody(ApiRequest):
    """A daily quiet window in Seoul time."""

    start: Annotated[time, Field(strict=False)]
    end: Annotated[time, Field(strict=False)]

    @model_validator(mode="after")
    def distinct(self) -> "QuietHoursBody":
        """Refuse a window of no length."""
        if self.start == self.end:
            message = "quiet hours must not start and end at the same time"
            raise ValueError(message)
        return self


class SettingsUpdate(ApiRequest):
    """The fields the owner changed; a field left out keeps its value."""

    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    mode: Mode | None = None
    proactive: bool | None = None
    per_tool: dict[str, Mode] | None = None
    daily_cap: Annotated[int, Field(strict=True, ge=1, le=MAX_DAILY_CAP)] | None = None
    quiet_hours: QuietHoursBody | None = None
    interval_minutes: Annotated[int, Field(strict=True, ge=MIN_INTERVAL, le=MAX_INTERVAL)] | None = None


class ToolSwitch(ApiModel):
    """One tool the owner can switch, and the mode it follows now."""

    tool: ToolName
    tier: Tier
    mode: Mode


class QuietHoursView(ApiModel):
    """The quiet window as clock texts."""

    start: str
    end: str


class SettingsView(ApiModel):
    """The settings screen."""

    mode: Mode
    proactive: bool
    tools: list[ToolSwitch]
    daily_cap: int
    quiet_hours: QuietHoursView | None
    interval_minutes: int
    revision: int
    updated_at: str | None


def clock_text(moment: time) -> str:
    """Write a time of day the way the screen shows it."""
    return moment.strftime("%H:%M")


def settings_view(settings: AgentSettings) -> SettingsView:
    """Shape settings for the app: every switchable tool with the mode it follows."""
    quiet = settings.quiet
    return SettingsView(
        mode=settings.mode, proactive=settings.proactive,
        tools=[
            ToolSwitch(tool=tool, tier=tier, mode=settings.tool_mode(tool))
            for tool, tier in TOOL_TIERS.items() if tier != "T0"
        ],
        daily_cap=settings.daily_cap,
        quiet_hours=None if quiet is None else QuietHoursView(
            start=clock_text(quiet.start), end=clock_text(quiet.end),
        ),
        interval_minutes=settings.interval_minutes, revision=settings.revision,
        updated_at=None if settings.updated_at is None else local(settings.updated_at).isoformat(
            timespec="seconds",
        ),
    )


def switchable(name: str) -> ToolName:
    """Accept a tool that may have a switch; anything the assistant may never do is not a tool."""
    try:
        tool = TOOLS.validate_python(name)
    except ValidationError:
        raise HTTPException(
            422, "설정에 없는 일이에요. 손님에게 보내기, 결제, 환불, 기록 삭제는 비서에게 맡길 수 없어요.",
        ) from None
    tier = TOOL_TIERS[tool]
    match tier:
        case "T1" | "T2":
            return tool
        case "T0":
            raise HTTPException(422, "찾아보는 일은 따로 켜고 끌 수 없어요.")
        case _:
            assert_never(tier)


def checked_switches(switches: Mapping[str, Mode]) -> dict[str, JsonValue]:
    """Check every switch before any of them is stored."""
    return {switchable(name): mode for name, mode in switches.items()}


@dataclass(frozen=True, slots=True)
class Change:
    """One field that the owner's request really changes."""

    field: SettingField
    previous: JsonValue
    value: JsonValue


def quiet_json(start: time | None, end: time | None) -> JsonValue:
    """Keep a quiet window in the history as clock texts."""
    if start is None or end is None:
        return None
    return {"start": clock_text(start), "end": clock_text(end)}


def apply_update(row: AgentSettingsRow, body: SettingsUpdate) -> list[Change]:
    """Write the given fields onto the row and list those that changed."""
    changes: list[Change] = []
    if body.mode is not None and body.mode != row.mode:
        changes.append(Change("mode", row.mode, body.mode))
        row.mode = body.mode
    if body.proactive is not None and body.proactive != row.proactive:
        changes.append(Change("proactive", row.proactive, body.proactive))
        row.proactive = body.proactive
    if body.per_tool is not None:
        merged: dict[str, JsonValue] = {**row.per_tool, **checked_switches(body.per_tool)}
        if merged != row.per_tool:
            changes.append(Change("per_tool", dict(row.per_tool), merged))
            row.per_tool = merged
    if body.daily_cap is not None and body.daily_cap != row.daily_cap:
        changes.append(Change("daily_cap", row.daily_cap, body.daily_cap))
        row.daily_cap = body.daily_cap
    if "quiet_hours" in body.model_fields_set:
        start = body.quiet_hours.start if body.quiet_hours else None
        end = body.quiet_hours.end if body.quiet_hours else None
        if (start, end) != (row.quiet_start, row.quiet_end):
            previous = quiet_json(row.quiet_start, row.quiet_end)
            changes.append(Change("quiet_hours", previous, quiet_json(start, end)))
            row.quiet_start, row.quiet_end = start, end
    if body.interval_minutes is not None and body.interval_minutes != row.interval_minutes:
        changes.append(Change("interval_minutes", row.interval_minutes, body.interval_minutes))
        row.interval_minutes = body.interval_minutes
    return changes


async def update_settings(db: AsyncSession, body: SettingsUpdate, now: datetime) -> AgentSettings:
    """Change settings under the row lock, keeping what each changed field was before."""
    row = await db.scalar(
        select(AgentSettingsRow).where(AgentSettingsRow.id == SETTINGS_ID).with_for_update()
        .execution_options(populate_existing=True),
    )
    if row is None:
        row = AgentSettingsRow(
            id=SETTINGS_ID, mode=DEFAULT_SETTINGS.mode, proactive=DEFAULT_SETTINGS.proactive,
            per_tool={}, daily_cap=DEFAULT_SETTINGS.daily_cap, quiet_start=QUIET_START, quiet_end=QUIET_END,
            interval_minutes=DEFAULT_SETTINGS.interval_minutes, revision=0, updated_at=now,
        )
        db.add(row)
    if row.revision != body.expected_revision:
        raise HTTPException(409, "그사이에 설정이 바뀌었어요. 다시 불러온 뒤 저장해 주세요.")
    changes = apply_update(row, body)
    if changes:
        row.revision += 1
        row.updated_at = now
        db.add_all(
            AgentSettingChangeRow(
                field=change.field, previous=change.previous, value=change.value,
                revision=row.revision, changed_at=now,
            )
            for change in changes
        )
    await db.flush()
    return settings_of(row)
