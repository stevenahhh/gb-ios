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
from b_k14_extract import (
    contact_kind,
    from_rules,
    is_locked,
    mask,
    numbers,
    rule_signals,
    with_server_signals,
)
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


def test_the_inquiry_hours_change_the_outreach_side_only() -> None:
    scenario = replace(
        BUDGETED, seats=SeatHistory(sessions=2, booked=9),
        inputs=replace(BUDGETED.inputs, lesson_minutes=240, travel_minutes=None),
    )
    result = calculate(scenario)
    assert result.outreach_minutes == 240 + 60
    # 9 seats over 2 sessions x 21,000 won = 94,500 won per 180-minute one-day class.
    assert result.net_per_hour_oneday == 31_500
    assert result.baseline_krw == 94_500 * 300 // 180
    assert result.net_per_hour_outreach == 1_390_000 * 60 // 300
    assert result.outreach_basis == (
        "출장 수업 40명, 5시간 (수업 4시간, 준비와 정리 1시간, 왕복 이동 시간을 안 넣어서 0분)"
    )
    assert result.oneday_basis == "최근 원데이 2번 평균 예약 4.5명, 3시간 (수업 2시간, 준비와 정리 1시간)"


def test_prep_and_round_trip_travel_count_in_the_outreach_hours() -> None:
    result = calculate(BUDGETED)
    assert result.outreach_basis == "출장 수업 40명, 6시간 (수업 2시간, 준비와 정리 1시간, 오가는 시간 3시간)"
    assert result.oneday_basis == "원데이 예약 기록이 없어요. 그래서 1인당 남는 돈끼리 비교했어요"


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


@pytest.mark.parametrize("text", [
    "선입금 해주시면 계약 진행하겠습니다",
    "계약보증금을 먼저 보내 주셔야 합니다",
    "재료를 먼저 구매해 주시면 나중에 정산해 드립니다",
    "물품 대금을 대납 부탁드립니다",
    "선입금 없이는 진행이 어렵습니다",
    "걱정하지 않으셔도 됩니다. 이행보증금 50만 원 납부 바랍니다",
    "저희 계좌로 선입금 부탁드려요",
    "선결제 후 정산하겠습니다",
    "재료를 먼저 구매해 주실 수 있나요?",
    "사장님께 선 입금 부탁드립니다",
    "사장님께 먼저 결제 후 정산하겠습니다",
    "저희가 대납 바랍니다",
    "착수금을 먼저 보내 주세요",
    "계약금 100만 원 입금 부탁드립니다",
    "보증금 30만 원 부탁드립니다",
    "예치금을 납부하셔야 합니다",
    "물품 대금을 먼저 송금해 주시면 됩니다",
    "착수금 입금 확인 후 계약서를 보내 드립니다",
    "계약금은 저희가 지정한 계좌로 입금해 주셔야 합니다",
    "계약금은 저희가 안내한 계좌로 입금 후 진행됩니다",
    "등록비를 내셔야 강사로 등록됩니다",
    "증거금 20만 원이 필요합니다",
    "계약금 1,000,000원 입금 부탁드립니다",
    "보증금을 요청드립니다",
    "예치금 주시면 바로 진행합니다",
    "가입비 10만 원이 있어야 강사 등록이 됩니다",
    "학교에서 선결제하시면 됩니다",
    "대납 후 정산해 드리겠습니다",
    "사장님이 먼저 입금 완료하시면 됩니다",
    "공방에서 먼저 구매 후 청구해 주시면 처리하겠습니다",
    "저희 학교는 선입금 해주시면 진행합니다",
    "저희가 선입금 요청드립니다",
    "저희가 선입금 해주시면 진행하겠습니다",
])
def test_owner_paying_first_locks(text: str) -> None:
    assert "prepay_by_owner" in rule_signals(text)
    assert is_locked(rule_signals(text))


