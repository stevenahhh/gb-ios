"""Carrier formats match what the app stores, and no adapter ever makes up a number."""

from datetime import datetime
from pathlib import Path
from typing import Final

import pytest

from carriers import (
    CARRIERS,
    Carrier,
    FakeCarrier,
    Issued,
    ParcelOrder,
    Provenance,
    Tracked,
    Unavailable,
    UnconfiguredCarrier,
    adapter_for,
    carrier_named,
    has_valid_format,
)
from display import SEOUL

pytestmark = pytest.mark.anyio
NOW: Final = datetime(2026, 11, 18, 11, 0, tzinfo=SEOUL)
ORDER: Final = ParcelOrder(1040, "김가상", None, None, "머그컵", 1)
SHEETS: Final = Path(__file__).parents[2] / "GongbangAssistant/Shared/ActionSheets.swift"


async def test_registry_names_are_the_ones_the_app_offers() -> None:
    line = next(line for line in SHEETS.read_text().splitlines() if "static let carriers" in line)
    assert sorted(line.split('"')[1::2]) == sorted(carrier.name for carrier in CARRIERS)


@pytest.mark.parametrize(("name", "digits", "valid"), [
    ("CJ대한통운", "682100042841", True), ("CJ대한통운", "6821000428", True),
    ("CJ대한통운", "68210004284", False),
    ("우체국택배", "6865123456789", True), ("우체국택배", "686512345678", False),
    ("한진택배", "610311119284", True), ("롯데택배", "610311119284", True), ("롯데택배", "6103111192", False),
    ("로젠택배", "61031111928", True), ("로젠택배", "6103111192a", False),
    ("", "610311119", True), ("", "61031111", False), ("", "610311119284123", False),
])
async def test_formats_check_length_and_digits(name: str, digits: str, *, valid: bool) -> None:
    assert has_valid_format(carrier_named(name), digits) is valid


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda carrier: carrier.name)
async def test_an_unconfigured_carrier_explains_itself_and_returns_no_number(carrier: Carrier) -> None:
    adapter = adapter_for(carrier)
    assert isinstance(adapter, UnconfiguredCarrier)
    for result in (await adapter.issue(ORDER), await adapter.track("610311119284")):
        assert isinstance(result, Unavailable)
        assert carrier.name in result.reason


async def test_a_fake_result_is_never_evidence() -> None:
    label = Provenance("test_fake", "f", "r", NOW)
    record = Tracked("610311119284", delivered=True, events=(), provenance=label)
    fake = FakeCarrier(CARRIERS[0], ["610311119284"], [record], NOW)
    issued = await fake.issue(ORDER)
    assert isinstance(issued, Issued)
    assert not issued.provenance.is_evidence
    assert await fake.track("610311119284") == record
    assert isinstance(await fake.track("610311119285"), Unavailable)
    assert isinstance(await FakeCarrier(CARRIERS[0], [], [], NOW).issue(ORDER), Unavailable)
    assert Provenance("carrier_api", "a", "r", NOW).is_evidence
