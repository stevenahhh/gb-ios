"""The assistant's settings: one stored row, its change history, and the kill switch.

Only the owner changes these values, through the settings screen. Mode off stops every agent step:
the worker and each run read the mode again before they act. A tool the owner may not hand over
(sending, paying, refunding, deleting) is not a tool at all, so no switch can turn it on.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from types import MappingProxyType
from typing import Final, Literal

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_tables import AgentSettingChangeRow, AgentSettingsRow
from agent_types import DEFAULT_DAILY_CAP, Mode, Tier, ToolName
from display import local

SETTINGS_ID: Final = 1
MAX_DAILY_CAP: Final = 50
MIN_INTERVAL: Final = 5
MAX_INTERVAL: Final = 240
DEFAULT_INTERVAL: Final = 15
QUIET_START: Final = time(22)
QUIET_END: Final = time(8)
type SettingField = Literal["mode", "proactive", "per_tool", "daily_cap", "quiet_hours", "interval_minutes"]
PER_TOOL: Final[TypeAdapter[dict[str, Mode]]] = TypeAdapter(dict[str, Mode])
FIELDS: Final[TypeAdapter[SettingField]] = TypeAdapter(SettingField)
MODES: Final[TypeAdapter[Mode]] = TypeAdapter(Mode)

# Reads stay on: the assistant answers from them. Every other listed tool has a switch.
TOOL_TIERS: Final[Mapping[ToolName, Tier]] = MappingProxyType({
    "find_bookings": "T0", "find_orders": "T0", "find_shipments": "T0", "find_inquiries": "T0",
    "find_sessions": "T0", "read_calendar": "T0", "read_fact_cards": "T0", "read_rules": "T0",
    "find_quotes": "T0", "recall": "T0",
    "save_reply_draft": "T1", "add_event": "T1", "move_event": "T1", "complete_task": "T1",
    "reopen_task": "T1", "save_content_draft": "T1", "remember": "T1", "forget": "T1",
    "confirm_order": "T2", "mark_packed": "T2", "register_invoice": "T2", "mark_delivered": "T2",
    "confirm_deposit": "T2", "create_booking": "T2", "decide_cancellation": "T2",
    "record_quote_outcome": "T2",
})


@dataclass(frozen=True, slots=True)
class QuietHours:
    """A daily window in Seoul time; a start later than its end runs past midnight."""

    start: time
    end: time

    def contains(self, moment: datetime) -> bool:
        """Tell whether a moment falls inside the window: the start counts, the end does not."""
        clock = local(moment).time()
        if self.start < self.end:
            return self.start <= clock < self.end
        return clock >= self.start or clock < self.end


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """What every agent decision reads before it acts."""

    mode: Mode
    proactive: bool
    per_tool: Mapping[str, Mode]
    daily_cap: int
    quiet: QuietHours | None
    interval_minutes: int
    revision: int
    updated_at: datetime | None

    @property
    def interval(self) -> timedelta:
        """Time between two proactive ticks."""
        return timedelta(minutes=self.interval_minutes)

    def tool_mode(self, tool: ToolName) -> Mode:
        """Return the owner's switch for a tool; a general off always wins."""
        return "off" if self.mode == "off" else self.per_tool.get(tool, self.mode)

    def is_quiet(self, moment: datetime) -> bool:
        """Tell whether the owner asked not to be bothered at a moment."""
        return self.quiet is not None and self.quiet.contains(moment)


DEFAULT_SETTINGS: Final = AgentSettings(
    mode="off", proactive=True, per_tool=MappingProxyType({}), daily_cap=DEFAULT_DAILY_CAP,
    quiet=QuietHours(start=QUIET_START, end=QUIET_END), interval_minutes=DEFAULT_INTERVAL,
    revision=0, updated_at=None,
)


@dataclass(frozen=True, slots=True)
class SettingChange:
    """One entry of the change history."""

    field: SettingField
    previous: JsonValue
    value: JsonValue
    revision: int
    changed_at: datetime


def settings_of(row: AgentSettingsRow) -> AgentSettings:
    """Read one stored row into the value every caller uses."""
    quiet = None
    if row.quiet_start is not None and row.quiet_end is not None:
        quiet = QuietHours(start=row.quiet_start, end=row.quiet_end)
    return AgentSettings(
        mode=MODES.validate_python(row.mode), proactive=row.proactive,
        per_tool=MappingProxyType(PER_TOOL.validate_python(row.per_tool)), daily_cap=row.daily_cap,
        quiet=quiet, interval_minutes=row.interval_minutes, revision=row.revision,
        updated_at=row.updated_at,
    )


async def load_settings(db: AsyncSession) -> AgentSettings | None:
    """Read the settings row; without it the proactive worker does nothing."""
    row = await db.scalar(
        select(AgentSettingsRow).where(AgentSettingsRow.id == SETTINGS_ID)
        .execution_options(populate_existing=True),
    )
    return None if row is None else settings_of(row)


async def stop_requested(db: AsyncSession) -> bool:
    """Read the kill switch fresh before every agent step; a missing row stops everything too."""
    mode = await db.scalar(select(AgentSettingsRow.mode).where(AgentSettingsRow.id == SETTINGS_ID))
    return mode is None or mode == "off"


async def setting_changes(db: AsyncSession, limit: int) -> list[SettingChange]:
    """List the newest changes first."""
    rows = await db.scalars(
        select(AgentSettingChangeRow)
        .order_by(AgentSettingChangeRow.changed_at.desc(), AgentSettingChangeRow.id.desc()).limit(limit),
    )
    return [
        SettingChange(
            field=FIELDS.validate_python(row.field), previous=row.previous, value=row.value,
            revision=row.revision, changed_at=row.changed_at,
        )
        for row in rows
    ]