@pytest.mark.parametrize("text", [
    "와인을 대신 구매해 주시면 같이 결제하겠습니다", "심장충격기를 대신 사 주세요", "대리구매 부탁드립니다",
    "와인을 대신 사 주시면 같이 결제할게요", "물품을 대신 구매해 주시면", "대신 결제해 주시면 정산",
    "저희 대신 사 주세요", "학교에서 대신 사다 주시면 같이 결제할게요",
    "대신 사다 주시면 정산해 드릴게요", "대리구매 가능한가요?",
    "와인을 대신 주문하고 영수증 주시면 정산하겠습니다",
])
def test_buying_goods_for_the_institution_locks(text: str) -> None:
    assert "proxy_purchase" in rule_signals(text)
    assert is_locked(rule_signals(text))


@pytest.mark.parametrize("text", [
    "예약금은 저희가 먼저 입금하겠습니다",
    "강사료 외에 재료는 저희 학교에서 직접 구매합니다",
    "보증금 없음",
    "보증금은 따로 없습니다",
    "저희가 선입금 해드리니 확인 부탁드립니다",
    "강사료는 선입금 가능합니다",
    "학교에서 선결제하고 영수증 부탁드려요",
    "이행보증보험 증권 제출 부탁드립니다",
    "계약보증금은 보증보험 증권으로 제출해 주세요",
    "나라장터를 통해 정식 계약으로 진행합니다",
    "재료는 저희가 대신 구매해 드립니다",
    "공방 로고를 대신 사용해도 될까요",
    "재료는 저희가 대신 준비할게요",
    "인원이 많아 대신 다른 날로",
    "강사님 대신 다른 분이",
    "재료는 저희가 대신 사 드릴게요",
    "선입금은 어렵습니다",
    "착수금은 저희가 먼저 보내 드리겠습니다",
    "계약금 30%를 먼저 입금해 드립니다",
    "계약금은 저희 학교에서 먼저 입금 후 진행 부탁드립니다",
    "저희가 계약금을 먼저 송금하겠습니다",
    "계약금 입금할 계좌를 알려 주세요",
    "계약금 받으시면 영수증 보내 주세요",
    "계약금 입금 예정입니다",
    "착수금 입금 완료했습니다",
    "보증금 관련 문의 부탁드립니다",
    "계약보증금은 보증보험으로 납부해 주세요",
    "계약금이 필요하시면 말씀해 주세요",
    "대금은 행사 후 지급됩니다",
    "대금 청구서를 먼저 보내 주세요",
    "예약금 안내 부탁드립니다",
    "예약금 결제 링크 보내 주세요",
    "예약금 입금은 어떻게 하면 될까요?",
    "계약금 확인 부탁드립니다",
    "수업료를 선결제하고 싶습니다",
    "선입금할 계좌를 알려 주시면 입금하겠습니다",
    "견적서를 먼저 보내 주세요",
    "저희 시청에서 먼저 입금 후 진행 부탁드립니다",
])
def test_institution_paying_first_does_not_lock(text: str) -> None:
    assert not is_locked(rule_signals(text))


@pytest.mark.anyio
@pytest.mark.parametrize("text", [
    "공문 보내드릴게요. 담당 주무관 홍길동 010-9999-8888, 마진 챙겨 드립니다",
    "담당 주무관입니다. 010-9999-8888 차액은 돌려 드려요",
])
async def test_official_wording_with_a_mobile_and_a_margin_locks(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, text: str,
) -> None:
    for replies in ((), (json.dumps({**READING, "org_type": "unknown", "budget_krw": None}),)):
        _ = fake_model(monkeypatch, *replies)
        body = (await client.post("/outreach/extract", json={"text": text})).json()
        assert body["fields"]["orgType"] == "public"
        assert {"mobile_only_contact", "margin_offer"} <= set(body["signals"])
        assert body["locked"] is True


@pytest.mark.parametrize("text", [
    "커미션 10% 드릴게요", "수수료로 20만 원 챙겨 드립니다", "사례비는 따로 드리겠습니다",
    "소개비를 지급합니다", "리베이트 가능합니다", "잘 되면 사례하겠습니다", "차액은 돌려 드려요",
    "견적을 올려 주시면 수수료를 나눠 드려요",
    "마진 챙겨 드립니다", "수수료도 있습니다", "커미션 지급은 문제없습니다",
])
def test_kickback_offers_are_margin_offers(text: str) -> None:
    assert "margin_offer" in rule_signals(text)


