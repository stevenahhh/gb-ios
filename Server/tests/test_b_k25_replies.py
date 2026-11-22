"""A grounded reply is written from the ledger, checked against it, and locked until it agrees."""

from datetime import timedelta
from typing import Final

import pytest
from httpx2 import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from common import current_time
from main import app
from tests.b_k25_support import (
    GROUNDED,
    ONCE_CONTROL,
    ScriptedModel,
    add_control_row,
    add_inquiry,
    scripted,
)
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
PLAIN_REPLY: Final = "이서준 님, 문의 주셔서 감사해요. 확인해서 다시 알려드릴게요."
WRONG_PLAIN_REPLY: Final = "이서준 님, 문의 주셔서 감사해요. 예약금은 30,000원이에요."
WRONG_SEATS: Final = "○○ 님, 토요일에 네 자리 가능해요."
WRONG_SEATS_CLAIMS: Final = '[{"kind":"seats","text":"네 자리","value":"4"}]'
REASON: Final = "손님과 따로 정했어요"
DATED_DRAFT: Final = "○○ 님, 11월 21일 토요일에 세 자리 남았어요. 예약금은 25,000원이에요."
DATED_CLAIMS: Final = (
    '[{"kind":"date","text":"11월 21일","value":"11-21"},'
    '{"kind":"seats","text":"세 자리 남았어요","value":"3"},'
    '{"kind":"deposit","text":"예약금은 25,000원","value":"25000"}]'
)
WRONG_DRAFT: Final = "○○ 님, 토요일에 네 자리 가능해요. 예약금은 30,000원이에요."
WRONG_CLAIMS: Final = (
    '[{"kind":"seats","text":"네 자리","value":"4"},'
    '{"kind":"deposit","text":"예약금은 30,000원","value":"30000"}]'
)
RIGHT_DRAFT: Final = "○○ 님, 토요일에 세 자리 남았어요. 예약금은 25,000원이에요."
RIGHT_CLAIMS: Final = (
    '[{"kind":"seats","text":"세 자리 남았어요","value":"3"},'
    '{"kind":"deposit","text":"예약금은 25,000원","value":"25000"}]'
)

UNUSABLE_CLAIMS: Final = "죄송하지만 JSON을 만들 수 없어요."


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> ScriptedModel:
    return scripted(monkeypatch)


async def saved(client: AsyncClient, inquiry_id: str) -> None:
    edited = await client.patch(f"/inquiries/{inquiry_id}/draft", json={
        "draft": "수정한 초안", "expectedRevision": 0,
    })
    assert edited.status_code == 200


async def approve(client: AsyncClient, inquiry_id: str, draft: str, reason: str | None = None) -> Response:
    """Approve a reply at its first revision, with a reason when it is locked."""
    return await client.post(f"/grounded-replies/{inquiry_id}/decision", json={
        "decision": "approve", "draft": draft, "expectedRevision": 0, "overrideReason": reason,
    })


async def kept(database: AsyncEngine) -> list[tuple[str, str, str | None]]:
    """Read what is stored about the checked replies."""
    async with database.connect() as connection:
        rows = await connection.execute(
            text("SELECT ab_arm, lock_state, override_reason FROM inquiry_grounding"),
        )
        return [(row.ab_arm, row.lock_state, row.override_reason) for row in rows]


async def steps(database: AsyncEngine) -> list[tuple[str, str]]:
    """Read the measured steps in order."""
    async with database.connect() as connection:
        rows = await connection.execute(text("SELECT arm, kind FROM grounded_events ORDER BY id"))
        return [(row.arm, row.kind) for row in rows]


@pytest.mark.parametrize("has_control_row", [False, True])
async def test_the_inquiry_that_hashed_to_control_is_grounded_checked_and_locked(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel, *, has_control_row: bool,
) -> None:
    await add_inquiry(database, ONCE_CONTROL)
    if has_control_row:
        await add_control_row(database, ONCE_CONTROL, PLAIN_REPLY)
    model.drafts, model.claims = [WRONG_SEATS], WRONG_SEATS_CLAIMS
    body = (await client.post(f"/grounded-replies/{ONCE_CONTROL}/draft")).json()
    assert (body["arm"], body["lock"], body["mismatchCount"]) == ("grounded", "locked", 1)
    assert model.routes == 1
    assert "이서준" not in "\n".join(model.prompts)
    assert (await approve(client, ONCE_CONTROL, body["draft"])).status_code == 409
    passed = await approve(client, ONCE_CONTROL, body["draft"], REASON)
    assert passed.json()["status"] == "approved"
    assert await kept(database) == [("grounded", "overridden", REASON)]
    assert await steps(database) == [
        ("grounded", "draft"), ("grounded", "override"), ("grounded", "approved"),
    ]


