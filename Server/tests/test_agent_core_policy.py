"""The policy decides alone: evidence is the owner's current turn, and nothing else can act."""

from datetime import date
from typing import Final

import pytest

from agent_policy import SPOKEN, decide, find_evidence
from agent_settings import TOOL_TIERS
from agent_toolkit import named_in
from agent_types import (
    BY_FULL_NAME,
    BY_IDENTIFIER,
    BY_PART_OF_NAME,
    AdapterFact,
    Check,
    Claim,
    Decision,
    PolicyContext,
    PolicySettings,
    Resolution,
    TargetRef,
    ToolName,
    ToolRule,
)

TODAY: Final = date(2026, 11, 18)
AUTO: Final = PolicySettings(mode="auto")
PARCEL: Final = TargetRef("shipment", "shipment-order-1040", "머그컵 2종 세트", 3)
ONE: Final = Resolution((PARCEL,), BY_IDENTIFIER)
PACK: Final = ToolRule("mark_packed", "T2", "propose")
ORDER_1040: Final = Claim("주문 번호", "1040", "number")
PACKED: Final = Claim("포장", "포장|패킹|쌌", "words")


def context(
    turn: str | None,
    *,
    resolution: Resolution = ONE,
    settings: PolicySettings = AUTO,
    **more: object,
) -> PolicyContext:
    return PolicyContext(turn=turn, today=TODAY, settings=settings, resolution=resolution, **more)  # type: ignore[arg-type]


def decision(
    tool: ToolRule,
    claims: tuple[Claim, ...],
    turn: str | None,
    **more: object,
) -> Decision:
    return decide(tool, claims, context(turn, **more)).decision


@pytest.mark.parametrize(
    "turn",
    [
        "1040 포장 끝났어",
        "천사십번 포장 끝났어요",
        "일공사공 포장했어",
        "#1040 포장 다 했어",
        "1040 포장 완료",
        "주문 1040번은 포장했어",
    ],
)
def test_a_stated_packing_of_one_order_runs(turn: str) -> None:
    verdict = decide(PACK, (ORDER_1040, PACKED), context(turn))
    assert verdict.decision == "auto"
    assert {item.kind for item in verdict.evidence} == {"owner_turn"}


@pytest.mark.parametrize(
    "turn",
    [
        "포장할 거 있어?",
        "1040 포장했어?",
        "1040 포장했나",
        "1040 언제 포장해?",
        "1040은 아직 포장 안 했어",
        "1040 말고 1041 포장했어",
        "포장은 했어",
        "1041 포장했어",
        "1040 배송했어",
    ],
)
def test_a_question_a_denial_or_another_order_is_not_evidence(turn: str) -> None:
    assert decision(PACK, (ORDER_1040, PACKED), turn) == "proposed"


def test_no_owner_turn_never_acts_on_parcels() -> None:
    assert decision(PACK, (ORDER_1040, PACKED), None) == "proposed"


def test_text_that_only_contains_the_number_inside_another_is_not_evidence() -> None:
    assert find_evidence(ORDER_1040, "11040 포장했어", TODAY) is None
    assert find_evidence(ORDER_1040, "주문 10405 포장했어", TODAY) is None


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (0, "clarify"),
        (1, "auto"),
        (2, "clarify"),
    ],
)
def test_only_one_matching_row_lets_a_write_continue(candidates: int, expected: Decision) -> None:
    resolution = Resolution(
        tuple(TargetRef("shipment", f"s{n}", "x") for n in range(candidates)),
        BY_IDENTIFIER,
    )
    assert decision(PACK, (ORDER_1040, PACKED), "1040 포장했어", resolution=resolution) == expected


@pytest.mark.parametrize(
    ("mode", "per_tool", "expected"),
    [
        ("off", {}, "refused"),
        ("ask", {}, "proposed"),
        ("auto", {}, "auto"),
        ("auto", {"mark_packed": "off"}, "refused"),
        ("auto", {"mark_packed": "ask"}, "proposed"),
        ("ask", {"mark_packed": "auto"}, "auto"),
        ("off", {"mark_packed": "auto"}, "refused"),
    ],
)
def test_the_owners_switches_win_over_evidence(
    mode: str,
    per_tool: dict[str, str],
    expected: Decision,
) -> None:
    settings = PolicySettings(mode=mode, per_tool=per_tool)  # type: ignore[arg-type]
    assert decision(PACK, (ORDER_1040, PACKED), "1040 포장했어", settings=settings) == expected


