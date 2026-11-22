"""The number check compares a draft with the workshop's ledger without the model."""

from dataclasses import replace
from datetime import date, datetime

import pytest

from b_k25_claims import (
    LABEL_LEDGER,
    LABEL_PRICES,
    LABEL_RULE,
    UNASKED_PRICE,
    CardFact,
    Claim,
    Ledger,
    ModelClaim,
    RuleFact,
    SessionFact,
    check_numbers,
    claim_to_json,
    claims_from_json,
    deferral_only,
    evaluate,
    parse_model_claims,
    recheck,
    support_of,
)
from b_k25_interview import is_unsure, number_value
from b_k25_numbers import amount_spans, days_named, number_tokens, seat_spans
from display import SEOUL

TODAY = date(2026, 11, 18)
SATURDAY = datetime(2026, 11, 21, 10, 0, tzinfo=SEOUL)
WEEKEND = "주말 도자기 클래스"


def ledger(**changes: object) -> Ledger:
    base = Ledger(
        today=TODAY,
        sessions=(SessionFact(WEEKEND, SATURDAY, 8, 3, 25_000, 120),),
        cards=(CardFact(WEEKEND, price_won=38_000, parking="건물 뒤편 공영주차장 1시간 무료"),),
        policies=("예약·환불 규정: 수업 2일 전까지 전액 환불받을 수 있어요.",),
        question="토요일에 몇 명 가능한가요? 가격도 알려 주세요.",
        asked="토요일에 몇 명 가능한가요? 가격도 알려 주세요.",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("1인 38,000원이에요.", [38_000]),
        ("1인 3만 8천 원이에요.", [38_000]),
        ("3.5만 원 예산이에요.", [35_000]),
        ("5천 원 할인해요.", [5_000]),
        ("두 분이면 7만 원", [70_000]),
        ("10만원입니다.", [100_000]),
    ],
)
def test_amounts_read_korean_units(text: str, values: list[int]) -> None:
    assert [span.won for span in amount_spans(text)] == values


def test_deposit_is_told_apart_from_price() -> None:
    spans = amount_spans("예약금은 2만 5천 원이고, 수업료는 38,000원이에요.")
    assert [(span.won, span.is_deposit) for span in spans] == [(25_000, True), (38_000, False)]


@pytest.mark.parametrize(
    ("text", "count", "exact"),
    [
        ("토요일에 두 자리 가능해요.", 2, False),
        ("지금 두 자리 남았어요.", 2, True),
        ("남은 자리 3명이에요.", 3, True),
        ("4석까지 예약돼요.", 4, False),
        ("두 자리밖에 없어요.", 2, True),
    ],
)
def test_seat_counts_tell_remaining_from_possible(*, text: str, count: int, exact: bool) -> None:
    (span,) = seat_spans(text)
    assert (span.value, span.exact) == (count, exact)


def test_days_named_reads_weekdays_dates_and_relative_words() -> None:
    assert days_named("토요일에 가능해요", TODAY) == {date(2026, 11, 21)}
    assert days_named("다음 주 토요일", TODAY) == {date(2026, 11, 28)}
    assert days_named("11월 28일 수업", TODAY) == {date(2026, 11, 28)}
    assert days_named("내일 2시", TODAY) == {date(2026, 11, 19)}
    assert days_named("내일 2시", TODAY, relative=False) == frozenset()


def claim(draft: str, index: int = 0, **changes: object) -> Claim:
    return check_numbers(draft, ledger(**changes))[index]


def test_matching_seats_price_and_deposit_are_clear() -> None:
    draft = "토요일에 세 자리까지 가능하고, 1인 38,000원, 예약금은 25,000원이에요."
    result = evaluate(draft, ledger(), parse_model_claims(
        '[{"kind":"seats","text":"세 자리","value":"3"},'
        '{"kind":"price","text":"1인 38,000원","value":"38000"},'
        '{"kind":"deposit","text":"예약금은 25,000원","value":"25000"}]',
        draft,
    ))
    assert (result.lock, result.extraction_ok) == ("clear", True)
    assert {item.source for item in result.claims} == {"ledger", "price_list"}