async def test_a_row_stored_as_control_with_an_old_plain_draft_is_checked_and_locked(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, ONCE_CONTROL, WRONG_PLAIN_REPLY)
    await add_control_row(database, ONCE_CONTROL, WRONG_PLAIN_REPLY)
    state = (await client.get(f"/grounded-replies/{ONCE_CONTROL}")).json()
    assert (state["arm"], state["lock"], state["mismatchCount"]) == ("grounded", "locked", 1)
    text_now = {"draft": WRONG_PLAIN_REPLY}
    verified = (await client.post(f"/grounded-replies/{ONCE_CONTROL}/verify", json=text_now)).json()
    assert (verified["lock"], verified["checkedKinds"]) == ("locked", ["예약금"])
    assert (await approve(client, ONCE_CONTROL, WRONG_PLAIN_REPLY)).status_code == 409
    assert (await approve(client, ONCE_CONTROL, WRONG_PLAIN_REPLY, REASON)).status_code == 200
    assert await kept(database) == [("grounded", "overridden", REASON)]


async def test_a_reply_nobody_drafted_here_is_checked_locked_and_remembered(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, ONCE_CONTROL, WRONG_PLAIN_REPLY)
    state = (await client.get(f"/grounded-replies/{ONCE_CONTROL}")).json()
    assert (state["arm"], state["lock"], state["mismatchCount"]) == ("grounded", "locked", 1)
    assert (await approve(client, ONCE_CONTROL, WRONG_PLAIN_REPLY)).status_code == 409
    assert await kept(database) == []
    assert (await approve(client, ONCE_CONTROL, WRONG_PLAIN_REPLY, REASON)).status_code == 200
    assert await kept(database) == [("grounded", "overridden", REASON)]
    assert await steps(database) == [("grounded", "override"), ("grounded", "approved")]


