"""Only whole-message reactions skip the model; requests and questions never do."""

import pytest

from prompts import HistoryTurn
from turns import (
    Reaction,
    asks_advice,
    off_topic_reply,
    previous_answer,
    reaction,
    reaction_reply,
    revision_target,
    unresolved_reference,
    without_drafts,
)

DRAFTED = (
    HistoryTurn(role="owner", text="주말 클래스 홍보 글 써줘"),
    HistoryTurn(role="assistant", text="이번 주말 머그컵 클래스에 놀러 오세요."),
)
OFFERED = (*DRAFTED, HistoryTurn(role="assistant", text="해시태그도 붙여 드릴까요?"))


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("오 좋은데?", "praise"), ("괜찮네", "praise"), ("와 진짜 맘에 들어요 👍", "praise"),
        ("끝내주네", "praise"), ("딱 좋아", "praise"), ("고마워", "thanks"), ("오 좋네 고마워!", "thanks"),
        ("감사합니다~", "thanks"), ("ㅇㅇ", "ack"), ("알겠어", "ack"), ("ㅋㅋㅋ", "ack"),
        ("끝", "closing"), ("수고했어요", "closing"),
        ("좋은데 더 짧게", None), ("오늘 예약 몇 건이야?", None), ("고마워 근데 내일 일정은?", None),
        ("됐어?", None), ("주말 클래스 홍보 글 써줘", None),
    ],
)
def test_reaction_kind(question: str, expected: Reaction | None) -> None:
    assert reaction(question, DRAFTED) == expected


@pytest.mark.parametrize(("question", "expected"), [("좋아", None), ("응", None), ("고마워", "thanks")])
def test_yes_to_an_offer_is_not_a_reaction(question: str, expected: Reaction | None) -> None:
    assert reaction(question, OFFERED) == expected


def test_reply_after_writing_points_at_the_next_step() -> None:
    assert "복사" in reaction_reply("praise", DRAFTED)
    assert "복사" not in reaction_reply("praise", ())


@pytest.mark.parametrize(
    ("question", "revises"),
    [("좀 더 짧게", True), ("다시 써줘", True), ("해시태그 빼줘", True), ("내일 일정 다시 알려줘", False)],
)
def test_revision_target(question: str, *, revises: bool) -> None:
    assert (revision_target(question, DRAFTED) is not None) is revises
    assert revision_target(question, ()) is None


def test_previous_answer_skips_a_trailing_offer() -> None:
    assert previous_answer(OFFERED) == DRAFTED[1].text
    assert previous_answer(()) is None


@pytest.mark.parametrize(
    ("question", "dangling"),
    [
        ("그거 다시", True), ("아까 그 글 짧게", True), ("방금 들어온 주문 확인해줘", False),
        ("그거 다시 언제였지?", False), ("주말 홍보 글 짧게 써줘", False),
    ],
)
def test_unresolved_reference(question: str, *, dangling: bool) -> None:
    assert unresolved_reference(question, ()) is dangling
    assert unresolved_reference(question, DRAFTED) is False


@pytest.mark.parametrize(
    ("question", "advice"),
    [
        ("이번 주말 클래스 어떻게 홍보하면 좋을까?", True), ("가격을 얼마로 하면 좋을지 모르겠어", True),
        ("인스타에 어떻게 올릴까?", True), ("토요일에 하는 게 나을까?", True),
        ("가격 올려도 괜찮을까?", True),
        ("크리스마스 클래스 추천해 줄래?", True), ("손님 늘릴 방법 있을까?", True),
        ("어떻게 홍보하면 좋을지 글로 써 줘", False), ("홍보 글 작성해줘, 어떻게 하면 좋을까", False),
        ("괜찮을까 싶은 문구로 공지 만들어 줘", False), ("주말 클래스 홍보 글 써줘", False),
        ("오늘 예약 몇 건이야?", False), ("포장 완료 처리해줘", False),
    ],
)
def test_asks_advice(question: str, *, advice: bool) -> None:
    assert asks_advice(question) is advice


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("오늘 날씨 어때?", "날씨"), ("내일 비 와?", "날씨"), ("요즘 뉴스 뭐 있어?", "뉴스"),
        ("삼성 주가 얼마야?", "시세"), ("날씨 추우면 주말 클래스 예약 줄까?", None),
        ("수업 준비와 정리 순서 알려줘", None), ("점심 뭐 먹지?", None),
    ],
)
def test_off_topic_reply_names_what_it_cannot_know(question: str, topic: str | None) -> None:
    reply = off_topic_reply(question)
    if topic is None:
        assert reply is None
    else:
        assert reply == f"{topic}는 제가 알 수 없어요. 대신 오늘 수업이나 발송 일정은 바로 알려 드릴게요."


def test_without_drafts_keeps_questions_and_plain_answers() -> None:
    answered = (
        HistoryTurn(role="owner", text="오늘 예약 몇 건?"), HistoryTurn(role="assistant", text="2건이에요."),
    )
    assert without_drafts([*answered, *OFFERED]) == [*answered, DRAFTED[0]]