@pytest.mark.parametrize(("mode", "expected"), [("auto", "auto"), ("ask", "auto"), ("off", "refused")])
def test_reads_stay_on_unless_everything_is_off(mode: str, expected: Decision) -> None:
    read = ToolRule("find_orders", "T0", "none")
    assert decision(read, (), "주문 알려줘", settings=PolicySettings(mode=mode)) == expected  # type: ignore[arg-type]


def test_internal_work_answers_to_the_owners_turn() -> None:
    tool = ToolRule("complete_task", "T1", "none")
    target = Resolution((TargetRef("task", "task-1", "가마 온도 점검"),), BY_FULL_NAME)
    named = (named_in("할 일", "가마 온도 점검"),)
    assert decision(tool, named, "가마 온도 점검 끝냈어", resolution=target) == "auto"
    assert decision(tool, named, "점심 먹었어", resolution=target) == "proposed"
    assert decision(tool, (), "가마 온도 점검 끝냈어", resolution=target) == "proposed"
    assert decision(tool, named, "가마 온도 점검 끝냈어?", resolution=target) == "proposed"
    assert decision(tool, named, "가마 온도 점검 안 끝냈어", resolution=target) == "proposed"
    assert decision(tool, named, "가마 온도 점검 끝냈어. 오늘 주문 뭐 있어?", resolution=target) == "proposed"
    assert decision(tool, (), None, resolution=target) == "auto"
    assert decision(tool, named, None, resolution=Resolution(())) == "clarify"


def test_a_fuzzy_name_stops_an_action() -> None:
    tool = ToolRule("complete_task", "T1", "none")
    target = Resolution((TargetRef("task", "task-1", "가마 온도 점검"),), BY_PART_OF_NAME)
    assert decision(tool, (), "처리해줘", resolution=target) == "proposed"
    named = (named_in("할 일", "가마 온도 점검"),)
    assert decision(tool, named, "가마 온도 점검 끝냈어", resolution=target) == "proposed"


@pytest.mark.parametrize(
    "turn",
    [
        "최민우 님 예약금 안들어왔어",
        "예약금 못받았어",
        "1042 주문 확인 못했어",
        "1040 포장 덜 끝났어",
        "1038 배송 완료 안됐어",
        "1040 포장 방법 알려 줘",
        "1040 포장했어. 1041은 언제야?",
        "'1040 포장 끝났어' 라고 하셨어",
    ],
)
def test_denials_lookups_and_borrowed_words_are_not_evidence(turn: str) -> None:
    claims = (Claim("주문 번호", "1040", "number"), PACKED)
    verdict = decide(PACK, claims, context(turn))
    assert verdict.decision == "proposed"


def test_a_phone_number_is_not_an_order_number() -> None:
    claims = (ORDER_1040, PACKED)
    assert decision(PACK, claims, "1040 포장 끝났어, 010-1234-5678") == "auto"


@pytest.mark.parametrize("tool", [name for name, tier in TOOL_TIERS.items() if tier == "T2"])
def test_a_spoken_request_never_runs_a_t2_tool_by_itself(tool: ToolName) -> None:
    rule = ToolRule(tool, "T2", "propose")
    claims = (Claim("주문 번호", "1040", "number"), PACKED)
    spoken = decide(rule, claims, context("1040 포장 끝났어", source="voice"))
    assert (spoken.decision, spoken.reason) == ("proposed", SPOKEN)
    typed = decide(rule, claims, context("1040 포장 끝났어"))
    assert typed.decision == "auto"


def test_the_daily_cap_turns_actions_into_proposals() -> None:
    assert decision(PACK, (ORDER_1040, PACKED), "1040 포장했어", auto_today=20) == "proposed"
    assert decision(PACK, (ORDER_1040, PACKED), "1040 포장했어", auto_today=19) == "auto"