@pytest.mark.parametrize("text", [
    "카드 수수료는 저희가 지급합니다", "플랫폼 수수료가 있나요?", "수수료 없이 진행합니다",
    "강사 사례비는 30만 원 지급해 드립니다", "특강 사례비를 드립니다", "우수 사례를 보내 드립니다",
    "수수료 관련해서 연락드립니다", "커미션은 받지 않습니다",
    "송금 수수료를 제외하고 드립니다", "강사료를 지급해 드립니다", "강사님 사례비는 30만 원 드립니다",
    "강연 사례비 지급 규정을 보내 드립니다", "페이백 행사는 없습니다",
])
def test_ordinary_fees_are_not_margin_offers(text: str) -> None:
    assert "margin_offer" not in rule_signals(text)


BUDGETS = [
    ("1인당 예산 3만 원, 40명", 1_200_000),
    ("인당 35,000원으로 20명입니다", 700_000),
    ("예산은 1인당 3만5천원이고 30명 정도예요", 1_050_000),
    ("한 명당 2만 원, 2개 반 각 24명", 960_000),
    ("1인 예산 3만원 10명", 300_000),
    ("3만 원/인, 40명", 1_200_000),
    ("30명이고 인당 2만 원씩입니다", 600_000),
    ("1인당 3만 원, 총액 120만 원, 40명", 1_200_000),
    ("1인당 예산 3만 원입니다", None),
    ("인당 3만 원, 30~40명", None),
    ("인당 3~5만 원, 40명", None),
    ("반별 24명, 1인당 2만 원", None),
    ("40명, 예산은 200만 원", 2_000_000),
    ("40인 기준 예산 200만 원", 2_000_000),
    ("1인 창업 교육 예산 200만 원, 40명", 2_000_000),
    ("1인 1작품, 예산 150만 원, 30명", 1_500_000),
    ("1인당 재료비 1만 원, 예산 200만 원, 40명", 2_000_000),
    ("1인당 재료비 1만 원, 40명", None),
    ("강사비 30만 원, 재료비 1인당 1만 원, 20명", None),
    ("재료비 포함 1인당 5만 원, 20명", 1_000_000),
    ("1인당 재료비 포함 5만 원, 20명", 1_000_000),
    ("1명당 3만 원, 20명", 600_000),
    ("인당 삼만 원, 20명", None),
    ("총예산 123만 5천 원, 40명", 1_235_000),
]


@pytest.mark.parametrize(("text", "expected"), BUDGETS)
def test_rules_never_store_a_per_person_budget_as_the_total(text: str, expected: int | None) -> None:
    assert from_rules(text, "unknown").budget_krw == expected


MODEL_BUDGETS = [
    ("1인당 예산 3만 원, 40명", 30_000, (1_200_000, "low")),
    ("1인당 예산 3만 원, 40명", 1_200_000, (1_200_000, "high")),
    ("1인당 예산 3만 원입니다", 30_000, (None, "low")),
    ("인당 3만 원, 30~40명", 900_000, (None, "low")),
    ("1인당 3만 원, 총액 120만 원, 40명", 30_000, (1_200_000, "low")),
    ("1인당 3만 원, 총액 120만 원, 40명", 1_200_000, (1_200_000, "high")),
    ("1인당 3만 원, 총액 100만 원, 40명", 1_000_000, (1_000_000, "low")),
    ("1인당 재료비 1만 원, 예산 200만 원, 40명", 2_000_000, (2_000_000, "high")),
    ("1인당 재료비 1만 원, 40명", 10_000, (None, "low")),
    ("1인당 예산 3만 원, 40명", None, (1_200_000, "low")),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("text", "answer", "expected"), MODEL_BUDGETS)
