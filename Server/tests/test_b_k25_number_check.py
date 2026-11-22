"""What the number check must see, must leave alone, and must lock on without the model's help."""

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from b_k25_claims import (
    CardFact,
    Claim,
    Ledger,
    RuleFact,
    SessionFact,
    check_numbers,
    evaluate,
    parse_model_claims,
    recheck,
)
from display import SEOUL

WEEKEND = "주말 도자기 클래스"
SATURDAY = datetime(2026, 11, 21, 10, 0, tzinfo=SEOUL)
QUESTION = "토요일에 자리 있나요? 가격도 알려 주세요."
LEDGER = Ledger(
    today=date(2026, 11, 18),
    sessions=(SessionFact(WEEKEND, SATURDAY, 8, 3, 25_000, 120),),
    cards=(CardFact(
        WEEKEND, price_won=38_000, included_materials="점토 1kg과 앞치마 1벌",
        parking="건물 뒤편 공영주차장 1시간 무료",
    ),),
    policies=("예약·환불 규정: 수업 2일 전까지 전액 환불받을 수 있어요.",),
    question=QUESTION, asked=QUESTION,
)
GROUP_RULE = RuleFact("6명부터 1인 30,000원", WEEKEND)
REVIEWED_WRONG = [
    ("1인 삼만오천원이에요.", "38,000원"),
    ("₩35,000입니다.", "38,000원"),
    ("1인당 35k예요.", "38,000원"),
    ("아직 5명 더 받을 수 있어요.", "3자리"),
    ("토요일 오후 2시에 시작해요.", "10:00"),
    ("수업 하루 전까지 전액 환불돼요.", "2일 전까지"),
    ("주차는 2시간 무료예요.", "1시간 무료"),
    ("세 명이면 총 12만원이에요.", "114,000원"),
]
WRONG = [
    *REVIEWED_WRONG,
    ("1인 삼만 오천 원이에요.", "38,000원"),
    ("1인 3만오천원이에요.", "38,000원"),
    ("1인 3만 5천이에요.", "38,000원"),
    ("1인 KRW 35,000입니다.", "38,000원"),
    ("1인 25,000원이에요.", "38,000원"),
    ("수업료는 25,000원이에요.", "38,000원"),
    ("두 분이면 총 38,000원이에요.", "76,000원"),
    ("1인 38,000원이고 두 분이면 총 70,000원이에요.", "76,000원"),
    ("다섯 분까지 예약 가능해요.", "3자리"),
    ("네 명 더 오실 수 있어요.", "3자리"),
    ("지금 4명 남았어요.", "3자리"),
    ("두 자리는 어려워요.", "3자리"),
    ("토요일 14시에 시작해요.", "10:00"),
    ("토요일 14:00에 시작해요.", "10:00"),
    ("오전 10시 30분에 시작해요.", "10:00"),
    ("10시 반에 시작해요.", "10:00"),
    ("오후 10시에 시작해요.", "10:00"),
    ("두 시에 시작해요.", "10:00"),
    ("수업은 오전 10시부터 오후 1시까지예요.", "10:00"),
    ("토요일 오전 10시 수업은 없어요.", "10:00"),
    ("수업은 세 시간이에요.", "120분"),
    ("수업은 반나절 걸려요.", "120분"),
    ("수업은 구십 분 진행해요.", "120분"),
    ("정원은 열 명이에요.", "8명"),
    ("사흘 전까지 전액 환불돼요.", "2일 전까지"),
    ("수업 3일 전까지 취소하시면 돼요.", "2일 전까지"),
    ("수업 24시간 전까지 전액 환불돼요.", "2일 전까지"),
    ("수업 전날까지 전액 환불돼요.", "2일 전까지"),
    ("당일에 취소하셔도 환불돼요.", "2일 전까지"),
    ("취소하시면 50% 환불돼요.", "2일 전까지"),
    ("수업 이틀 전에는 환불이 어려워요.", "2일 전까지"),
    ("주차는 세 시간까지 무료예요.", "1시간 무료"),
    ("주차는 30분 무료예요.", "1시간 무료"),
    ("주차는 건물 뒤편에 있고 2시간 무료예요.", "1시간 무료"),
    ("주차장은 건물 뒤편이에요. 2시간 무료예요.", "1시간 무료"),
    ("재료는 점토 2kg을 드려요.", "점토 1kg"),
    ("11월 21일 일요일에 만나요.", "11월 21일 토요일"),
    ("11/25(수)에 만나요.", "11월 21일 토요일"),
    ("25일 수요일에 만나요.", "11월 21일 토요일"),
    ("11.28(토)에 만나요.", "11월 21일 토요일"),
    ("11월 20일까지 취소하시면 전액 환불돼요.", "11월 19일 목요일"),
    ("7일 전까지만 환불 가능해요.", "2일 전까지"),
    ("하루 전에 말씀해 주시면 전액 돌려드려요.", "2일 전까지"),
    ("차는 2시간까지 무료로 대실 수 있어요.", "1시간 무료"),
    ("1인 35,000won이에요.", "38,000원"),
    ("수업은 2pm에 시작해요.", "10:00"),
    ("예약금 25,000원을 뺀 나머지 15,000원은 당일에 결제해 주세요.", "13,000원"),
    ("지금 다섯 분 자리가 남았어요.", "3자리"),
    ("총 150분입니다.", "120분"),
    ("두 자리 예약하시면 70,000원이에요.", "76,000원"),
    ("하루 전까지, 전액 환불돼요.", "2일 전까지"),
    ("일요일에도 수업이 있어요.", "11월 21일 토요일"),
    ("수요일에 수업을 진행해요.", "11월 21일 토요일"),
    ("다음 주 토요일에 수업이 있어요.", "11월 21일 토요일"),
    ("토요일은 수업이 없어요.", "11월 21일 토요일"),
    ("토요일 수업은 마감됐어요.", "11월 21일 토요일"),
    ("수업은 일요일이에요.", "11월 21일 토요일"),
    ("토요일 클래스는 열지 않아요.", "11월 21일 토요일"),
]
KEPT = [
    "1인 38,000원이에요.", "1인 3만8천원이에요.", "남은 자리 3자리예요.", "11월 21일 토요일 10시예요.",
    "2시간 수업이에요.", "정원 8명이에요.", "예약금 25,000원이에요.", "수업 2일 전까지 전액 환불돼요.",
]
RIGHT = [
    *KEPT,
    "두 명이면 76,000원이에요.",
    "1인 삼만팔천원이에요.", "₩38,000입니다.", "1인당 38k예요.", "1인 3만 8천이에요.",
    "1인 38,000원이고 두 분이면 총 76,000원이에요.", "1인당 38,000원, 두 분 합계 76,000원이에요.",
    "성인 두 분과 아이 한 분이시면 총 114,000원이에요.", "두 분 예약 가능하고 수업료는 38,000원이에요.",
    "예약금 없이 38,000원이에요.",
    "아직 3명 더 받을 수 있어요.", "두 분 예약 가능해요.", "세 분까지 참여하실 수 있어요.",
    "5자리는 어렵고 3자리 남았어요.", "다섯 분은 받기 어려워요.",
    "토요일 오전 10시에 시작해요.", "10:00에 시작해요.", "열 시에 시작해요.",
    "오전 10시부터 낮 12시까지 진행해요.", "오후 2시 수업은 없고 오전 10시에 시작해요.",
    "수업은 두 시간이에요.", "수업은 백이십 분이에요.", "재료비가 포함된 2시간 수업이에요.",
    "주차는 어렵고 2시간 수업이에요.",
    "이틀 전까지 전액 환불돼요.", "수업 48시간 전까지 전액 환불돼요.", "수업 하루 전에는 환불이 어려워요.",
    "주차는 한 시간 무료예요.", "주차장은 60분까지 무료예요.", "앞치마 1벌을 준비해 드려요.",
    "11/21(토)에 만나요.", "11월 25일은 수업이 없어요.",
    "예약금 25,000원을 뺀 나머지 13,000원은 당일에 결제해 주세요.",
    "수업 이틀 전인 11월 19일까지 취소하시면 전액 환불돼요.",
    "두 분이 쓰실 앞치마 2벌을 준비해 둘게요.",
    "오전 10시에 시작해 정오에 마칩니다.", "오전 10시 수업이 끝나면 12시쯤 됩니다.",
    "수업 하루 전이나 당일에 취소하시면 환불해 드리기 어렵습니다.",
    "두 자리 예약하시면 76,000원이고 예약금은 25,000원이에요.",
    "2일 전까지 취소하시면 위약금이 없어요.",
    "토요일에 수업이 있어요.", "이번 주 토요일에 수업을 열어요.", "일요일은 수업이 없어요.",
    "월요일은 수업을 쉬어요.", "수업 2일 전인 목요일까지 취소하시면 전액 환불돼요.",
    "일요일 클래스는 아직 열지 않고 있어요.", "일요일에는 체험을 진행하지 않아요.",
    "토요일 오후 2시 수업은 없어요.",
]
QUIET = [
    "수업은 30분 단위로 예약을 받아요.", "수업 시작 10분 전까지 오세요.", "오후 6시까지 다시 연락드릴게요.",
    "두 분 가능한지 확인해서 알려드릴게요.", "편한 시간에 문의 주세요.", "이만 줄일게요.",
    "1:1 수업이에요.", "이 시간에는 전화가 어려워요.", "수업 전에 30분 정도 상담해 드려요.",
    "오전 10시에 시작하니 9시 50분까지 와 주세요.",
    "주차는 1시간 무료이고 수업은 2시간이라 1시간은 유료예요.",
    "말씀하신 1인 3만 원은 어렵고, 1인 38,000원으로 안내드리고 있습니다.",
    "수업 안내는 금요일에 전화로 드릴게요.", "화요일에 작품을 찾으러 오세요.",
    "토요일 수업에 다섯 분은 어려워요.", "토요일 수업은 어렵지 않아요.",
    "수업 전날인 금요일에 안내 문자를 보내 드려요.", "토요일 수업이 끝나면 일요일에 가마를 때요.",
    "토요일 저녁 수업은 없어요.", "토요일에 다른 수업은 없어요.",
    "금요일 저녁에는 수업 준비를 해요.", "월요일에 수업료를 환불해 드렸어요.",
]