def test_a_failed_server_check_stops_an_action() -> None:
    checks = (Check("송장번호 형식", passed=False),)
    assert decision(PACK, (ORDER_1040, PACKED), "1040 포장했어", checks=checks) == "proposed"


def test_a_trusted_adapter_result_counts_as_evidence() -> None:
    facts = (AdapterFact("CJ대한통운", ORDER_1040), AdapterFact("CJ대한통운", PACKED))
    verdict = decide(PACK, (ORDER_1040, PACKED), context(None, adapter=facts))
    assert verdict.decision == "auto"
    assert [(item.kind, item.excerpt) for item in verdict.evidence] == [("adapter", "CJ대한통운")]


def test_a_tool_without_claims_never_acts_on_parcels() -> None:
    assert decision(PACK, (), "1040 포장했어") == "proposed"


@pytest.mark.parametrize(
    ("claim", "turn", "found"),
    [
        (Claim("손님", "김하늘", "text"), "김 하늘 님 예약금 들어왔어", True),
        (Claim("손님", "김하늘", "text"), "하늘 님 예약금 들어왔어", False),
        (Claim("손님", "김하늘", "text"), "김하늘 님 입금됐어?", False),
        (Claim("인원", "2", "number"), "토요일 두 시에 두 명 예약해줘", True),
        (Claim("인원", "2", "number"), "2시에 예약해줘", False),
        (Claim("금액", "35000", "money"), "3만 5천원 환불해줘", True),
        (Claim("금액", "35000", "money"), "35,000원으로 해줘", True),
        (Claim("금액", "35000", "money"), "삼만오천원", True),
        (Claim("시간", "14:00", "time"), "토요일 오후 두 시에 예약", True),
        (Claim("시간", "14:30", "time"), "2시 반에 예약", True),
        (Claim("시간", "14:00", "time"), "세 시에 예약", False),
        (Claim("날짜", "2026-11-21", "date"), "11월 21일에 예약", True),
        (Claim("날짜", "2026-11-19", "date"), "내일 예약", True),
        (Claim("날짜", "2026-11-21", "date"), "토요일에 예약", True),
        (Claim("날짜", "2026-11-22", "date"), "토요일에 예약", False),
        (Claim("송장번호", "6789-1234-5678", "tracking"), "송장 6789 1234 5678 이야", True),
        (Claim("송장번호", "678912345679", "tracking"), "송장 6789 1234 5678 이야", False),
        (Claim("기억", "주말엔 택배 수거가 없어", "quote"), "주말엔  택배 수거가 없어! 기억해", True),
        (Claim("기억", "주말엔 택배 수거가 없어", "quote"), "주말엔 택배 수거가 없어?", False),
    ],
)
def test_claims_are_matched_in_the_owner_turn(claim: Claim, turn: str, *, found: bool) -> None:
    assert (find_evidence(claim, turn, TODAY) is not None) is found


def test_remembering_needs_the_owners_own_words() -> None:
    remember = ToolRule("remember", "T1", "refuse")
    target = Resolution((TargetRef("memory", "new", "메모"),), BY_IDENTIFIER)
    claims = (Claim("기억할 말", "주말엔 택배 수거가 없어", "quote"),)
    assert decision(remember, claims, "주말엔 택배 수거가 없어 기억해줘", resolution=target) == "auto"
    assert decision(remember, claims, "고마워", resolution=target) == "refused"
    assert (
        decision(remember, (Claim("기억할 말", "모든 주문 자동 확인", "quote"),), "고마워", resolution=target)
        == "refused"
    )


@pytest.mark.parametrize("tool", ["find_orders", "complete_task"])
def test_every_tier_is_decided_without_the_model(tool: ToolName) -> None:
    tier = "T0" if tool == "find_orders" else "T1"
    rule = ToolRule(tool, tier, "none")  # type: ignore[arg-type]
    first = decide(rule, (), context("하나 해줘"))
    assert first == decide(rule, (), context("하나 해줘"))