def test_wrong_seats_price_and_deposit_lock_and_show_the_ledger() -> None:
    draft = "토요일에 네 자리 가능하고, 1인 35,000원, 예약금은 30,000원이에요."
    claims = check_numbers(draft, ledger())
    assert [(item.kind, item.status) for item in claims] == [
        ("seats", "mismatched"), ("price", "mismatched"), ("deposit", "mismatched"),
    ]
    assert claims[0].ledger_value == "11월 21일 토요일 10:00 3자리"
    assert (claims[1].source_label, claims[1].ledger_value) == (LABEL_PRICES, "38,000원")
    assert (claims[2].source_label, claims[2].ledger_value) == (LABEL_LEDGER, "25,000원")
    model = parse_model_claims(
        '[{"kind":"seats","text":"네 자리","value":"4"},{"kind":"price","text":"1인 35,000원"},'
        '{"kind":"deposit","text":"예약금은 30,000원"}]', draft,
    )
    result = evaluate(draft, ledger(), model)
    assert (result.lock, len(result.claims)) == ("locked", 3)


def test_a_single_ledger_value_is_offered_as_the_fix() -> None:
    draft = "토요일에 네 자리 가능하고, 1인 3만 5천 원, 예약금은 30,000원이에요. 수업은 90분 진행해요."
    claims = check_numbers(draft, ledger())
    assert [item.replacement for item in claims] == ["3자리", "38,000원", "25,000원", "120분"]
    two_prices = ledger(cards=(CardFact(WEEKEND, price_won=38_000), CardFact("머그컵", price_won=45_000)))
    assert check_numbers("1인 35,000원이에요.", two_prices)[0].replacement is None


def test_seats_are_checked_for_the_day_the_draft_names() -> None:
    far = ledger(sessions=(
        SessionFact(WEEKEND, SATURDAY, 8, 3, 25_000, 120),
        SessionFact(WEEKEND, datetime(2026, 11, 28, 10, 0, tzinfo=SEOUL), 8, 7, 25_000, 120),
    ))
    assert claim("토요일에 5자리 남았어요.").status == "mismatched"
    assert check_numbers("11월 28일에 7자리 남았어요.", far)[0].status == "matched"


def test_seat_without_a_listed_session_is_not_in_the_ledger() -> None:
    item = claim("11월 30일에 두 자리 가능해요.", index=1)
    assert (item.kind, item.status, item.ledger_value) == ("seats", "mismatched", None)


def test_unasked_price_locks_even_when_the_rule_supports_it() -> None:
    quiet = ledger(
        cards=(CardFact(WEEKEND),), rules=(RuleFact("6명부터 1인 30,000원", WEEKEND),),
        question="토요일 6명이서 할 수 있나요?", asked="토요일 6명이서 할 수 있나요?",
    )
    item = check_numbers("6명부터 1인 30,000원이에요.", quiet)[0]
    assert (item.status, item.note) == ("mismatched", UNASKED_PRICE)
    asked = replace(quiet, asked="6인 단체 견적 기준은?")
    assert check_numbers("6명부터 1인 30,000원이에요.", asked)[0].source_label == LABEL_RULE


def test_customer_amount_supports_a_price_only_when_no_price_is_known() -> None:
    quiet = ledger(cards=(), question="예산은 1인 3만 원이에요.", asked="예산은 1인 3만 원이에요.")
    assert check_numbers("예산은 1인 30,000원이라고 말씀하셨네요.", quiet)[0].source == "customer"
    known = claim("예산은 1인 30,000원이라고 말씀하셨네요.")
    assert known.ledger_value == "38,000원"


def test_dates_must_be_in_the_ledger_the_notes_or_the_question() -> None:
    assert claim("11월 21일에 만나요.").status == "matched"
    assert claim("11월 25일에 만나요.").status == "mismatched"
    noted = ledger(facts=("안내 · 12월 5일 휴무",))
    assert check_numbers("12월 5일은 쉬어요.", noted)[0].source == "fact_card"
    asked = replace(ledger(), question="12월 5일 가능한가요?")
    assert check_numbers("12월 5일은 어려워요.", asked)[0].source == "customer"


def test_class_length_and_capacity_use_the_ledger_over_the_card() -> None:
    card_only = ledger(sessions=(), cards=(CardFact(WEEKEND, duration_minutes=90, capacity=6),))
    assert check_numbers("수업은 90분 동안 진행해요.", card_only)[0].status == "matched"
    assert claim("수업은 90분 진행해요.").ledger_value == "120분"
    assert claim("정원 10명이에요.").ledger_value == "8명"
    assert check_numbers("손님 3분이 오셨어요.", ledger()) == []