def mismatched(draft: str, ledger: Ledger = LEDGER) -> list[Claim]:
    return [claim for claim in check_numbers(draft, ledger) if claim.status == "mismatched"]


def session(starts_at: datetime, seats_left: int) -> SessionFact:
    return SessionFact(WEEKEND, starts_at, 8, seats_left, 25_000, 120)


@pytest.mark.parametrize(("draft", "shown"), WRONG)
def test_a_wrong_number_is_seen_and_the_ledger_is_shown(draft: str, shown: str) -> None:
    (wrong,) = mismatched(draft)
    assert shown in (wrong.ledger_value or "")


@pytest.mark.parametrize("draft", RIGHT)
def test_a_right_number_is_matched_and_never_locked(draft: str) -> None:
    claims = check_numbers(draft, LEDGER)
    assert claims
    assert {claim.status for claim in claims} == {"matched"}


@pytest.mark.parametrize("draft", QUIET)
def test_numbers_that_are_not_about_the_class_do_not_lock(draft: str) -> None:
    assert mismatched(draft) == []


@pytest.mark.parametrize("draft", [draft for draft, _ in WRONG])
def test_a_fix_the_screen_offers_passes_the_check(draft: str) -> None:
    (wrong,) = mismatched(draft)
    if wrong.replacement is not None:
        assert mismatched(draft.replace(wrong.text, wrong.replacement, 1)) == []


