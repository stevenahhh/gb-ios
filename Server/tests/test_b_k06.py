"""Cancellation and no-show card: fixed refund math, guarded model wording, and reversible decisions."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from b_k06_logic import (
    ExtractedPolicy,
    LateRule,
    Payment,
    ReplyFacts,
    Rule,
    checked_policy,
    compute,
    date_of,
    edited_characters,
    fallback_reply,
    parse_policy,
    reply_check,
    without_identity,
)
from b_k06_seed import apply
from common import current_time
from display import SEOUL
from main import app
from providers import ChatMessage, Sampling
from tests.conftest import NOW, downgrade, upgrade

pytestmark = pytest.mark.anyio
type Body = dict[str, JsonValue]
TODAY = NOW.date()
CLASS_AT = datetime(2026, 11, 22, 10, 0, tzinfo=SEOUL)
TIERS = [
    Rule(days_before=3, refund_percent=100), Rule(days_before=2, refund_percent=50),
    Rule(days_before=1), Rule(days_before=0, refund_percent=0),
]
TEXT = "3일 전까지 전액 환불, 2일 전 50%, 당일 환불 불가. 15분 넘게 늦으면 노쇼 처리"
HAYUN = "booking-k06-hayun"
SICK = "김하윤이에요 010-1234-5678. 오늘 아이가 아파서 못 갈 것 같은데 환불되나요?"


@dataclass(slots=True)
class FakeChat:
    """Answers in order; an exhausted list fails like an unreachable model."""

    replies: Sequence[str]
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def __call__(self, messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        self.calls.append(list(messages))
        if len(self.calls) > len(self.replies):
            raise HTTPException(502, "upstream service failed")
        return self.replies[len(self.calls) - 1]


def fake_chat(monkeypatch: pytest.MonkeyPatch, *replies: str) -> FakeChat:
    fake = FakeChat(replies)
    monkeypatch.setattr("ai.chat", fake)
    return fake


@pytest.fixture
async def examples(database: AsyncEngine) -> AsyncEngine:
    async with database.begin() as connection:
        _ = await apply(connection, TODAY)
    return database


@pytest.mark.parametrize(
    ("days", "refund"), [(5, 20000), (3, 20000), (2, 10000), (1, None), (0, 0), (-1, None)],
)
def test_refund_uses_the_first_tier_reached(days: int, refund: int | None) -> None:
    at = CLASS_AT - timedelta(days=days)
    assert compute(TIERS, CLASS_AT, at, Payment(20000, None)).refund == refund


def test_days_are_calendar_days_in_workshop_time() -> None:
    late_evening = datetime(2026, 11, 19, 23, 59, tzinfo=SEOUL)
    assert compute(TIERS, CLASS_AT, late_evening, Payment(20000, None)).days_left == 3


@pytest.mark.parametrize(("material", "refund"), [(None, None), (3000, 7000), (90000, 0)])
def test_material_is_deducted_only_when_its_cost_is_known(material: int | None, refund: int | None) -> None:
    rules = [Rule(days_before=0, refund_percent=50, deduct_material=True)]
    assert compute(rules, CLASS_AT, CLASS_AT, Payment(20000, material)).refund == refund


def test_rule_text_is_read_without_a_model() -> None:
    source = f"{TEXT}. 하루 전 취소는 상황 따라"
    policy = checked_policy(parse_policy(source), source)
    assert [(rule.days_before, rule.refund_percent) for rule in policy.rules] == [
        (3, 100), (2, 50), (1, None), (0, 0),
    ]
    assert policy.late == LateRule(late_minutes=15, note="15분 넘게 늦으면 노쇼 처리")
    assert policy.unread == ("하루 전 취소는 상황 따라",)


def test_rows_that_do_not_quote_the_source_are_unread() -> None:
    raw = ExtractedPolicy(
        rules=[
            Rule(days_before=3, refund_percent=100, note="3일 전까지 전액 환불"),
            Rule(days_before=7, refund_percent=100, note="7일 전 전액"),
            Rule(days_before=3, refund_percent=0, note="당일 환불 불가"),
        ],
        late=LateRule(late_minutes=30, note="30분 지나면 노쇼"),
    )
    policy = checked_policy(raw, TEXT)
    assert [(rule.days_before, rule.refund_percent) for rule in policy.rules] == [
        (7, None), (3, None), (2, 50), (0, None),
    ]
    assert policy.late == LateRule(late_minutes=15, note="15분 넘게 늦으면 노쇼 처리")


@pytest.mark.parametrize(
    ("message", "day"),
    [
        ("오늘 못 가요", TODAY), ("내일 취소요", TODAY + timedelta(days=1)),
        ("이번 주 토요일", datetime(2026, 11, 21, tzinfo=SEOUL).date()),
        ("다음 주 월요일", datetime(2026, 11, 23, tzinfo=SEOUL).date()),
        ("12월 1일 취소", datetime(2026, 12, 1, tzinfo=SEOUL).date()), ("13월 1일", None),
        ("환불되나요", None),
    ],
)
def test_message_dates(message: str, day: object) -> None:
    assert date_of(message, TODAY) == day


def test_identity_is_masked_before_the_model() -> None:
    masked = without_identity(SICK, ["김하윤"])
    assert "하윤" not in masked
    assert "1234" not in masked


def facts(**changes: object) -> ReplyFacts:
    values: dict[str, object] = {
        "customer": "김하윤", "class_title": "머그컵", "class_when": "11월 22일 일요일 10:00",
        "decision": "by_rule", "reason": "", "paid": 20000, "refund": 10000, "days": 2, "version": 3,
        "noticed": TODAY,
    }
    return ReplyFacts(**{**values, **changes})


@pytest.mark.parametrize(
    "reply",
    [
        "손님A 님, 15,000원을 환불해 드릴게요.", "손님A 님, 2만 원을 돌려드릴게요. 10,000원이에요.",
        "손님A 님, 법적으로 10,000원이에요.", "10,000원을 돌려드릴게요.", "손님A 님, 돌려드릴게요.",
        "손님A 님, 10,000원을 돌려드리고 다음 회차로 옮겨 드릴게요.",
    ],
)
def test_a_reply_that_leaves_the_facts_is_refused(reply: str) -> None:
    assert reply_check(reply, facts()) != []


@pytest.mark.parametrize("decision", ["by_rule", "carry_over", "full_refund", "custom"])
def test_the_fixed_reply_passes_its_own_checks(decision: str) -> None:
    amount = {"by_rule": 10000, "carry_over": 0, "full_refund": 20000, "custom": 5000}[decision]
    values = facts(decision=decision, refund=amount, customer="손님A")
    assert reply_check(fallback_reply(values), values) == []


def test_edited_characters_ignores_the_shared_ends() -> None:
    assert edited_characters("안녕하세요 님", "안녕하세요 님") == 0
    assert edited_characters("가나다라", "가마다라") == 1


async def test_extract_falls_back_to_rules_when_the_model_breaks_the_format(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "표입니다", "{}x")
    body = (await client.post("/policy/extract", json={"text": TEXT})).json()
    assert len(fake.calls) == 2
    assert body["source"] == "rules"
    assert [rule["refundPercent"] for rule in body["rules"]] == [100, 50, 0]
    assert body["late"]["lateMinutes"] == 15


async def test_extract_uses_valid_model_output(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    rule = {"days_before": 2, "refund_percent": 50, "note": "2일 전 50%"}
    _ = fake_chat(monkeypatch, json.dumps({"rules": [rule], "unread": ["하루 전 취소"]}))
    body = (await client.post("/policy/extract", json={"text": TEXT})).json()
    assert body["source"] == "model"
    assert [(row["daysBefore"], row["refundPercent"]) for row in body["rules"]] == [
        (3, 100), (2, 50), (1, None), (0, 0),
    ]


@pytest.mark.postgres
async def test_versions_grow_and_never_change(database: AsyncEngine, client: AsyncClient) -> None:
    empty = await client.get("/policy/versions")
    assert (empty.status_code, empty.json()) == (200, [])
    first: Body = {"rules": [{"daysBefore": 0, "refundPercent": 0}], "sourceText": "당일 환불 불가"}
    second: Body = {"rules": [{"daysBefore": 0, "refundPercent": 50}], "sourceText": "당일 50%"}
    assert (await client.post("/policy/versions", json=first)).json()["version"] == 1
    assert (await client.post("/policy/versions", json=second)).json()["version"] == 2
    listed = (await client.get("/policy/versions")).json()
    assert [(row["version"], row["change"]) for row in listed] == [(2, "당일 50% 환불"), (1, "첫 규정")]
    assert (await client.get("/policy/versions/1")).json()["labels"] == ["당일 환불 없음"]
    duplicate: Body = {"rules": [{"daysBefore": 0}, {"daysBefore": 0}], "sourceText": "x"}
    assert (await client.post("/policy/versions", json=duplicate)).status_code == 422


@pytest.mark.postgres
async def test_intake_finds_one_booking_and_hides_identity_from_the_model(
    examples: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, json.dumps({"date": None, "kind": "cancel"}))
    body = (await client.post("/cancellations/intake", json={"message": SICK})).json()
    assert (body["kind"], body["reasonCategory"]) == ("cancel", "health")
    assert [item["bookingId"] for item in body["candidates"]] == [HAYUN]
    assert body["recent"] == []
    sent = fake.calls[0][-1].content
    assert "하윤" not in sent
    assert "1234" not in sent
    async with examples.connect() as connection:
        stored = await connection.scalar(text(
            "SELECT count(*) FROM cancellation_cases c WHERE row_to_json(c)::text LIKE '%못 갈 것%'",
        ))
    assert stored == 0


@pytest.mark.postgres
async def test_intake_without_a_match_lists_recent_bookings(
    examples: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = fake_chat(monkeypatch)
    body = (await client.post("/cancellations/intake", json={"message": "환불되나요"})).json()
    assert body["candidates"] == []
    assert HAYUN in [item["bookingId"] for item in body["recent"]]


async def quoted(client: AsyncClient, booking: str = HAYUN) -> Body:
    return (await client.post(
        "/cancellations/quote", json={"bookingId": booking, "reasonCategory": "health"},
    )).json()


@pytest.mark.postgres
async def test_quote_uses_the_version_told_to_this_customer(
    examples: AsyncEngine, client: AsyncClient,
) -> None:
    newer: Body = {"rules": [{"daysBefore": 0, "refundPercent": 100}], "sourceText": "전액"}
    assert (await client.post("/policy/versions", json=newer)).json()["version"] == 4
    body = await quoted(client)
    assert (body["policyVersion"], body["noticedAt"]) == (3, "2026-11-08")
    assert (body["daysLeft"], body["paid"], body["refund"], body["warnings"]) == (0, 20000, 0, [])
    reasons = [item["reason"] for item in body["precedents"]]
    assert reasons == ["예시: 아이가 아파서 1회 이월", "예시: 감기로 1회 이월"]
    other = await quoted(client, "booking-k06-small")
    assert (other["policyVersion"], other["warnings"]) == (4, ["no_notice"])


@pytest.mark.postgres
async def test_quote_without_rules_warns(database: AsyncEngine, client: AsyncClient) -> None:
    body = await quoted(client, "booking-yuna")
    assert (body["refund"], body["warnings"]) == (None, ["no_policy", "naver_booking"])


async def decide(client: AsyncClient, **body: JsonValue) -> tuple[int, Body]:
    response = await client.post(
        f"/cancellations/{HAYUN}/decision", json={"expectedRevision": 0, **body},
    )
    return response.status_code, response.json()


@pytest.mark.postgres
async def test_a_decision_is_recorded_drafted_approved_and_undone(
    examples: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = "손님A 님, 이번에는 다음 회차로 한 번 옮겨 드릴게요. 편한 날짜를 알려 주세요."
    _ = fake_chat(monkeypatch, good)
    assert (await decide(client, decision="carry_over"))[0] == 422
    status, body = await decide(client, decision="carry_over", reason="아이가 아픔", reasonCategory="health")
    assert (status, body["seatOpened"], body["refund"]) == (200, True, 0)
    assert (await client.get("/k06/cards")).json()["refill"][0]["sessionId"] == "session-k06-today"
    case = body["caseId"]
    draft = (await client.post(f"/cancellations/cases/{case}/draft")).json()
    assert draft == {"draft": good.replace("손님A", "김하윤"), "source": "model"}
    edited = {"draft": f"{draft['draft']} 감사해요."}
    approved = await client.post(f"/cancellations/cases/{case}/approve", json=edited)
    assert approved.json()["editChars"] == len(" 감사해요.")
    assert (await client.post(f"/cancellations/cases/{case}/approve", json=edited)).status_code == 409
    assert (await client.post(f"/cancellations/cases/{case}/undo")).json() == {"removed": 1}
    assert (await quoted(client))["revision"] == 2
    assert (await client.get("/k06/cards")).json()["refill"] == []


@pytest.mark.postgres
async def test_an_unsafe_model_reply_twice_leaves_the_fixed_wording(
    examples: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_chat(monkeypatch, "손님A 님, 20,000원을 환불해 드릴게요.", "손님A 님, 전액 드릴게요.")
    _, body = await decide(client, decision="by_rule")
    draft = (await client.post(f"/cancellations/cases/{body['caseId']}/draft")).json()
    assert len(fake.calls) == 2
    assert draft["source"] == "rules"
    assert draft["draft"] == body["draft"]
    assert draft["draft"].startswith("김하윤 님, 연락 주셔서 감사해요. 11월 8일에 안내드린 규정 3판에 따라")


@pytest.mark.postgres
async def test_custom_refund_is_bounded_and_stale_writes_are_refused(
    examples: AsyncEngine, client: AsyncClient,
) -> None:
    assert (await decide(client, decision="custom", reason="x", refundWon=20001))[0] == 422
    assert (await decide(client, decision="custom", reason="x"))[0] == 422
    assert (await decide(client, decision="by_rule", expectedRevision=9))[0] == 409
    assert (await decide(client, decision="custom", reason="x", refundWon=5000))[1]["refund"] == 5000
    assert (await decide(client, decision="by_rule", expectedRevision=1))[0] == 409


@pytest.mark.postgres
async def test_undo_is_refused_when_the_seat_was_filled(examples: AsyncEngine, client: AsyncClient) -> None:
    _, body = await decide(client, decision="by_rule")
    taken: Body = {"sessionId": "session-k06-today", "customerName": "새 손님", "partySize": 4}
    assert (await client.post("/bookings", json=taken)).status_code == 201
    assert (await client.post(f"/cancellations/cases/{body['caseId']}/undo")).status_code == 409


@pytest.mark.postgres
async def test_late_card_appears_after_the_grace_and_attendance_is_reversible(
    examples: AsyncEngine, client: AsyncClient,
) -> None:
    early = (await client.get("/k06/cards")).json()
    assert early["late"] == []
    assert early["reminders"][-1]["fireAt"].startswith("2026-11-2")
    assert (await client.post(f"/bookings/{HAYUN}/attendance", json={"status": "no_show"})).status_code == 409
    app.dependency_overrides[current_time] = lambda: NOW.replace(hour=15, minute=15)
    late = (await client.get("/k06/cards")).json()["late"]
    assert HAYUN in [card["bookingId"] for card in late]
    assert next(card for card in late if card["bookingId"] == HAYUN)["ended"] is False
    app.dependency_overrides[current_time] = lambda: NOW.replace(hour=23, minute=0)
    ended = (await client.get("/k06/cards")).json()["late"]
    assert next(card for card in ended if card["bookingId"] == HAYUN)["ended"] is True
    app.dependency_overrides[current_time] = lambda: NOW.replace(hour=15, minute=15)
    absent = (await client.post(f"/bookings/{HAYUN}/attendance", json={"status": "no_show"})).json()
    assert "15분 넘게 늦으면 노쇼" in absent["draft"]
    assert (await client.post(f"/bookings/{HAYUN}/attendance", json={"status": "arrived"})).status_code == 409
    assert (await client.post(f"/bookings/{HAYUN}/undo-attendance")).status_code == 200
    kinds = [row["kind"] for row in (await client.get("/cancellations/cases")).json()]
    assert "no_show" not in kinds
    arrived = (await client.post(f"/bookings/{HAYUN}/attendance", json={"status": "arrived"})).json()
    assert arrived["attendedAt"].startswith("2026-11-18T15:15")
    assert HAYUN not in [card["bookingId"] for card in (await client.get("/k06/cards")).json()["late"]]


@pytest.mark.postgres
async def test_refill_lists_requests_before_make_up_classes(
    examples: AsyncEngine, client: AsyncClient,
) -> None:
    path = "/class-sessions/session-k06-today"
    added: Body = {"customerName": "오준호", "phone": "010-5520-1187", "source": "waitlist"}
    detail = (await client.post(f"{path}/waitlist", json=added)).json()
    assert [(item["name"], item["source"]) for item in detail["targets"]] == [
        ("김하늘", "waitlist"), ("오준호", "waitlist"), ("박서연", "makeup"),
    ]
    entry = detail["targets"][1]["entryId"]
    assert (await client.delete(f"{path}/waitlist/{entry}")).json() == {"removed": 1}
    body = (await client.get(f"{path}/refill")).json()
    assert (body["openSeats"], body["startsInMinutes"], len(body["targets"])) == (3, 240, 2)


@pytest.mark.postgres
async def test_under_min_card_shows_from_the_evening_before_and_merges(
    examples: AsyncEngine, client: AsyncClient,
) -> None:
    assert (await client.get("/class-sessions/under-min")).json() == []
    app.dependency_overrides[current_time] = lambda: NOW.replace(hour=18)
    [card] = (await client.get("/class-sessions/under-min")).json()
    assert (card["booked"], card["minSeats"], card["materialWon"]) == (1, 2, 8000)
    assert [item["sessionId"] for item in card["mergeCandidates"]] == ["session-k06-other"]
    path = "/class-sessions/session-k06-small/under-min-decision"
    full: Body = {"decision": "merge", "mergeInto": "session-wheel", "expectedRevision": 0}
    assert (await client.post(path, json=full)).status_code == 409
    merge: Body = {"decision": "merge", "mergeInto": "session-k06-other", "expectedRevision": 0}
    [draft] = (await client.post(path, json=merge)).json()["drafts"]
    assert "11월 21일 토요일 14:00 수업과 합치려고 해요" in draft["draft"]
    moved = (await client.get("/class-sessions/session-k06-other/k06")).json()
    assert moved["booked"] == 2
    assert (await client.get("/class-sessions/under-min")).json() == []


@pytest.mark.postgres
async def test_cancelling_a_class_words_a_full_refund(examples: AsyncEngine, client: AsyncClient) -> None:
    path = "/class-sessions/session-k06-small/under-min-decision"
    body: Body = {"decision": "cancel", "expectedRevision": 0}
    [draft] = (await client.post(path, json=body)).json()["drafts"]
    assert "예약금 20,000원은 모두 돌려드릴게요" in draft["draft"]
    assert (await client.post(path, json=body)).status_code == 409


@pytest.mark.postgres
async def test_plan_and_notice_are_saved_and_records_can_be_deleted(
    examples: AsyncEngine, client: AsyncClient,
) -> None:
    plan: Body = {"minSeats": 3, "materialOrderDeadline": "2026-11-20T10:00:00+09:00", "materialWon": None}
    saved = (await client.put("/class-sessions/session-k06-other/plan", json=plan)).json()
    assert (saved["minSeats"], saved["materialOrderDeadline"]) == (3, "2026-11-20T10:00:00+09:00")
    notice = await client.post("/policy/notices", json={"bookingId": "booking-k06-small"})
    assert notice.json()["version"] == 3
    assert (await client.post("/policy/notices", json={"bookingId": "none"})).status_code == 404
    _ = await decide(client, decision="by_rule")
    assert (await client.delete(f"/bookings/{HAYUN}/cancellation-cases")).json() == {"removed": 1}


@pytest.mark.postgres
async def test_migration_adds_and_removes_only_its_own_tables(empty_database: AsyncEngine) -> None:
    async def tables() -> set[str]:
        async with empty_database.connect() as connection:
            rows = await connection.scalars(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()",
            ))
            return set(rows)

    await upgrade(empty_database, "0005")
    before = await tables()
    await upgrade(empty_database, "0005_k06")
    assert await tables() - before == {
        "policy_versions", "policy_notices", "cancellation_cases", "waitlist_entries", "booking_marks",
        "session_plans",
    }
    await downgrade(empty_database, "0005")
    assert await tables() == before


@pytest.mark.postgres
async def test_an_unread_refund_clause_blocks_the_by_rule_amount(
    examples: AsyncEngine, client: AsyncClient,
) -> None:
    line = "하루 전은 상황에 따라 환불"
    body: Body = {
        "rules": [{"daysBefore": 0, "refundPercent": 0}], "unread": [line, "당일 변경 불가"],
        "sourceText": "당일 환불 불가, 하루 전은 상황에 따라 환불, 당일 변경 불가",
    }
    assert (await client.post("/policy/versions", json=body)).json()["unread"] == [line, "당일 변경 불가"]
    ask: Body = {"bookingId": "booking-k06-small"}
    quote = (await client.post("/cancellations/quote", json=ask)).json()
    assert (quote["refund"], quote["unread"]) == (None, [line])
    assert "unread_rule" in quote["warnings"]
    decision: Body = {"decision": "by_rule", "expectedRevision": 0}
    assert (await client.post("/cancellations/booking-k06-small/decision", json=decision)).status_code == 422
    resolved = {**body, "unread": ["당일 변경 불가"]}
    assert (await client.post("/policy/versions", json=resolved)).status_code == 201
    quote = (await client.post("/cancellations/quote", json=ask)).json()
    assert (quote["unread"], "unread_rule" in quote["warnings"]) == ([], False)
