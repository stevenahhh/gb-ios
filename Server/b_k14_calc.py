"""K14 outreach arithmetic: integer won from the owner's own cost card, never from a model."""

from dataclasses import dataclass
from typing import Final, Literal

from contracts import ApiModel
from display import won

HOUR: Final = 60
TIMES: Final = "\u00d7"
TIER_STEP: Final = 100
TIER_SIZES: Final = (10, 20, 30, 40)
type TravelMode = Literal["flat", "per_km"]
type Verdict = Literal["better", "worse", "unknown"]
type Suggestion = Literal["accept", "raise", "decline", "unknown"]


@dataclass(frozen=True, slots=True)
class CostCard:
    """One class's cost card; a missing value stays None instead of being guessed."""

    material_krw: int | None
    oneday_price_krw: int | None
    prep_minutes: int
    cleanup_minutes: int
    class_minutes: int


@dataclass(frozen=True, slots=True)
class Rates:
    """The workshop's outreach rates; None means the owner has not entered them."""

    instructor_hourly_krw: int | None
    assistant_daily_krw: int
    travel_mode: TravelMode
    travel_per_km_krw: int
    travel_flat_krw: int
    minimum_fee_krw: int


@dataclass(frozen=True, slots=True)
class Inputs:
    """What the owner confirmed for this inquiry."""

    headcount: int
    budget_krw: int | None = None
    per_person_krw: int | None = None
    assistants: int = 0
    travel_minutes: int | None = None
    distance_km: int | None = None
    lesson_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class SeatHistory:
    """Actually booked seats in past and upcoming sessions of the same class."""

    sessions: int
    booked: int


@dataclass(frozen=True, slots=True)
class Scenario:
    """Everything one judgement needs, already read from the database."""

    inputs: Inputs
    card: CostCard
    rates: Rates
    seats: SeatHistory
    lost_to_conflicts_krw: int = 0

    @property
    def lesson_minutes(self) -> int:
        """Length of the outreach lesson: the inquiry's own time range, else the registered class."""
        return self.inputs.lesson_minutes or self.card.class_minutes

    @property
    def setup_minutes(self) -> int:
        """Preparation and cleanup from the cost card, counted on both sides."""
        return self.card.prep_minutes + self.card.cleanup_minutes

    @property
    def travel_minutes(self) -> int:
        """Round-trip travel; an empty value counts as zero and is flagged on screen."""
        return 2 * (self.inputs.travel_minutes or 0)


class Line(ApiModel):
    """One of the four quote cells with the formula that produced it."""

    key: Literal["instructor", "assistant", "travel", "material"]
    label: str
    amount_krw: int | None
    formula: str


class TierPrice(ApiModel):
    """Per-person price when a given number of people come."""

    headcount: int
    per_person_krw: int


class Calculation(ApiModel):
    """The full judgement snapshot stored with the quote."""

    lines: list[Line]
    total_krw: int
    per_person_krw: int
    base_instructor_krw: int
    instructor_gap_krw: int
    minimum_applied: bool
    outreach_minutes: int
    travel_unknown: bool
    net_per_person_outreach: int | None
    net_per_person_oneday: int | None
    net_per_hour_outreach: int | None
    net_per_hour_oneday: int | None
    baseline_krw: int | None
    verdict: Verdict
    suggestion: Suggestion
    break_even_headcount: int | None
    max_headcount: int | None
    needed_total_krw: int | None
    tier_prices: list[TierPrice]
    outreach_basis: str
    oneday_basis: str


