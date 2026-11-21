"""Model output cleanup and the reply-draft safety check are pure functions."""

import pytest

from ai_output import normalize, reply_problems

POLICY = "예약은 예약금 입금 확인 후 확정됩니다. 수업 2일 전까지 전액 환불이 가능합니다."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("```\n김 님, 감사해요.\n```", "김 님, 감사해요."),
        ("답변: 김 님, 감사해요.", "김 님, 감사해요."),
        ("초안 : \u201c김 님, 감사해요.\u201d", "김 님, 감사해요."),
        ('"김 님, 감사해요."', "김 님, 감사해요."),
        ('"좋아요" 하고 "싫어요"', '"좋아요" 하고 "싫어요"'),
        ("## 오늘 할 일\n**두 건**이에요.", "오늘 할 일\n두 건이에요."),
        ("보낼 택배는 '**머그컵 세트**'예요.", "보낼 택배는 머그컵 세트예요."),
        ("연락처: ***-****-****", "연락처: ***-****-****"),
        ("두 건이에요.\n- 점토 주문\n* 키링 결과", "두 건이에요.\n· 점토 주문\n· 키링 결과"),
        ("두 건이에요. 도움이 되셨길 바랍니다.", "두 건이에요."),
        ("두 건이에요.\n\n도움이 되었으면 좋겠어요!", "두 건이에요."),
        ("첫 줄\n\n\n\n둘째 줄", "첫 줄\n\n둘째 줄"),
        ("#도자기 #원데이", "#도자기 #원데이"),
        ("  \n```\n```\n ", ""),
    ],
)
def test_normalize_strips_forbidden_wrappers(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "claim",
    [
        "예약이 확정되었습니다.",
        "예약 확정해 드릴게요.",
        "환불해 드리겠습니다.",
        "결제가 완료되었어요.",
        "할인해 드릴게요.",
    ],
)
def test_unsupported_commitment_is_refused(claim: str) -> None:
    assert len(reply_problems(f"김 님, 감사해요. {claim}", POLICY, "")) == 1


def test_commitment_written_in_the_basis_is_allowed() -> None:
    basis = f"{POLICY}\n입금 확인 완료, 예약이 확정되었습니다."
    assert reply_problems("김 님, 예약이 확정되었습니다.", basis, "") == []


def test_question_does_not_license_a_commitment() -> None:
    text = "김 님, 예약이 확정되었습니다."
    assert reply_problems(text, POLICY, "예약이 확정되었나요?") != []


def test_amounts_and_dates_must_come_from_basis_or_question() -> None:
    basis = "예약금 20000원"
    assert reply_problems("예약금은 20,000원이에요.", basis, "") == []
    assert len(reply_problems("예약금은 30,000원이에요.", basis, "")) == 1
    assert reply_problems("11월 21일 수업이에요.", basis, "11월 21일 자리 있나요?") == []
    assert len(reply_problems("11월 22일에 도착해요.", basis, "")) == 1


def test_empty_reply_is_refused() -> None:
    assert reply_problems("", POLICY, "") != []