async def write(client: AsyncClient, model: ScriptedModel, draft: str, claims: str) -> dict[str, object]:
    """Write one scripted draft and return its check."""
    model.drafts, model.claims = [draft], claims
    return (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()


async def read_state(client: AsyncClient, inquiry_id: str = GROUNDED) -> dict[str, object]:
    """Read what the inquiry screen shows."""
    return (await client.get(f"/grounded-replies/{inquiry_id}")).json()


async def raise_deposit(database: AsyncEngine) -> None:
    """Change the ledger under a reply that was already completed."""
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE class_sessions SET deposit_won = 30000"))


def shown(body: dict[str, object]) -> list[object]:
    """Pick the check of a draft or of a state."""
    return [body[key] for key in ("arm", "lock", "mismatchCount", "checkedKinds", "claims")]


async def test_a_reply_completed_as_clear_still_reads_clear_after_its_day(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    written = await write(client, model, DATED_DRAFT, DATED_CLAIMS)
    assert (written["lock"], written["mismatchCount"]) == ("clear", 0)
    assert (await approve(client, GROUNDED, str(written["draft"]))).status_code == 200
    redrafted = await write(client, model, WRONG_DRAFT, WRONG_CLAIMS)
    assert redrafted["lock"] == "locked"
    app.dependency_overrides[current_time] = lambda: NOW + timedelta(days=5)
    assert shown(await read_state(client)) == shown(written)


async def test_a_reply_completed_with_a_reason_still_reads_locked_with_it(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    written = await write(client, model, WRONG_DRAFT, WRONG_CLAIMS)
    assert (written["lock"], written["mismatchCount"]) == ("locked", 2)
    assert (await approve(client, GROUNDED, str(written["draft"]), REASON)).status_code == 200
    await raise_deposit(database)
    state = await read_state(client)
    assert (shown(state), state["overrideReason"]) == (shown(written), REASON)


@pytest.mark.parametrize("has_control_row", [False, True])
async def test_a_completed_reply_nobody_approved_here_is_unchecked(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel, *, has_control_row: bool,
) -> None:
    await add_inquiry(database, ONCE_CONTROL, WRONG_PLAIN_REPLY)
    if has_control_row:
        await add_control_row(database, ONCE_CONTROL, WRONG_PLAIN_REPLY)
    done = await client.post(f"/inquiries/{ONCE_CONTROL}/decision", json={
        "decision": "approve", "draft": WRONG_PLAIN_REPLY, "expectedRevision": 0,
    })
    assert done.status_code == 200
    state = await read_state(client, ONCE_CONTROL)
    assert (shown(state), state["overrideReason"]) == (["grounded", "unchecked", 0, [], []], None)


async def test_editing_a_completed_reply_is_checked_again(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    written = await write(client, model, RIGHT_DRAFT, RIGHT_CLAIMS)
    draft = str(written["draft"])
    assert (await approve(client, GROUNDED, draft)).status_code == 200
    await raise_deposit(database)
    assert shown(await read_state(client)) == shown(written)
    decision = {"decision": "approve", "expectedRevision": 1}
    for checked in (draft, f"{draft} 편하게 오세요."):
        verified = await client.post(f"/grounded-replies/{GROUNDED}/verify", json={"draft": checked})
        assert verified.json()["lock"] == "locked"
        again = {**decision, "draft": checked}
        refused = await client.post(f"/grounded-replies/{GROUNDED}/decision", json=again)
        assert refused.status_code == 409
    edited = {"draft": f"{draft} 편하게 오세요.", "expectedRevision": 1}
    assert (await client.patch(f"/inquiries/{GROUNDED}/draft", json=edited)).status_code == 200
    state = await read_state(client)
    assert (state["lock"], state["mismatchCount"]) == ("locked", 1)


async def test_an_approval_without_a_recorded_text_is_checked_again(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    written = await write(client, model, RIGHT_DRAFT, RIGHT_CLAIMS)
    assert (await approve(client, GROUNDED, str(written["draft"]))).status_code == 200
    async with database.begin() as connection:
        _ = await connection.execute(text("UPDATE grounded_events SET data = data - 'digest' - 'claims'"))
    await raise_deposit(database)
    assert (await read_state(client))["lock"] == "locked"


async def test_a_blank_reply_is_grounded_and_has_nothing_to_check(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, ONCE_CONTROL)
    state = (await client.get(f"/grounded-replies/{ONCE_CONTROL}")).json()
    assert (state["arm"], state["lock"], state["checkedKinds"]) == ("grounded", "clear", [])


async def test_metrics_have_one_entry_without_the_steps_of_unchecked_drafts(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, ONCE_CONTROL)
    async with database.begin() as connection:
        _ = await connection.execute(
            text("INSERT INTO grounded_events (inquiry_id, arm, kind) VALUES (:id, 'control', 'draft')"),
            {"id": ONCE_CONTROL},
        )
    report = (await client.get("/grounded-replies/metrics?start=2020-01-01&end=2099-12-31")).json()
    assert [(row["arm"], row["drafts"], row["deferralRate"]) for row in report] == [("grounded", 0, None)]


async def test_grounded_draft_hides_the_customer_and_locks_wrong_numbers(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts, model.claims = [WRONG_DRAFT], WRONG_CLAIMS
    response = await client.post(f"/grounded-replies/{GROUNDED}/draft")
    body = response.json()
    assert response.status_code == 200
    assert (body["arm"], body["lock"], body["mismatchCount"]) == ("grounded", "locked", 2)
    assert body["draft"].startswith("이서준 님, 토요일에 네 자리")
    seats = next(claim for claim in body["claims"] if claim["kind"] == "seats")
    assert (seats["status"], seats["ledgerValue"]) == ("mismatched", "11월 21일 토요일 10:00 3자리")
    prompt = "\n".join(model.prompts)
    assert "이서준" not in prompt
    assert "010-1234-5678" not in prompt
    assert "[장부]" in prompt
    assert "남은 자리 3명" in prompt


async def test_the_lock_is_enforced_by_the_server_until_a_reason_is_given(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts, model.claims = [WRONG_DRAFT], WRONG_CLAIMS
    draft = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()["draft"]
    body = {"decision": "approve", "draft": draft, "expectedRevision": 0}
    blocked = await client.post(f"/grounded-replies/{GROUNDED}/decision", json=body)
    assert blocked.status_code == 409
    state = (await client.get(f"/grounded-replies/{GROUNDED}")).json()
    assert state["arm"] == "grounded"
    passed = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        **body, "overrideReason": "장부가 아직 안 맞아요",
    })
    assert passed.status_code == 200
    assert passed.json()["status"] == "approved"
    async with database.connect() as connection:
        kinds = (await connection.execute(
            text("SELECT kind, data->>'override', data->>'reason' FROM grounded_events ORDER BY id"),
        )).all()
        lock = await connection.scalar(text("SELECT lock_state FROM inquiry_grounding"))
    assert [row[0] for row in kinds] == ["draft", "override", "approved"]
    assert kinds[1][2] == "장부가 아직 안 맞아요"
    assert lock == "overridden"


async def test_corrected_text_is_verified_without_the_model(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts, model.claims = [WRONG_DRAFT], WRONG_CLAIMS
    wrong = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()["draft"]
    calls = len(model.prompts)
    corrected = wrong.replace("네 자리", "3자리").replace("30,000원", "25,000원")
    verified = await client.post(f"/grounded-replies/{GROUNDED}/verify", json={"draft": corrected})
    assert verified.json()["lock"] == "clear"
    assert len(model.prompts) == calls
    approved = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        "decision": "approve", "draft": corrected, "expectedRevision": 0,
    })
    assert approved.status_code == 200


async def test_agreeing_numbers_are_clear_and_an_unchanged_approval_is_counted(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts, model.claims = [RIGHT_DRAFT], RIGHT_CLAIMS
    written = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
    assert (written["lock"], written["mismatchCount"]) == ("clear", 0)
    approved = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        "decision": "approve", "draft": written["draft"], "expectedRevision": 0,
    })
    assert approved.status_code == 200
    report = (await client.get("/grounded-replies/metrics")).json()
    assert [row["arm"] for row in report] == ["grounded"]
    grounded = report[0]
    assert (grounded["approvals"], grounded["uneditedApprovals"], grounded["uneditedRate"]) == (1, 1, 1.0)
    assert grounded["drafts"] == 1


async def test_a_stale_revision_or_blank_draft_is_refused(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    await saved(client, GROUNDED)
    stale = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        "decision": "approve", "draft": "답변", "expectedRevision": 0,
    })
    assert stale.status_code == 409
    blank = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        "decision": "approve", "draft": "  ", "expectedRevision": 1,
    })
    assert blank.status_code == 422