async def test_model_budget_is_checked_against_a_per_person_price(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, text: str, answer: int | None,
    expected: tuple[int | None, str],
) -> None:
    _ = fake_model(monkeypatch, json.dumps({**READING, "budget_krw": answer}))
    body = (await client.post("/outreach/extract", json={"text": text})).json()
    assert (body["fields"]["budgetKrw"], body["confidence"]["budgetKrw"]) == expected


HEADCOUNTS = [
    ("4학년 2개 반 각 24명", (48, 48)),
    ("반당 24명, 총 3개 반입니다", (72, 72)),
    ("두 팀 각각 10~12명", (20, 24)),
    ("15명씩 4개 조로 진행", (60, 60)),
    ("2회차 각 20명", (40, 40)),
    ("2개 반 각 24명, 총 48명", (48, 48)),
    ("40명 출강", (40, 40)),
    ("30~40명 정도", (30, 40)),
    ("하루 2회, 회당 15명", (30, 30)),
    ("1회차 20명, 2회차 20명", None),
    ("참여 인원 50명(교사 5명 포함)", None),
    ("반별 24명입니다", None),
    ("한 반에 24명 정도예요", None),
    ("4학년 2개 반, 5학년 3개 반 각 24명", None),
    ("4학년 3반 각 24명", None),
    ("성인 20명, 아이 10명", None),
    ("2개 반 24명", None),
]


@pytest.mark.parametrize(("text", "expected"), HEADCOUNTS)
def test_rules_multiply_groups_or_leave_the_headcount_empty(
    text: str, expected: tuple[int, int] | None,
) -> None:
    fields = from_rules(text, "unknown")
    assert (fields.headcount, fields.headcount_max) == (expected or (None, None))


MODEL_HEADCOUNTS = [
    ("4학년 2개 반 각 24명", 24, (48, "low")),
    ("4학년 2개 반 각 24명", 48, (48, "high")),
    ("반별 24명입니다", 24, (None, "low")),
    ("2개 반 24명", 24, (None, "low")),
    ("성인 20명, 아이 10명", 30, (30, "low")),
    ("40명 출강", 40, (40, "high")),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("text", "answer", "expected"), MODEL_HEADCOUNTS)
async def test_model_headcount_is_checked_against_the_groups(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, text: str, answer: int,
    expected: tuple[int | None, str],
) -> None:
    reading = {**READING, "headcount_min": answer, "headcount_max": answer, "budget_krw": None}
    _ = fake_model(monkeypatch, json.dumps(reading))
    body = (await client.post("/outreach/extract", json={"text": text})).json()
    assert (body["fields"]["headcount"], body["confidence"]["headcount"]) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("14:00-16:00", "14:00-16:00"),
    ("14시~16시", "14:00-16:00"),
    ("오후 2시부터 4시", "14:00-16:00"),
    ("오후 2~4시", "14:00-16:00"),
    ("오전 10시 30분부터 12시까지", "10:30-12:00"),
    ("오전 11시~오후 1시", "11:00-13:00"),
    ("오전 11시~1시", "11:00-13:00"),
    ("오후 1시 반에서 3시", "13:30-15:00"),
    ("9:00 ~ 11:30", "09:00-11:30"),
    ("2시~4시", None),
    ("3~4시간 수업", None),
    ("20~24명", None),
    ("25시~26시", None),
    ("10:00-9:00", None),
    ("11/29~30 14시", None),
])
def test_rules_read_a_written_time_range(text: str, expected: str | None) -> None:
    assert from_rules(text, "unknown").time_range == expected


@pytest.mark.anyio
async def test_rule_read_time_range_is_low_confidence(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = fake_model(monkeypatch)
    body = (await client.post("/outreach/extract", json={"text": "40명, 오후 2시부터 4시"})).json()
    assert body["fields"]["timeRange"] == "14:00-16:00"
    assert body["confidence"]["timeRange"] == "low"


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
    title = "시청 총무과 출장 수업 견적 다시 연락하기"
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

    await upgrade(empty_database, "0005_k06")
    before = await tables()
    await upgrade(empty_database, "k14_0005")
    assert await tables() - before == {"class_costs", "outreach_defaults", "outreach_quotes"}
    await downgrade(empty_database, "0005_k06")
    assert await tables() == before
