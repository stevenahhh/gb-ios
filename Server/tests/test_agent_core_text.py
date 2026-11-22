"""Korean numbers, clock times, dates, and questions are read the way the owner says them."""

from datetime import date, time
from typing import Final

import pytest

from agent_mask import Masker, unmasked
from agent_run import without_claims
from agent_text import clock_times, dates_named, is_negated, is_question, is_unfinished, mentions, same_clock
from agent_toolkit import name_confidence
from agent_types import BY_FULL_NAME, BY_PART_OF_NAME

TODAY: Final = date(2026, 11, 18)
TRACKING: Final = "102345678901"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1040", [(1040, "")]),
        ("천사십", [(1040, "")]),
        ("일공사공", [(1040, "")]),
        ("1,040원", [(1040, "money")]),
        ("3만 5천원", [(35000, "money")]),
        ("삼만오천원", [(35000, "money")]),
        ("두 명", [(2, "people")]),
        ("스물다섯 명", [(25, "people")]),
        ("만원", [(10000, "money")]),
        ("2일 남음", [(2, "date")]),
        ("천천히 해도 돼", []),
        ("30분 뒤", [(30, "clock")]),
        ("세 분 오세요", [(3, "people")]),
    ],
)
def test_numbers_are_read_with_what_they_count(text: str, expected: list[tuple[int, str]]) -> None:
    assert [(found.value, found.unit) for found in mentions(text)] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("오후 두 시 반", [(14, 30)]),
        ("10:00 수업", [(10, 0)]),
        ("오전 12시", [(0, 0)]),
        ("3시 30분", [(3, 30)]),
        ("밤 9시", [(21, 0)]),
        ("아침 9시", [(9, 0)]),
    ],
)
def test_clock_times_are_read(text: str, expected: list[tuple[int, int]]) -> None:
    assert [(hour, minute) for hour, minute, *_ in clock_times(text)] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("11월 21일", "2026-11-21"),
        ("21일", "2026-11-21"),
        ("내일", "2026-11-19"),
        ("어제", "2026-11-17"),
        ("11/21", "2026-11-21"),
        ("2026-12-01", "2026-12-01"),
        ("토요일", "2026-11-21"),
        ("5일", "2026-12-05"),
    ],
)
def test_dates_are_read_relative_to_today(text: str, expected: str) -> None:
    assert [day.isoformat() for day, *_ in dates_named(text, TODAY)] == [expected]


def test_a_number_in_a_time_is_never_read_as_a_count() -> None:
    assert [found.unit for found in mentions("10시에 두 명")] == ["clock", "people"]
    assert all(day is not None for day in dates_named("11/21", TODAY))


@pytest.mark.parametrize(
    ("clock", "wanted", "same"),
    [
        (2, time(14), True),
        (14, time(14), True),
        (2, time(14, 30), False),
        (3, time(14), False),
    ],
)
def test_an_hour_without_a_meridiem_fits_either_half_of_the_day(
    clock: int, wanted: time, *, same: bool,
) -> None:
    assert same_clock(clock, 0, wanted) is same


@pytest.mark.parametrize("text", ["포장했어?", "몇 건이야", "언제 와", "됐나", "할까요"])
def test_questions_are_recognized(text: str) -> None:
    assert is_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "들어오면 확정해 줘",
        "기사님이 1040 포장 끝났냐고 물어보시네",
        "오늘 저녁까지 포장 끝낼게",
        "포장할 예정이야",
        "1040 포장했다고 전해줘",
        "내일 포장하려고 해",
    ],
)
def test_conditions_plans_and_reported_words_are_not_done(text: str) -> None:
    assert is_unfinished(text)


@pytest.mark.parametrize("text", ["포장 끝났어", "도착했어", "수거됐어", "그렇게 처리해", "완전히 끝났어"])
def test_finished_statements_are_not_plans(text: str) -> None:
    assert not is_unfinished(text)


def test_statements_and_denials_are_told_apart() -> None:
    assert not is_question("포장 끝났어")
    assert is_negated("아직 안 했어")
    assert not is_negated("포장 다 했어")


