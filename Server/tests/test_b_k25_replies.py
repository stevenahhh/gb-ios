"""A grounded reply is written from the ledger, checked against it, and locked until it agrees."""

from typing import Final

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from b_k25_engine import arm_for
from tests.b_k25_support import CONTROL, GROUNDED, ScriptedModel, add_inquiry, scripted

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
PLAIN_REPLY: Final = "이서준 님, 문의 주셔서 감사해요. 확인해서 다시 알려드릴게요."
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


def test_the_arm_of_an_inquiry_never_changes() -> None:
    assert arm_for(GROUNDED) == "grounded"
    assert arm_for(CONTROL) == "control"
    assert arm_for(GROUNDED) == arm_for(GROUNDED)


async def test_control_inquiry_gets_the_existing_draft_and_no_lock(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, CONTROL)
    model.drafts = [PLAIN_REPLY]
    response = await client.post(f"/grounded-replies/{CONTROL}/draft")
    body = response.json()
    assert response.status_code == 200
    assert (body["arm"], body["claims"], body["judgment"]) == ("control", [], None)
    assert body["draft"] == PLAIN_REPLY
    assert model.routes == 0
    prompt = "\n".join(model.prompts)
    assert "이서준" in prompt
    decided = await client.post(f"/grounded-replies/{CONTROL}/decision", json={
        "decision": "approve", "draft": PLAIN_REPLY, "expectedRevision": 0,
    })
    assert decided.json()["status"] == "approved"


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
    grounded = next(row for row in report if row["arm"] == "grounded")
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
