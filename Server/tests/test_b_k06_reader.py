"""The rule reader never guesses money: an uncertain clause is undecided or unread, whoever read it."""

import pytest

from b_k06_logic import (
    ExtractedPolicy,
    LateRule,
    Payment,
    Policy,
    Rule,
    blocking,
    checked_policy,
    compute,
    parse_policy,
)
from tests.conftest import NOW


def read(text: str) -> Policy:
    return checked_policy(parse_policy(text), text)


def tiers(policy: Policy) -> dict[int, int | None]:
    return {rule.days_before: rule.refund_percent for rule in policy.rules}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("7일 전까지 100%, 3일 전까지 50%, 당일 환불 불가", {7: 100, 3: 50, 0: 0}),
        ("이틀 전까지 전액 환불, 하루 전까지 50%", {2: 100, 1: 50}),
        ("사흘 전까지 전액 환불\n나흘 전까지 전액 환불", {4: 100, 3: 100}),
        ("2주 전까지 전액 환불, 일주일 전까지 반액 환불", {14: 100, 7: 50}),
        (
            "수업 3일 전까지 취소 시 전액 환불됩니다. 전날 취소는 절반 환불해 드려요.",
            {3: 100, 1: 50},
        ),
        ("3일 전까지는 전액 환불이고 당일은 환불이 안 돼요", {3: 100, 0: 0}),
        ("3일 전까지 전액 환불, 2일 전 50% 환불, 1일 전 환불 불가", {3: 100, 2: 50, 1: 0}),
    ],
)
def test_plain_clauses_are_read(text: str, expected: dict[int, int | None]) -> None:
    policy = read(text)
    assert tiers(policy) == expected
    assert [line for line in policy.unread if blocking(line)] == []


def test_material_is_deducted_only_from_a_full_refund() -> None:
    policy = read("3일 전까지 재료비 공제 후 전액 환불")
    assert [(rule.refund_percent, rule.deduct_material) for rule in policy.rules] == [(100, True)]


UNCERTAIN = [
    "3일 전 취소 시 30% 공제 후 환불",
    "2일 전 취소는 위약금 50%",
    "3일 전 취소 수수료 20%",
    "3일 전 20%를 제외하고 환불",
    "3일 전 10% 차감",
    "3일 전부터 환불 불가",
    "수업 2일 전 이후 취소는 환불 불가",
    "3일 이내 환불 불가",
    "3일 전 안에 취소하면 50%",
    "3일 미만 50% 환불",
    "영업일 기준 3일 전까지 전액 환불",
    "평일 3일 전까지 전액 환불",
    "당일은 환불이 어려워요",
    "당일 취소 불가",
    "당일 환불 불가이나 질병은 예외",
    "3일 전 100% 2일 전 50%",
    "7일 전 ~ 3일 전 50% 환불",
    "3~5일 전 50% 환불",
    "3일에서 5일 전 50%",
    "3일 전까지 전액 환불(단, 재료비 제외)",
    "2일 전 50% 환불(재료비 공제)",
    "2일 전 재료비 공제 후 50% 환불",
    "2일 전 33.3% 환불",
    "2일 전 5,000원 공제 후 환불",
    "전액 환불 불가 3일 전",
    "3일 전까지 환불 불가",
    "24시간 전까지 전액 환불",
    "정규반은 7일 전까지 50% 환불",
    "3일 전 전액 환불 또는 이월",
    "3일 전 150% 환불",
    "3일 전 환불 불가하지 않아요",
    "3일 전 50% 이상 환불",
    "3일 전 최대 50% 환불",
    "한 달 전까지 전액 환불",
]


@pytest.mark.parametrize("text", UNCERTAIN)
def test_an_uncertain_clause_never_becomes_a_number(text: str) -> None:
    policy = read(text)
    assert [value for value in tiers(policy).values() if value is not None] == []
    assert any(blocking(line) for line in policy.unread)


@pytest.mark.parametrize("text", ["당일 변경 불가", "전날 이월 불가"])
def test_a_change_rule_is_not_a_refund_rule(text: str) -> None:
    policy = read(text)
    assert policy.rules == ()
    assert policy.unread == (text,)
    assert not blocking(text)