@pytest.mark.parametrize(
    ("draft", "fix"),
    [
        ("수업은 3시간이에요.", "2시간"), ("수업은 90분 진행해요.", "120분"),
        ("수업 하루 전까지 전액 환불돼요.", "2일"), ("주차는 2시간 무료예요.", "1시간"),
        ("토요일 오후 2시에 시작해요.", "오전 10시"), ("아직 5명 더 받을 수 있어요.", "3명"),
        ("세 명이면 총 12만원이에요.", "114,000원"), ("토요일에 네 자리 가능해요.", "3자리"),
    ],
)
def test_the_fix_keeps_the_words_of_the_draft(draft: str, fix: str) -> None:
    (wrong,) = mismatched(draft)
    assert wrong.replacement == fix


def test_twelve_seats_are_not_read_as_two() -> None:
    (wrong,) = mismatched("열두 자리 남았어요.")
    assert wrong.value == "12"


def test_a_total_uses_the_headcount_of_the_question_when_the_sentence_names_none() -> None:
    pair = replace(LEDGER, question="두 명 가격이 얼마예요?", asked="두 명 가격이 얼마예요?")
    assert mismatched("총 76,000원이에요.", pair) == []
    (wrong,) = mismatched("총 70,000원이에요.", pair)
    assert wrong.replacement == "76,000원"


