"""Settings of the assistant: storage, switches, the change history, and the kill switch."""

from datetime import UTC, datetime, time, timedelta
from typing import Final

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agent_settings import (
    AgentSettings,
    QuietHours,
    load_settings,
    setting_changes,
    stop_requested,
)
from agent_settings_edit import SettingsUpdate, settings_view, update_settings
from database import transaction
from display import SEOUL
from tests.agent_proactive_support import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
REFUSED_TOOLS: Final = ("refund", "send_message", "delete", "complete_reply", "find_orders", "없는_도구")


def update(**fields: object) -> SettingsUpdate:
    return SettingsUpdate.model_validate({"expectedRevision": 0, **fields})


async def current() -> AgentSettings:
    async with transaction() as db:
        settings = await load_settings(db)
    assert settings is not None
    return settings


async def test_a_fresh_schema_starts_off_with_proactive_ready_and_quiet_nights(
    migrated: AsyncEngine,
) -> None:
    settings = await current()

    assert (settings.mode, settings.proactive, settings.daily_cap) == ("off", True, 20)
    assert (settings.quiet, settings.interval_minutes) == (QuietHours(time(22), time(8)), 15)
    assert (dict(settings.per_tool), settings.revision) == ({}, 0)


async def test_a_missing_row_loads_as_nothing_and_stops_every_run(migrated: AsyncEngine) -> None:
    async with migrated.begin() as connection:
        _ = await connection.execute(text("DELETE FROM agent_settings"))

    async with transaction() as db:
        assert (await load_settings(db), await stop_requested(db)) == (None, True)


async def test_an_update_keeps_the_previous_value_of_every_changed_field(migrated: AsyncEngine) -> None:
    body = update(
        mode="ask", proactive=False, dailyCap=5, perTool={"confirm_order": "off"},
        quietHours={"start": "23:00", "end": "07:30"}, intervalMinutes=30,
    )

    async with transaction() as db:
        saved = await update_settings(db, body, NOW)
    async with transaction() as db:
        history = await setting_changes(db, 10)

    assert saved == AgentSettings(
        mode="ask", proactive=False, per_tool={"confirm_order": "off"}, daily_cap=5,
        quiet=QuietHours(time(23), time(7, 30)), interval_minutes=30, revision=1, updated_at=NOW,
    )
    assert {change.field: (change.previous, change.value) for change in history} == {
        "mode": ("off", "ask"), "proactive": (True, False), "daily_cap": (20, 5),
        "per_tool": ({}, {"confirm_order": "off"}), "interval_minutes": (15, 30),
        "quiet_hours": ({"start": "22:00", "end": "08:00"}, {"start": "23:00", "end": "07:30"}),
    }
    assert {change.revision for change in history} == {1}


async def test_an_update_without_changes_keeps_the_revision_and_the_history(migrated: AsyncEngine) -> None:
    async with transaction() as db:
        saved = await update_settings(db, update(mode="off", dailyCap=20, proactive=True), NOW)
    async with transaction() as db:
        history = await setting_changes(db, 10)

    assert (saved.revision, history) == (0, [])


async def test_clearing_quiet_hours_is_a_change_of_its_own(migrated: AsyncEngine) -> None:
    async with transaction() as db:
        saved = await update_settings(db, update(quietHours=None), NOW)
    async with transaction() as db:
        history = await setting_changes(db, 10)

    assert saved.quiet is None
    assert [(change.field, change.value) for change in history] == [("quiet_hours", None)]


async def test_a_stale_revision_is_refused_and_changes_nothing(migrated: AsyncEngine) -> None:
    async with transaction() as db:
        _ = await update_settings(db, update(mode="ask"), NOW)

    with pytest.raises(HTTPException) as refused:
        async with transaction() as db:
            _ = await update_settings(db, update(mode="off"), NOW)

    assert refused.value.status_code == 409
    assert (await current()).mode == "ask"


@pytest.mark.parametrize("tool", REFUSED_TOOLS)
async def test_no_switch_turns_on_an_unknown_tool_or_a_read(migrated: AsyncEngine, tool: str) -> None:
    with pytest.raises(HTTPException) as refused:
        async with transaction() as db:
            _ = await update_settings(db, update(perTool={tool: "auto", "confirm_order": "off"}), NOW)

    assert refused.value.status_code == 422
    assert (await current()).per_tool == {}


async def test_tool_switches_fall_back_to_the_general_mode_and_off_always_wins(migrated: AsyncEngine) -> None:
    async with transaction() as db:
        mixed = await update_settings(db, update(mode="ask", perTool={"confirm_order": "auto"}), NOW)
    async with transaction() as db:
        stopped = await update_settings(db, update(expectedRevision=1, mode="off"), NOW)

    assert (mixed.tool_mode("confirm_order"), mixed.tool_mode("mark_packed")) == ("auto", "ask")
    assert stopped.tool_mode("confirm_order") == "off"