@pytest.mark.parametrize(
    "text",
    [
        "당일 환불 불가, 단 질병은 제외",
        "당일 환불 불가. 다만 천재지변은 협의",
        "3일 전까지 전액 환불. 영업일 기준입니다.",
        "3일 전까지 전액 환불, 재료비는 빼고 드려요",
        "3일 전까지 전액 환불. 노쇼는 환불 불가",
    ],
)
def test_a_later_exception_keeps_the_whole_table_unsettled(text: str) -> None:
    assert any(blocking(line) for line in read(text).unread)


@pytest.mark.parametrize(
    "text", ["취소 수수료\n3일 전 20%\n당일 100%", "위약금: 3일 전 20%, 2일 전 50%, 당일 100%"],
)
def test_bare_percentages_under_a_fee_heading_are_undecided(text: str) -> None:
    assert [value for value in tiers(read(text)).values() if value is not None] == []


@pytest.mark.parametrize("text", ["3일 전 50%, 3일 전 70%", "3일 전 50% 환불, 당일 70% 환불"])
def test_contradicting_tiers_are_undecided(text: str) -> None:
    policy = read(text)
    assert [value for value in tiers(policy).values() if value is not None] == []
    assert any(blocking(line) for line in policy.unread)


@pytest.mark.parametrize(
    ("text", "row"),
    [
        (
            "3일 전 취소 시 30% 공제 후 환불",
            Rule(days_before=3, refund_percent=30, note="30% 공제 후 환불"),
        ),
        (
            "3일 전 취소 시 30% 공제 후 환불",
            Rule(days_before=3, refund_percent=30, note="3일 전 취소 시 30%"),
        ),
        ("2일 전 취소는 위약금 50%", Rule(days_before=2, refund_percent=50, note="위약금 50%")),
        ("3일 전부터 환불 불가", Rule(days_before=3, refund_percent=0, note="환불 불가")),
        (
            "수업 2일 전 이후 취소는 환불 불가",
            Rule(days_before=2, refund_percent=0, note="취소는 환불 불가"),
        ),
        ("당일 변경 불가", Rule(days_before=0, refund_percent=0, note="당일 변경 불가")),
        (
            "영업일 기준 3일 전까지 전액 환불",
            Rule(days_before=3, refund_percent=100, note="3일 전까지 전액 환불"),
        ),
        ("당일 환불 불가", Rule(days_before=0, refund_percent=50, note="당일 환불 불가")),
        (
            "하루 전이면 반만 돌려드려요",
            Rule(days_before=1, refund_percent=70, note="반만 돌려드려요"),
        ),
    ],
)
def test_a_model_row_cannot_outvote_its_own_sentence(text: str, row: Rule) -> None:
    policy = checked_policy(ExtractedPolicy(rules=[row]), text)
    assert [value for value in tiers(policy).values() if value is not None] == []


def test_a_model_row_may_add_a_sentence_the_rules_cannot_parse() -> None:
    text = "수업 시작 3일 전까지 알려 주시면 예약금 전액을 돌려드려요"
    row = Rule(days_before=3, refund_percent=100, note="3일 전까지 알려 주시면 예약금 전액")
    policy = checked_policy(ExtractedPolicy(rules=[row]), text)
    assert tiers(policy) == {3: 100}
    assert policy.unread == ()


def test_a_clause_the_model_left_out_stays_visible() -> None:
    text = "3일 전까지 전액 환불, 2일 전은 상황에 따라 환불"
    row = Rule(days_before=3, refund_percent=100, note="3일 전까지 전액 환불")
    policy = checked_policy(ExtractedPolicy(rules=[row]), text)
    assert tiers(policy) == {3: 100, 2: None}
    assert policy.unread == ("2일 전은 상황에 따라 환불",)


def test_a_late_rule_must_match_its_sentence() -> None:
    text = "15분 넘게 늦으면 노쇼"
    wrong = ExtractedPolicy(late=LateRule(late_minutes=30, note=text))
    assert checked_policy(wrong, text).late == LateRule(late_minutes=15, note=text)


@pytest.mark.parametrize(
    "rules", [[Rule(days_before=0, refund_percent=0)], [Rule(days_before=2, refund_percent=0)]],
)
def test_an_early_cancellation_is_never_zero_by_a_late_tier_alone(rules: list[Rule]) -> None:
    assert compute(rules, NOW, NOW.replace(day=8), Payment(20000, None)).refund is None