async def test_a_known_mismatch_locks_even_when_the_extraction_failed(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts, model.claims = [WRONG_DRAFT], UNUSABLE_CLAIMS
    body = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
    assert (body["lock"], body["mismatchCount"]) == ("locked", 2)
    decision = {"decision": "approve", "draft": body["draft"], "expectedRevision": 0}
    blocked = await client.post(f"/grounded-replies/{GROUNDED}/decision", json=decision)
    assert blocked.status_code == 409
    passed = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        **decision, "overrideReason": "손님과 따로 정했어요",
    })
    assert passed.status_code == 200


async def test_extraction_failure_without_a_mismatch_stays_open_and_unchecked(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts, model.claims = [RIGHT_DRAFT], UNUSABLE_CLAIMS
    body = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
    assert (body["lock"], body["mismatchCount"]) == ("unchecked", 0)
    approved = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        "decision": "approve", "draft": body["draft"], "expectedRevision": 0,
    })
    assert approved.status_code == 200


async def test_the_state_locks_a_hand_written_reply_the_server_would_refuse(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.route = '{"route":"judgment","issue":"6인 단체, 금요일, 견적 기준?"}'
    _ = await client.post(f"/grounded-replies/{GROUNDED}/draft")
    wrong = "예약금은 30,000원이에요."
    edited = await client.patch(f"/inquiries/{GROUNDED}/draft", json={"draft": wrong, "expectedRevision": 0})
    assert edited.status_code == 200
    state = (await client.get(f"/grounded-replies/{GROUNDED}")).json()
    assert (state["lock"], state["mismatchCount"], state["checkedKinds"]) == ("locked", 1, ["예약금"])
    refused = await client.post(f"/grounded-replies/{GROUNDED}/decision", json={
        "decision": "approve", "draft": wrong, "expectedRevision": 1,
    })
    assert refused.status_code == 409


async def test_the_answer_says_which_kinds_of_number_were_compared(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts, model.claims = [RIGHT_DRAFT], RIGHT_CLAIMS
    written = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
    assert written["checkedKinds"] == ["남은 자리", "예약금"]
    thanks = {"draft": "문의 주셔서 감사해요."}
    verified = (await client.post(f"/grounded-replies/{GROUNDED}/verify", json=thanks)).json()
    assert (verified["checkedKinds"], verified["claims"]) == ([], [])


async def test_unusable_model_drafts_fall_back_to_the_ledger(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.drafts = ["```\n```", "  "]
    body = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
    assert "남은 자리가 3자리예요" in body["draft"]
    assert body["draft"].startswith("이서준 님")
    assert body["lock"] == "unchecked"


async def test_a_question_the_facts_cannot_answer_is_handed_to_the_owner_once(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, GROUNDED)
    model.route = '{"route":"judgment","issue":"6인 단체, 금요일, 견적 기준?"}'
    for _ in range(2):
        body = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
        assert (body["draft"], body["judgment"]["issue"]) == ("", "6인 단체, 금요일, 견적 기준?")
    assert body["judgment"]["customer"] == "이서준"
    state = (await client.get(f"/grounded-replies/{GROUNDED}")).json()
    assert state["judgment"]["id"] == body["judgment"]["id"]
    async with database.connect() as connection:
        opened = await connection.scalar(
            text("SELECT count(*) FROM grounded_events WHERE kind = 'judgment_opened'"),
        )
    assert opened == 1


async def test_unknown_inquiries_and_missing_keys_are_refused(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    assert (await client.get("/grounded-replies/missing")).status_code == 404
    assert (await client.post("/grounded-replies/missing/draft")).status_code == 404
    denied = await client.get("/grounded-replies/metrics", headers={"X-Roundup-Key": "wrong"})
    assert denied.status_code == 401
