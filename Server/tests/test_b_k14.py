"""Outreach quote judge: deterministic arithmetic, extraction fallback, and the stored quote lifecycle."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import pytest
from fastapi import HTTPException
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from b_k14_calc import CostCard, Inputs, Rates, Scenario, SeatHistory, calculate, missing_costs
from b_k14_extract import contact_kind, is_locked, mask, numbers, with_server_signals
from providers import ChatMessage, Sampling
from tests.conftest import downgrade, upgrade

type Body = dict[str, JsonValue]
CLASS = "도자기 원데이 클래스"
COST: Body = {
    "materialPerPersonKrw": 14000, "onedayPriceKrw": 35000, "prepMinutes": 30, "cleanupMinutes": 30,
    "maxHeadcount": 6,
}
DEFAULTS: Body = {
    "instructorHourlyKrw": 100000, "assistantDailyKrw": 90000, "travelMode": "flat", "travelPerKmKrw": 0,
    "travelFlatKrw": 50000, "minimumFeeKrw": 300000,
}
CARD = CostCard(
    material_krw=14000, oneday_price_krw=35000, prep_minutes=30, cleanup_minutes=30, class_minutes=120,
)
RATES = Rates(
    instructor_hourly_krw=100000, assistant_daily_krw=90000, travel_mode="flat", travel_per_km_krw=500,
    travel_flat_krw=50000, minimum_fee_krw=300000,
)
BUDGETED = Scenario(
    inputs=Inputs(headcount=40, budget_krw=2_000_000, travel_minutes=90), card=CARD, rates=RATES,
    seats=SeatHistory(sessions=0, booked=0),
)
INQUIRY = "시청 총무과입니다. 40명 출강 가능한가요? 예산은 200만 원입니다. 010-1234-5678"
READING: Body = {
    "org_type": "public", "org_name": "시청 총무과", "headcount_min": 40, "headcount_max": 40,
    "budget_krw": 2000000, "budget_vat": "unknown", "date": None, "date_text": None, "time_range": None,
    "location_text": None, "class_hint": None, "contact_kind": "unknown", "signals": [], "low_confidence": [],
}


@dataclass(slots=True)
class FakeModel:
    """Answers with the given replies in order, or fails like the provider when none is left."""

    replies: Sequence[str]
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def __call__(self, messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        self.calls.append(list(messages))
        if len(self.calls) > len(self.replies):
            raise HTTPException(502, "upstream service failed")
        return self.replies[len(self.calls) - 1]


def fake_model(monkeypatch: pytest.MonkeyPatch, *replies: str) -> FakeModel:
    fake = FakeModel(replies)
    monkeypatch.setattr("b_k14_extract.chat", fake)
    return fake


def test_fixed_budget_is_judged_per_person_when_the_class_has_no_history() -> None:
    result = calculate(BUDGETED)
    assert {line.key: line.amount_krw for line in result.lines} == {
        "instructor": 1_390_000, "assistant": 0, "travel": 50_000, "material": 560_000,
    }
    assert result.total_krw == 2_000_000
    assert result.net_per_person_outreach == 34_750
    assert result.net_per_person_oneday == 21_000
    assert (result.verdict, result.suggestion) == ("better", "accept")
    assert result.outreach_minutes == 120 + 30 + 30 + 180


def test_real_bookings_set_the_bar_and_the_minimum_headcount_meets_it() -> None:
    scenario = replace(BUDGETED, seats=SeatHistory(sessions=2, booked=20), inputs=Inputs(
        headcount=10, per_person_krw=30_000, travel_minutes=90,
    ))
    result = calculate(scenario)
    # Ten booked seats x 21,000 won over a 180-minute class, stretched over 360 minutes.
    assert result.baseline_krw == 420_000
    assert (result.verdict, result.suggestion) == ("worse", "raise")
    assert result.break_even_headcount == 30
    met = calculate(replace(scenario, inputs=replace(scenario.inputs, headcount=30)))
    below = calculate(replace(scenario, inputs=replace(scenario.inputs, headcount=29)))
    assert (met.verdict, below.verdict) == ("better", "worse")


def test_price_below_material_has_no_minimum_headcount() -> None:
    cheap = Inputs(headcount=10, per_person_krw=12_000, travel_minutes=0)
    result = calculate(replace(BUDGETED, inputs=cheap))
    assert result.break_even_headcount is None
    assert result.suggestion == "decline"


def test_booked_classes_pushed_out_raise_the_bar() -> None:
    result = calculate(replace(BUDGETED, lost_to_conflicts_krw=2_500_000))
    assert result.verdict == "worse"
    assert result.baseline_krw == 2_500_000
    assert result.needed_total_krw == 50_000 + 560_000 + 2_500_000


def test_missing_costs_give_no_verdict_and_are_named() -> None:
    card = replace(CARD, material_krw=None, oneday_price_krw=None)
    result = calculate(replace(BUDGETED, card=card))
    assert result.verdict == "unknown"
    assert result.net_per_person_outreach is None
    assert missing_costs(card, RATES) == ["material_per_person_krw", "oneday_price_krw"]


def test_minimum_fee_lifts_only_a_quote_without_a_budget() -> None:
    small = replace(BUDGETED, inputs=Inputs(headcount=1, travel_minutes=0))
    result = calculate(small)
    assert (result.total_krw, result.minimum_applied) == (300_000, True)
    assert sum(line.amount_krw or 0 for line in result.lines) == result.total_krw


def test_travel_without_distance_is_flagged_not_guessed() -> None:
    result = calculate(replace(BUDGETED, rates=replace(RATES, travel_mode="per_km")))
    assert result.travel_unknown
    assert next(line for line in result.lines if line.key == "travel").amount_krw is None


def test_contacts_are_masked_before_the_model_sees_them() -> None:
    masked = mask("문의 010-1234-5678 / 02-123-4567 / a.b@school.go.kr, 예산 2,000,000원")
    assert "1234" not in masked
    assert "school.go.kr" not in masked
    assert "2,000,000원" in masked
    assert contact_kind("010-1234-5678") == "mobile"
    assert contact_kind("02-123-4567, 010-1234-5678") == "landline"
    assert numbers("40명, 200만 원") == {40, 2_000_000}


def test_lock_rules_follow_the_design_chapter() -> None:
    mobile_public = with_server_signals(["margin_offer"], "public", "mobile")
    assert mobile_public == ["mobile_only_contact", "margin_offer"]
    assert is_locked(mobile_public)
    assert not is_locked(["mobile_only_contact"])
    assert is_locked(["prepay_by_owner"])
    assert not is_locked(["same_day_pressure", "margin_offer"])
    assert with_server_signals(["mobile_only_contact"], "company", "mobile") == []


@pytest.mark.anyio
async def test_extract_reads_fields_and_keeps_the_contact_out(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_model(monkeypatch, json.dumps(READING))
    response = await client.post("/outreach/extract", json={"text": INQUIRY})
    body = response.json()
    assert response.status_code == 200
    assert body["error"] is None
    assert body["fields"]["headcount"] == 40
    assert body["fields"]["budgetKrw"] == 2_000_000
    assert body["fields"]["contactKind"] == "mobile"
    assert body["confidence"]["headcount"] == "high"
    assert body["signals"] == ["mobile_only_contact"]
    assert body["locked"] is False
    assert "010-1234-5678" not in fake.calls[0][1].content


@pytest.mark.anyio
async def test_extract_drops_to_low_when_a_number_is_not_in_the_text(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = fake_model(monkeypatch, json.dumps({**READING, "budget_krw": 3_000_000}))
    body = (await client.post("/outreach/extract", json={"text": INQUIRY})).json()
    assert body["confidence"]["budgetKrw"] == "low"
    assert body["confidence"]["headcount"] == "high"


@pytest.mark.anyio
@pytest.mark.parametrize("replies", [("not json", '{"org_type": "public"}'), ()])
async def test_broken_or_failed_model_falls_back_to_rules(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, replies: tuple[str, ...],
) -> None:
    fake = fake_model(monkeypatch, *replies)
    response = await client.post("/outreach/extract", json={"text": INQUIRY + " 대리 구매 부탁드려요"})
    body = response.json()
    assert response.status_code == 200
    assert len(fake.calls) == max(1, len(replies))
    assert body["error"] == "extract_failed"
    assert (body["fields"]["headcount"], body["fields"]["budgetKrw"]) == (40, 2_000_000)
    assert set(body["confidence"].values()) == {"low"}
    assert "proxy_purchase" in body["signals"]
    assert body["locked"] is True


async def prepare(client: AsyncClient) -> None:
    assert (await client.put(f"/settings/class-costs/{CLASS}", json=COST)).status_code == 200
    assert (await client.put("/settings/outreach-defaults", json=DEFAULTS)).status_code == 200


def quote_body(**changes: JsonValue) -> Body:
    fields: Body = {
        "orgType": "public", "orgName": "시청 총무과", "budgetKrw": 2_000_000, "contactKind": "landline",
    }
    return {"fields": fields, "classId": CLASS, "headcount": 40, "travelMinutes": 90, **changes}


@pytest.mark.anyio
@pytest.mark.postgres
async def test_cost_settings_list_classes_and_refuse_a_zero_price(
    client: AsyncClient, database: AsyncEngine,
) -> None:
    listed = (await client.get("/settings/class-costs")).json()
    assert CLASS in [item["classId"] for item in listed["classes"]]
    assert all(item["materialPerPersonKrw"] is None for item in listed["classes"])
    assert listed["defaults"] is None
    refused = await client.put(f"/settings/class-costs/{CLASS}", json={**COST, "onedayPriceKrw": 0})
    assert refused.status_code == 422
    assert "onedayPriceKrw" in refused.text
    assert (await client.put("/settings/class-costs/없는 수업", json=COST)).status_code == 404
    await prepare(client)
    saved = (await client.get("/settings/class-costs")).json()
    assert saved["defaults"]["travelFlatKrw"] == 50000


@pytest.mark.anyio
@pytest.mark.postgres
async def test_quote_without_costs_names_them_and_gives_no_verdict(
    client: AsyncClient, database: AsyncEngine,
) -> None:
    body = (await client.post("/outreach/quotes", json=quote_body())).json()
    assert body["calculation"]["verdict"] == "unknown"
    assert body["missingCosts"] == ["material_per_person_krw", "oneday_price_krw", "instructor_hourly_krw"]


@pytest.mark.anyio
@pytest.mark.postgres
async def test_quote_lists_the_classes_it_would_push_out(client: AsyncClient, database: AsyncEngine) -> None:
    await prepare(client)
    sessions = (await client.get("/calendar", params={"start": "2026-11-25", "end": "2026-11-25"})).json()
    assert sessions["days"]
    body = quote_body()
    body["fields"] = {"orgType": "school", "date": "2026-11-25", "budgetKrw": 500_000}
    quote = (await client.post("/outreach/quotes", json=body)).json()
    assert [item["title"] for item in quote["conflicts"]] == [CLASS]
    assert quote["conflicts"][0]["lostKrw"] == quote["conflicts"][0]["bookedCount"] * 21_000
    assert quote["changeDeadline"] == "2026-11-18"


@pytest.mark.anyio
@pytest.mark.postgres
async def test_recalculation_changes_only_what_was_sent(client: AsyncClient, database: AsyncEngine) -> None:
    await prepare(client)
    quote = (await client.post("/outreach/quotes", json=quote_body())).json()
    path = f"/outreach/quotes/{quote['id']}"
    changed = (await client.post(f"{path}/recalculate", json={"headcount": 20})).json()
    assert changed["inputs"]["headcount"] == 20
    assert changed["inputs"]["travelMinutes"] == 90
    assert (await client.get(path)).json()["calculation"] == changed["calculation"]


@pytest.mark.anyio
@pytest.mark.postgres
async def test_locked_quote_is_sent_only_after_the_institution_is_verified(
    client: AsyncClient, database: AsyncEngine,
) -> None:
    await prepare(client)
    quote = (await client.post("/outreach/quotes", json=quote_body(signals=["prepay_by_owner"]))).json()
    path = f"/outreach/quotes/{quote['id']}"
    assert quote["locked"] is True
    assert (await client.post(f"{path}/sent", json={})).status_code == 409
    first = (await client.post(f"{path}/verify-org")).json()
    assert first["locked"] is False
    assert (await client.post(f"{path}/verify-org")).json() == first
    assert (await client.post(f"{path}/sent", json={"elapsedSeconds": 120})).json()["status"] == "sent"


@pytest.mark.anyio
@pytest.mark.postgres
async def test_follow_up_reminder_reaches_today_and_an_outcome_closes_it(
    client: AsyncClient, database: AsyncEngine,
) -> None:
    await prepare(client)
    quote = (await client.post("/outreach/quotes", json=quote_body())).json()
    # 2026-11-18 is a Wednesday, so three business days later is Monday.
    assert quote["followUpAt"] == "2026-11-23T15:00:00+09:00"
    path = f"/outreach/quotes/{quote['id']}"
    at = {"followUpAt": "2026-11-18T10:00:00+09:00"}
    sent = (await client.post(f"{path}/sent", json=at)).json()
    assert sent["status"] == "follow_up"
    title = "시청 총무과 출강 견적 다시 연락"
    assert title in (await client.get("/today")).text
    assert (await client.post(f"{path}/outcome", json={"outcome": "accepted_adjusted"})).status_code == 422
    adjusted = {"outcome": "accepted_adjusted", "finalTotalKrw": 1_900_000}
    done = await client.post(f"{path}/outcome", json=adjusted)
    assert (done.json()["status"], done.json()["finalTotalKrw"]) == ("accepted_adjusted", 1_900_000)
    assert (await client.post(f"{path}/sent", json={})).status_code == 409
    listed = (await client.get("/outreach/quotes")).json()
    assert [row["status"] for row in listed] == ["accepted_adjusted"]
    assert listed[0]["followUpDue"] is None


@pytest.mark.anyio
@pytest.mark.postgres
async def test_stored_quote_holds_no_contact_details(client: AsyncClient, database: AsyncEngine) -> None:
    await prepare(client)
    body = quote_body()
    body["fields"] = {"orgName": "시청 010-1234-5678", "locationText": "별관 a@b.kr"}
    stored = (await client.post("/outreach/quotes", json=body)).json()
    assert (stored["fields"]["orgName"], stored["fields"]["locationText"]) == ("시청", "별관")


@pytest.mark.anyio
@pytest.mark.parametrize("route", ["/outreach/quotes", "/settings/class-costs"])
async def test_routes_require_the_api_key(client: AsyncClient, route: str) -> None:
    assert (await client.get(route, headers={"X-Roundup-Key": "wrong"})).status_code == 401


@pytest.mark.anyio
@pytest.mark.postgres
async def test_downgrade_removes_only_the_new_tables(empty_database: AsyncEngine) -> None:
    async def tables() -> set[str]:
        async with empty_database.connect() as connection:
            return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))

    await upgrade(empty_database, "0004")
    before = await tables()
    await upgrade(empty_database)
    assert await tables() - before == {"class_costs", "outreach_defaults", "outreach_quotes"}
    await downgrade(empty_database, "0004")
    assert await tables() == before