def test_the_model_never_sees_names_phones_or_addresses_but_keeps_order_and_tracking_numbers() -> None:
    masker = Masker.of(["김하늘", "김하"])
    shown = masker.text(
        f"김하늘 님 010-1234-5678, 주소 서울시 강남구 테헤란로 12, 송장 {TRACKING}, 주문 1040",
    )
    for hidden in ("김하늘", "010-1234-5678", "테헤란로"):
        assert hidden not in shown
    for kept in (TRACKING, "1040"):
        assert kept in shown
    assert masker.text("전화 02-123-4567") == "전화 (연락처 가림)"
    assert masker.text("010 1234 5678") == "(연락처 가림)"


@pytest.mark.parametrize("number", ["102345678901", "61031119284", "6103-1111-9284", "1040"])
def test_order_and_tracking_numbers_stay_readable(number: str) -> None:
    assert number in Masker.of(["김하늘"]).text(f"송장 {number} 등록해줘")


def test_masked_names_go_back_to_the_real_one_only_when_unique() -> None:
    masker = Masker.of(["김하늘", "김바늘", "이수진"])
    assert masker.aliases("김하늘 님 예약금") == {"김*늘": "김하늘"}
    assert masker.aliases("이수진 님 예약") == {"이*진": "이수진"}
    both = masker.aliases("김하늘 님과 김바늘 님")
    assert "김*늘" not in both
    assert unmasked({"order": "김*늘", "n": 3}, {"김*늘": "김하늘"}) == {"order": "김하늘", "n": 3}


def test_step_arguments_are_stored_masked() -> None:
    masker = Masker.of(["김하늘"])
    stored = masker.args(
        {"customer_name": "홍길동", "note": "김하늘 010-1234-5678", "party": 2, "nested": {"name": "홍길동"}},
    )
    assert stored == {
        "customer_name": "홍*동",
        "note": "김*늘 (연락처 가림)",
        "party": 2,
        "nested": {"name": "홍*동"},
    }


@pytest.mark.parametrize(
    ("reference", "name", "beside", "expected"),
    [
        ("점토 주문", "도자기용 점토 50kg 주문", (), BY_PART_OF_NAME),
        ("플리마켓 조건 확인", "플리마켓 참가 조건 확인", (), BY_PART_OF_NAME),
        ("김*연 님 머그컵 2종 세트", "김서연", ("머그컵 2종 세트",), BY_FULL_NAME),
        ("김*연 님 머그컵 2종 세트", "머그컵 2종 세트", ("김서연",), BY_PART_OF_NAME),
        ("최*우 님 물레 체험", "최민우", ("주말 도자기 클래스",), None),
        ("달나라 점토", "도자기용 점토 50kg 주문", (), None),
        ("예약 문의", "이도윤", ("둘이 참여 가능 여부",), None),
    ],
)
def test_a_reference_of_several_words_names_a_row_only_when_the_row_holds_them_all(
    reference: str, name: str, beside: tuple[str, ...], expected: float | None,
) -> None:
    assert name_confidence(reference, name, beside=beside) == expected


@pytest.mark.parametrize(
    ("words", "left"),
    [
        ("알겠어요. 정*우 님 미니 화병 주문을 받았어요.", "아직 처리하지 않았어요. 알겠어요."),
        ("주문 확인은 완료했는데, 점토 주문은 목록에 없어요.", ""),
        ("네, 토요일 오후 1시로 단체 수업 준비 일정을 잡았어요.", ""),
        ("네, #1043번 주문 확인했어요. 28,000원이에요.", "아직 처리하지 않았어요. 28,000원이에요."),
    ],
)
def test_an_answer_without_an_action_never_says_one_happened(words: str, left: str) -> None:
    assert without_claims(words) == left


def test_an_answer_that_claims_nothing_stays_as_written() -> None:
    assert without_claims("오늘 포장할 주문은 1건이에요.") == "오늘 포장할 주문은 1건이에요."