def ceil_div(numerator: int, denominator: int) -> int:
    """Divide and round up."""
    return -(-numerator // denominator)


@dataclass(frozen=True, slots=True)
class Parts:
    """Amounts that do not depend on the total."""

    instructor: int
    assistant: int
    travel: int | None
    material_per_person: int | None

    @property
    def fixed(self) -> int:
        """Costs paid once whatever the headcount."""
        return self.assistant + (self.travel or 0)

    def material(self, headcount: int) -> int:
        """Material cost for a headcount; an unknown card counts as zero here and is flagged elsewhere."""
        return (self.material_per_person or 0) * headcount


def travel_cost(rates: Rates, distance_km: int | None) -> tuple[int | None, str]:
    """Return the travel cost and its formula; a per-km rate without a distance is unknown."""
    if rates.travel_mode == "flat":
        return rates.travel_flat_krw, f"고정 출장비 {won(rates.travel_flat_krw)}"
    if distance_km is None:
        return None, "왕복 거리를 입력하면 계산해요"
    amount = rates.travel_per_km_krw * distance_km * 2
    return amount, f"{won(rates.travel_per_km_krw)} {TIMES} 편도 {distance_km}km {TIMES} 왕복 2"


def parts_for(scenario: Scenario) -> tuple[Parts, str]:
    """Work out the headcount-independent amounts and the travel formula."""
    inputs, card, rates = scenario.inputs, scenario.card, scenario.rates
    hourly = rates.instructor_hourly_krw or 0
    travel, travel_formula = travel_cost(rates, inputs.distance_km)
    parts = Parts(
        instructor=ceil_div(hourly * scenario.lesson_minutes, HOUR),
        assistant=rates.assistant_daily_krw * inputs.assistants,
        travel=travel,
        material_per_person=card.material_krw,
    )
    return parts, travel_formula


def fixed_revenue(inputs: Inputs) -> int | None:
    """Money the institution already fixed: an owner's per-person price first, else its budget."""
    if inputs.per_person_krw is not None:
        return inputs.per_person_krw * inputs.headcount
    return inputs.budget_krw


def quoted_total(headcount: int, parts: Parts, minimum_fee: int) -> int:
    """Return the owner's own cost-based total for a headcount."""
    total = parts.instructor + parts.fixed + parts.material(headcount)
    return max(total, minimum_fee)


def tier_prices(inputs: Inputs, parts: Parts, minimum_fee: int) -> list[TierPrice]:
    """Per-person price for common group sizes, rounded up to 100 won."""
    sizes = sorted({*TIER_SIZES, inputs.headcount})
    return [
        TierPrice(
            headcount=size,
            per_person_krw=ceil_div(quoted_total(size, parts, minimum_fee), size * TIER_STEP) * TIER_STEP,
        )
        for size in sizes
    ]


@dataclass(frozen=True, slots=True)
class Bar:
    """What the outreach has to beat."""

    baseline: int
    oneday_per_person: int
    per_hour: int | None
    uses_history: bool


def bar_for(scenario: Scenario, outreach_minutes: int) -> Bar:
    """Measure one-day earnings with actually booked seats, never with capacity."""
    card, seats = scenario.card, scenario.seats
    if card.oneday_price_krw is None or card.material_krw is None:
        return Bar(0, 0, None, uses_history=False)
    per_person = card.oneday_price_krw - card.material_krw
    session_minutes = card.class_minutes + scenario.setup_minutes
    if seats.sessions <= 0 or session_minutes <= 0:
        return Bar(scenario.lost_to_conflicts_krw, per_person, None,
                   uses_history=scenario.lost_to_conflicts_krw > 0)
    per_session = per_person * seats.booked // seats.sessions
    baseline = per_session * outreach_minutes // session_minutes
    return Bar(
        max(baseline, scenario.lost_to_conflicts_krw), per_person, per_session * HOUR // session_minutes,
        uses_history=True,
    )


def missing_costs(card: CostCard, rates: Rates) -> list[str]:
    """Name the empty cost fields that make a judgement impossible."""
    missing: list[str] = []
    if card.material_krw is None:
        missing.append("material_per_person_krw")
    if card.oneday_price_krw is None:
        missing.append("oneday_price_krw")
    if rates.instructor_hourly_krw is None:
        missing.append("instructor_hourly_krw")
    return missing


def break_even(parts: Parts, per_person: int, bar: Bar) -> int | None:
    """Smallest headcount, at this per-person price, that beats the one-day bar."""
    material = parts.material_per_person or 0
    if bar.uses_history:
        margin = per_person - material
        need = parts.fixed + bar.baseline
    else:
        margin = per_person - material - bar.oneday_per_person
        need = parts.fixed
    if margin <= 0:
        return None
    return max(1, ceil_div(need, margin))


def needed_total(inputs: Inputs, parts: Parts, bar: Bar) -> int:
    """Smallest total for this headcount that beats the one-day bar."""
    material = parts.material(inputs.headcount)
    if bar.uses_history:
        return parts.fixed + material + bar.baseline
    return parts.fixed + material + bar.oneday_per_person * inputs.headcount


def max_headcount(inputs: Inputs, parts: Parts, bar: Bar) -> int | None:
    """Largest headcount a fixed budget allows before the one-day bar wins."""
    if inputs.budget_krw is None:
        return None
    material = parts.material_per_person or 0
    per_head = material if bar.uses_history else material + bar.oneday_per_person
    spare = inputs.budget_krw - parts.fixed - (bar.baseline if bar.uses_history else 0)
    if per_head <= 0 or spare <= 0:
        return None
    return spare // per_head or None


@dataclass(frozen=True, slots=True)
class Judgement:
    """The comparison result; every field is None or unknown while a cost is missing."""

    net_per_person_outreach: int | None = None
    net_per_person_oneday: int | None = None
    net_per_hour_outreach: int | None = None
    net_per_hour_oneday: int | None = None
    baseline_krw: int | None = None
    verdict: Verdict = "unknown"
    suggestion: Suggestion = "unknown"
    break_even_headcount: int | None = None
    max_headcount: int | None = None
    needed_total_krw: int | None = None


def priced(scenario: Scenario, parts: Parts) -> tuple[int, int, bool]:
    """Return the instructor cell, the total, and whether the minimum fee lifted it."""
    inputs = scenario.inputs
    material = parts.material(inputs.headcount)
    revenue = fixed_revenue(inputs)
    if revenue is not None:
        instructor = max(0, revenue - parts.fixed - material)
        return instructor, instructor + parts.fixed + material, False
    raw = parts.instructor + parts.fixed + material
    total = max(raw, scenario.rates.minimum_fee_krw)
    return parts.instructor + total - raw, total, total > raw


def calculate(scenario: Scenario) -> Calculation:
    """Turn confirmed inputs into four cells, both net comparisons, and one verdict."""
    inputs, card, rates = scenario.inputs, scenario.card, scenario.rates
    parts, travel_formula = parts_for(scenario)
    instructor, total, minimum_applied = priced(scenario, parts)
    minutes = scenario.lesson_minutes + scenario.setup_minutes + scenario.travel_minutes
    verdict = (
        Judgement() if missing_costs(card, rates)
        else judged(scenario, parts, bar_for(scenario, minutes), Priced(total, minutes))
    )
    return Calculation(
        lines=quote_lines(scenario, parts, travel_formula, instructor, minimum_applied=minimum_applied),
        total_krw=total,
        per_person_krw=total // inputs.headcount,
        base_instructor_krw=parts.instructor,
        instructor_gap_krw=instructor - parts.instructor,
        minimum_applied=minimum_applied,
        outreach_minutes=minutes,
        travel_unknown=parts.travel is None or inputs.travel_minutes is None,
        net_per_person_outreach=verdict.net_per_person_outreach,
        net_per_person_oneday=verdict.net_per_person_oneday,
        net_per_hour_outreach=verdict.net_per_hour_outreach,
        net_per_hour_oneday=verdict.net_per_hour_oneday,
        baseline_krw=verdict.baseline_krw,
        verdict=verdict.verdict,
        suggestion=verdict.suggestion,
        break_even_headcount=verdict.break_even_headcount,
        max_headcount=verdict.max_headcount,
        needed_total_krw=verdict.needed_total_krw,
        tier_prices=(
            [] if card.material_krw is None else tier_prices(inputs, parts, rates.minimum_fee_krw)
        ),
        outreach_basis=outreach_basis(scenario, minutes),
        oneday_basis=oneday_basis(scenario),
    )


def span(minutes: int) -> str:
    """Say a length in hours and minutes."""
    hours, rest = divmod(minutes, HOUR)
    if hours and rest:
        return f"{hours}시간 {rest}분"
    return f"{hours}시간" if hours else f"{rest}분"


def outreach_basis(scenario: Scenario, minutes: int) -> str:
    """Say the people and hours behind the outreach numbers."""
    travel = (
        "왕복 이동은 입력 전이라 0분" if scenario.inputs.travel_minutes is None
        else f"왕복 이동 {span(scenario.travel_minutes)}"
    )
    return (
        f"출강 {scenario.inputs.headcount}명, {span(minutes)} "
        f"(수업 {span(scenario.lesson_minutes)}, 준비·정리 {span(scenario.setup_minutes)}, {travel})"
    )


def oneday_basis(scenario: Scenario) -> str:
    """Say the really booked people and hours behind the one-day numbers."""
    seats, card = scenario.seats, scenario.card
    if seats.sessions <= 0:
        if scenario.lost_to_conflicts_krw > 0:
            return "원데이는 비워야 하는 수업의 예약 금액과 비교"
        return "원데이는 예약 기록이 없어 1인 순수익끼리 비교"
    whole, tenth = divmod(seats.booked * 10 // seats.sessions, 10)
    people = f"{whole}.{tenth}" if tenth else f"{whole}"
    return (
        f"원데이 평균 {people}명, {span(card.class_minutes + scenario.setup_minutes)} "
        f"(수업 {span(card.class_minutes)}, 준비·정리 {span(scenario.setup_minutes)})"
    )


@dataclass(frozen=True, slots=True)
class Priced:
    """The total and the time the outreach takes."""

    total: int
    minutes: int


def judged(scenario: Scenario, parts: Parts, bar: Bar, priced_at: Priced) -> Judgement:
    """Compare the outreach against the one-day bar and suggest accept, raise, or decline."""
    inputs = scenario.inputs
    net = priced_at.total - parts.fixed - parts.material(inputs.headcount)
    net_per_person = net // inputs.headcount
    better = net >= bar.baseline if bar.uses_history else net_per_person >= bar.oneday_per_person
    minimum = break_even(parts, priced_at.total // inputs.headcount, bar)
    suggestion: Suggestion = "accept" if better else "decline"
    if not better and minimum is not None:
        suggestion = "raise"
    return Judgement(
        net_per_person_outreach=net_per_person,
        net_per_person_oneday=bar.oneday_per_person,
        net_per_hour_outreach=net * HOUR // priced_at.minutes if priced_at.minutes > 0 else None,
        net_per_hour_oneday=bar.per_hour,
        baseline_krw=bar.baseline if bar.uses_history else None,
        verdict="better" if better else "worse",
        suggestion=suggestion,
        break_even_headcount=minimum,
        max_headcount=max_headcount(inputs, parts, bar),
        needed_total_krw=needed_total(inputs, parts, bar),
    )


def quote_lines(
    scenario: Scenario, parts: Parts, travel_formula: str, instructor: int, *, minimum_applied: bool,
) -> list[Line]:
    """Describe the four cells so every number on screen shows where it came from."""
    inputs, card, rates = scenario.inputs, scenario.card, scenario.rates
    hourly = rates.instructor_hourly_krw
    if fixed_revenue(inputs) is not None:
        instructor_formula = "받을 금액에서 보조 강사비, 출장비, 재료비를 뺀 금액"
    elif minimum_applied:
        instructor_formula = f"출강 최소 금액 {won(rates.minimum_fee_krw)}에 맞춘 금액"
    elif hourly is None:
        instructor_formula = "시간당 강사비를 입력하면 계산해요"
    else:
        instructor_formula = f"시간당 {won(hourly)} {TIMES} 수업 {scenario.lesson_minutes}분"
    material = None if card.material_krw is None else card.material_krw * inputs.headcount
    material_formula = (
        "1인 재료비를 입력하면 계산해요" if card.material_krw is None
        else f"1인 {won(card.material_krw)} {TIMES} {inputs.headcount}명"
    )
    return [
        Line(key="instructor", label="강사비", amount_krw=instructor, formula=instructor_formula),
        Line(key="assistant", label="보조 강사비", amount_krw=parts.assistant,
             formula=f"보조 강사 {inputs.assistants}명 {TIMES} 일당 {won(rates.assistant_daily_krw)}"),
        Line(key="travel", label="출장비", amount_krw=parts.travel, formula=travel_formula),
        Line(key="material", label="재료비", amount_krw=material, formula=material_formula),
    ]