async def test_a_run_sees_the_kill_switch_at_its_next_step(migrated: AsyncEngine) -> None:
    sessions = async_sessionmaker(migrated, expire_on_commit=False)
    async with transaction() as db:
        _ = await update_settings(db, update(mode="auto"), NOW)
    async with sessions() as run:
        before = await stop_requested(run)
        async with sessions() as owner, owner.begin():
            _ = await update_settings(owner, update(expectedRevision=1, mode="off"), NOW)
        after = await stop_requested(run)

    assert (before, after) == (False, True)


async def test_the_screen_lists_every_tool_the_owner_may_switch_and_no_read(migrated: AsyncEngine) -> None:
    async with transaction() as db:
        settings = await update_settings(db, update(mode="auto", perTool={"register_invoice": "ask"}), NOW)

    view = settings_view(settings)

    modes = {switch.tool: (switch.tier, switch.mode) for switch in view.tools}
    assert modes["register_invoice"] == ("T2", "ask")
    assert modes["save_reply_draft"] == ("T1", "auto")
    assert {"find_orders", "read_calendar", "recall"}.isdisjoint(modes)
    assert view.quiet_hours is not None
    assert (view.quiet_hours.start, view.quiet_hours.end) == ("22:00", "08:00")


async def test_settings_survive_the_parsing_of_a_row_that_never_came_from_the_screen(
    migrated: AsyncEngine,
) -> None:
    async with migrated.begin() as connection:
        _ = await connection.execute(text("UPDATE agent_settings SET quiet_start = NULL, quiet_end = NULL"))

    settings = await current()

    assert settings.quiet is None
    assert not settings.is_quiet(datetime(2026, 11, 22, 23, 0, tzinfo=SEOUL))


NIGHT: Final = QuietHours(time(22), time(8))
LUNCH: Final = QuietHours(time(12), time(13))


def at(moment: time) -> datetime:
    return datetime.combine(datetime(2026, 11, 22, tzinfo=SEOUL).date(), moment, SEOUL)


@pytest.mark.parametrize(
    ("window", "moment"),
    [
        (NIGHT, time(22)), (NIGHT, time(23, 59)), (NIGHT, time(7, 59, 59)),
        (LUNCH, time(12)), (LUNCH, time(12, 59, 59)),
    ],
)
def test_quiet_hours_cover_their_start_and_every_moment_before_their_end(
    window: QuietHours, moment: time,
) -> None:
    assert window.contains(at(moment))


@pytest.mark.parametrize(
    ("window", "moment"),
    [
        (NIGHT, time(21, 59, 59)), (NIGHT, time(8)), (NIGHT, time(12)),
        (LUNCH, time(11, 59, 59)), (LUNCH, time(13)), (LUNCH, time(0)),
    ],
)
def test_quiet_hours_stop_at_their_end_and_start_at_their_start(window: QuietHours, moment: time) -> None:
    assert not window.contains(at(moment))


def test_quiet_hours_are_judged_on_the_seoul_clock_for_a_moment_in_another_zone() -> None:
    ten_pm_in_seoul = datetime(2026, 11, 22, 13, 0, tzinfo=UTC)

    assert NIGHT.contains(ten_pm_in_seoul)
    assert not NIGHT.contains(ten_pm_in_seoul - timedelta(minutes=1))


@pytest.mark.parametrize(
    "fields",
    [
        {"dailyCap": 0}, {"dailyCap": 51}, {"intervalMinutes": 4}, {"intervalMinutes": 241},
        {"mode": "always"}, {"quietHours": {"start": "22:00", "end": "22:00"}}, {"unknown": True},
    ],
)
def test_the_screen_cannot_send_a_value_outside_the_contract(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _ = update(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"quietHours": {"start": "23:00", "end": "07:00"}}, {"quietHours": None}, {"dailyCap": 5},
        {"perTool": {"confirm_order": "auto"}}, {"proactive": False}, {"intervalMinutes": 30},
    ],
)
async def test_saving_anything_but_the_mode_on_an_empty_table_leaves_the_assistant_off(
    migrated: AsyncEngine, fields: dict[str, object],
) -> None:
    async with migrated.begin() as connection:
        _ = await connection.execute(text("DELETE FROM agent_settings"))

    async with transaction() as db:
        _ = await update_settings(db, update(**fields), NOW)

    async with transaction() as db:
        stopped, changes = await stop_requested(db), await setting_changes(db, 10)
    assert ((await current()).mode, stopped) == ("off", True)
    assert len(changes) == 1


async def test_only_an_explicit_mode_turns_the_assistant_on_from_an_empty_table(
    migrated: AsyncEngine,
) -> None:
    async with migrated.begin() as connection:
        _ = await connection.execute(text("DELETE FROM agent_settings"))

    async with transaction() as db:
        _ = await update_settings(db, update(mode="ask"), NOW)

    async with transaction() as db:
        stopped, changes = await stop_requested(db), await setting_changes(db, 10)
    assert ((await current()).mode, stopped) == ("ask", False)
    assert [(change.field, change.previous, change.value) for change in changes] == [("mode", "off", "ask")]