def test_a_group_rule_prices_groups_and_not_pairs() -> None:
    group = replace(LEDGER, rules=(GROUP_RULE,), question="6명 가격이요", asked="6명 가격이요")
    (total,) = check_numbers("6명이면 총 180,000원이에요.", group)
    assert (total.status, total.source) == ("matched", "owner_rule")
    (pair,) = mismatched("두 분이면 1인 30,000원이에요.", group)
    assert pair.ledger_value == "38,000원"


def test_the_customers_own_number_does_not_prove_an_answer() -> None:
    asked = replace(LEDGER, question="11월 25일 가능한가요?", asked="11월 25일 가능한가요?")
    assert len(mismatched("네, 11월 25일에 가능해요.", asked)) == 1
    assert mismatched("11월 25일은 어려워요.", asked) == []
    unpriced = replace(LEDGER, cards=(), question="1인 3만 원 맞나요?", asked="1인 3만 원 맞나요?")
    assert len(mismatched("네, 1인 30,000원이에요.", unpriced)) == 1


@pytest.mark.parametrize("dash", ["~", "-", "\u2013", "\uff5e"])
def test_a_range_of_hours_ends_at_its_second_time(dash: str) -> None:
    assert mismatched(f"수업은 10:00{dash}12:00이에요.") == []
    assert len(mismatched(f"수업은 10:00{dash}13:00이에요.")) == 1
    assert mismatched(f"수업은 2{dash}3시간 걸려요.") == []


def test_agreeing_to_what_the_customer_said_needs_the_ledger() -> None:
    words = "11월 28일에 1인 3만 원으로 될까요?"
    asked = replace(LEDGER, cards=(), question=words, asked=words)
    for draft in ("네, 말씀하신 11월 28일로 예약해 드릴게요.", "네, 말씀하신 1인 3만 원으로 가능해요.",
                  "1인 3만 원이면 괜찮아요."):
        assert len(mismatched(draft, asked)) == 1
    for draft in ("말씀하신 11월 28일은 어려워요.", "말씀하신 3만 원은 어려워요.",
                  "예산이 3만 원이라고 말씀하셨네요."):
        assert mismatched(draft, asked) == []


def test_each_day_is_compared_with_its_own_session() -> None:
    two = replace(LEDGER, sessions=(
        session(SATURDAY, 3), session(SATURDAY + timedelta(days=7, hours=4), 7),
    ))
    assert mismatched("11월 21일은 3자리, 11월 28일은 7자리 남았어요.", two) == []
    assert len(mismatched("11월 21일은 7자리, 11월 28일은 3자리 남았어요.", two)) == 2
    assert mismatched("11월 28일은 오후 2시에 시작해요.", two) == []
    assert len(mismatched("11월 21일은 오후 2시에 시작해요.", two)) == 1


def test_each_class_of_a_day_is_compared_with_its_own_seats_and_hours() -> None:
    day = replace(LEDGER, sessions=(session(SATURDAY, 3), session(SATURDAY + timedelta(hours=4), 7)))
    assert mismatched("토요일 오전 10시 수업은 3자리, 오후 2시 수업은 7자리 남았어요.", day) == []
    assert len(mismatched("토요일 오전 10시 수업은 7자리, 오후 2시 수업은 3자리 남았어요.", day)) == 2
    assert mismatched("수업은 오후 2시부터 4시까지예요.", day) == []
    (late,) = mismatched("수업은 오전 10시부터 오후 4시까지예요.", day)
    assert late.replacement == "오후 12시"


def test_a_full_class_may_be_called_full_and_an_owner_text_may_name_a_weekday() -> None:
    full = replace(LEDGER, sessions=(session(SATURDAY, 0),))
    assert mismatched("토요일 수업은 마감됐어요.", full) == []
    noted = replace(LEDGER, policies=(*LEDGER.policies, "클래스 안내: 일요일 수업은 예약이 들어오면 열어요."))
    (claim,) = check_numbers("일요일에도 수업을 열어요.", noted)
    assert (claim.status, claim.source) == ("matched", "fact_card")