def test_extraction_must_agree_with_the_regular_expressions() -> None:
    draft = "토요일에 3자리 있고 1인 38,000원이에요."
    agreeing = parse_model_claims(
        '[{"kind":"seats","text":"3자리"},{"kind":"price","text":"38,000원"}]', draft,
    )
    assert evaluate(draft, ledger(), agreeing).lock == "clear"
    missing = parse_model_claims('[{"kind":"seats","text":"3자리"}]', draft)
    missed = evaluate(draft, ledger(), missing)
    assert (missed.lock, missed.extraction_ok) == ("unchecked", False)
    failed = evaluate(draft, ledger(), None)
    assert (failed.lock, [item.status for item in failed.claims]) == ("unchecked", ["matched", "matched"])


def test_model_claims_outside_the_draft_are_dropped_and_bad_json_is_refused() -> None:
    draft = "주차는 건물 뒤편에 있어요."
    read = parse_model_claims(
        '```json\n[{"kind":"fact","text":"주차는 건물 뒤편"},'
        '{"kind":"price","text":"지어낸 문장"},{"kind":"unknown","text":"건물"}]\n```', draft,
    )
    assert read == (ModelClaim("fact", "주차는 건물 뒤편", ""), ModelClaim("fact", "건물", ""))
    assert parse_model_claims("없음", draft) is None
    assert parse_model_claims('{"kind":"fact"}', draft) is None


def test_a_statement_is_supported_by_the_owner_text_it_rests_on() -> None:
    item = support_of("건물 뒤편 공영주차장은 1시간 무료예요", ledger())
    assert item == ("fact_card", f"사실 카드: {WEEKEND}")
    assert support_of("주말에는 쉬어요", ledger()) is None
    assert support_of("수업 2일 전까지 전액 환불받을 수 있어요", ledger()) == ("fact_card", "공방 안내")


def test_recheck_keeps_statements_that_remain_and_reads_numbers_again() -> None:
    kept = [
        Claim("fact", "주차 안내", "", "fact_card", "사실 카드", "matched"),
        Claim("fact", "사라진 문장", "", "fact_card", "사실 카드", "matched"),
    ]
    draft = "주차 안내는 아래에 있어요. 1인 35,000원이에요."
    locked = recheck(draft, ledger(), kept, extraction_ok=True)
    assert (locked.lock, [item.text for item in locked.claims]) == ("locked", ["35,000원", "주차 안내"])
    fixed = "주차 안내는 아래에 있어요. 1인 38,000원이에요."
    assert recheck(fixed, ledger(), kept, extraction_ok=True).lock == "clear"
    assert recheck(fixed, ledger(), kept, extraction_ok=False).lock == "unchecked"
    assert recheck(draft, ledger(), kept, extraction_ok=False).lock == "locked"


def test_claims_round_trip_through_json() -> None:
    original = check_numbers("토요일에 네 자리 가능해요.", ledger())
    assert claims_from_json([claim_to_json(item) for item in original]) == tuple(original)
    assert claims_from_json([{"kind": "poem", "text": "x"}]) == ()


def test_deferral_only_means_no_claim_is_made() -> None:
    assert deferral_only("확인해서 다시 알려드릴게요.", [])
    assert not deferral_only("수업은 토요일이에요. 나머지는 확인해서 알려드릴게요.", [
        Claim("date", "토요일", "", "ledger", "예약 장부", "matched"),
    ])


def test_rule_numbers_are_compared_after_normalizing_units() -> None:
    assert number_tokens("6명부터 1인 3만 원") == number_tokens("6명부터 1인 30,000원")
    assert number_tokens("6명부터 1인 3만 원") != number_tokens("8명부터 1인 3만 원")


@pytest.mark.parametrize(
    ("field", "answer", "expected"),
    [
        ("durationMinutes", "두 시간이에요", "120"),
        ("durationMinutes", "2시간 30분 정도 걸려요", "150"),
        ("durationMinutes", "한 시간 반이요", "90"),
        ("durationMinutes", "구십 분 걸려요", "90"),
        ("durationMinutes", "1.5시간이요", "90"),
        ("capacity", "여섯 명까지 받아요", "6"),
        ("capacity", "8명", "8"),
        ("capacity", "10", "10"),
        ("capacity", "6명에서 8명이요", None),
        ("durationMinutes", "모르겠어요", None),
        ("includedMaterials", "앞치마", None),
    ],
)
def test_interview_numbers_come_from_the_answer_alone(field: str, answer: str, expected: str | None) -> None:
    assert number_value(field, answer) == expected  # type: ignore[arg-type]


def test_unsure_answers_are_not_values() -> None:
    assert is_unsure("글쎄요")
    assert is_unsure("  ")
    assert not is_unsure("주차는 어려워요")
