"""Only whole-message reactions skip the model; requests and questions never do."""

import pytest

from prompts import HistoryTurn
from turns import Reaction, reaction, reaction_reply, revision_target

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