def test_a_discount_needs_the_owners_own_words() -> None:
    (promised,) = mismatched("10% 할인해 드려요.")
    assert (promised.source, promised.ledger_value) == ("none", None)
    rule = replace(LEDGER, rules=(RuleFact("6명부터 10% 할인", WEEKEND),))
    (claim,) = check_numbers("단체는 10% 할인해 드려요.", rule)
    assert (claim.status, claim.source) == ("matched", "owner_rule")
    (wrong,) = mismatched("단체는 20% 할인해 드려요.", rule)
    assert (wrong.ledger_value, wrong.replacement) == ("6명부터 10% 할인", "10%")
    assert mismatched("20% 할인은 어려워요.", rule) == []


def test_a_half_hour_start_is_a_time_and_not_a_length() -> None:
    half = replace(LEDGER, sessions=(session(SATURDAY + timedelta(minutes=30), 3),))
    for start in ("오전 10시 30분", "10시 반", "10:30"):
        (claim,) = check_numbers(f"수업은 {start}에 시작해요.", half)
        assert claim.status == "matched"


def test_the_ledger_wins_over_a_card_that_says_something_else() -> None:
    stale = replace(LEDGER, cards=(CardFact(WEEKEND, duration_minutes=90, capacity=12, price_won=38_000),))
    assert len(mismatched("수업은 90분 진행해요.", stale)) == 1
    assert len(mismatched("정원 12명이에요.", stale)) == 1


def test_a_deposit_is_not_backed_by_a_price_the_owner_wrote() -> None:
    noted = replace(LEDGER, facts=("원데이 클래스 1인 38,000원",))
    (wrong,) = mismatched("예약금은 38,000원이에요.", noted)
    assert wrong.ledger_value == "25,000원"


def test_a_time_after_the_end_or_the_opening_hours_is_not_a_start() -> None:
    open_hours = replace(LEDGER, policies=(*LEDGER.policies, "영업시간: 오전 10시부터 오후 8시까지"))
    assert len(mismatched("수업은 12시에 시작해요.")) == 1
    assert len(mismatched("수업은 오후 8시에 시작해요.", open_hours)) == 1
    assert mismatched("영업시간은 오전 10시부터 오후 8시까지예요.", open_hours) == []
    (late,) = mismatched("토요일 오후 2시까지 오세요.")
    assert late.replacement == "오전 10시"


def test_a_topic_without_owner_text_is_not_in_the_ledger() -> None:
    bare = replace(LEDGER, cards=(CardFact(WEEKEND, price_won=38_000),), policies=())
    for draft in ("주차는 2시간 무료예요.", "수업 2일 전까지 전액 환불돼요."):
        (wrong,) = mismatched(draft, bare)
        assert (wrong.source, wrong.ledger_value) == ("none", None)


def test_a_known_mismatch_locks_without_the_model() -> None:
    wrong = "1인 35,000원이에요."
    failed = evaluate(wrong, LEDGER, None)
    assert (failed.lock, failed.extraction_ok) == ("locked", False)
    disagreeing = evaluate(wrong, LEDGER, parse_model_claims("[]", wrong))
    assert (disagreeing.lock, disagreeing.extraction_ok) == ("locked", False)
    assert recheck(wrong, LEDGER, (), extraction_ok=False).lock == "locked"


def test_agreeing_numbers_stay_unchecked_without_the_model() -> None:
    right = "1인 38,000원이에요."
    assert evaluate(right, LEDGER, None).lock == "unchecked"
    assert recheck(right, LEDGER, (), extraction_ok=False).lock == "unchecked"


def test_a_number_only_the_model_can_read_is_never_clear() -> None:
    draft = "1인 삼점팔만 원이에요."
    model = parse_model_claims('[{"kind":"price","text":"삼점팔만 원","value":"38000"}]', draft)
    assert evaluate(draft, LEDGER, model).lock == "unchecked"


def test_a_number_is_listed_once_when_the_draft_is_checked_again() -> None:
    draft = "수업은 90분 진행해요."
    first = evaluate(draft, LEDGER, parse_model_claims("[]", draft))
    again = recheck(draft, LEDGER, first.claims, extraction_ok=True)
    assert [claim.text for claim in again.claims] == ["90분"]
