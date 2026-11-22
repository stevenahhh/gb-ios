"""A judgment is answered once, can become a reusable rule, and the next draft rests on that rule."""

from typing import Final

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.b_k25_support import CONTROL, GROUNDED, ScriptedModel, add_inquiry, scripted

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
WEEKEND: Final = "주말 도자기 클래스"
ISSUE: Final = "6인 단체, 금요일, 견적 기준?"
ANSWER: Final = "6명부터 1인 3만 원"
RULE: Final = '{"rule":"6명부터 1인 3만 원을 받아요.","applies_to":"주말 도자기 클래스"}'


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> ScriptedModel:
    return scripted(monkeypatch)


async def raise_judgment(database: AsyncEngine, client: AsyncClient, model: ScriptedModel) -> str:
    await add_inquiry(database, GROUNDED)
    model.route = f'{{"route":"judgment","issue":"{ISSUE}"}}'
    body = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
    model.route = '{"route":"draft"}'
    return body["judgment"]["id"]


def expect_price(model: ScriptedModel) -> None:
    """Script a draft and an extraction that state the owner's price."""
    model.drafts = ["○○ 님, 6명부터 1인 30,000원이에요."]
    model.claims = '[{"kind":"price","text":"30,000원","value":"30000"}]'


async def answer(client: AsyncClient, judgment: str, scope: str) -> dict[str, object]:
    body = {"answer": ANSWER, "scope": scope}
    response = await client.post(f"/judgments/{judgment}/answer", json=body)
    assert response.status_code == 200
    return response.json()


async def test_an_open_judgment_carries_the_customers_words(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    judgment = await raise_judgment(database, client, model)
    rows = (await client.get("/judgments")).json()
    assert [(row["id"], row["issue"], row["customer"]) for row in rows] == [(judgment, ISSUE, "이서준")]
    assert "토요일 주말 클래스" in rows[0]["question"]
    assert (await client.get("/judgments?status=answered")).json() == []
    assert (await client.get("/judgments?status=unknown")).status_code == 422


async def test_rule_preview_keeps_the_owners_numbers_and_hides_the_customer(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    judgment = await raise_judgment(database, client, model)
    model.rule = RULE
    preview = (await client.post(f"/judgments/{judgment}/rule-preview", json={"answer": ANSWER})).json()
    assert preview == {"ruleText": "6명부터 1인 3만 원을 받아요.", "className": WEEKEND}
    model.rule = '{"rule":"이서준 님은 8명부터 1인 3만 원","applies_to":"전체"}'
    changed = (await client.post(f"/judgments/{judgment}/rule-preview", json={"answer": ANSWER})).json()
    assert changed == {"ruleText": ANSWER, "className": WEEKEND}
    model.rule = '{"rule":"이서준 님 6명부터 1인 3만 원","applies_to":"전체"}'
    named = (await client.post(f"/judgments/{judgment}/rule-preview", json={"answer": ANSWER})).json()
    assert named == {"ruleText": "손님 님 6명부터 1인 3만 원", "className": None}


async def test_an_answer_as_rule_is_reused_by_the_next_draft(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    judgment = await raise_judgment(database, client, model)
    model.rule = RULE
    expect_price(model)
    body = await answer(client, judgment, "rule")
    assert (body["ruleText"], body["lock"]) == ("6명부터 1인 3만 원을 받아요.", "clear")
    claims = body["claims"]
    assert isinstance(claims, list)
    assert [(claim["kind"], claim["sourceLabel"], claim["status"]) for claim in claims] == [
        ("price", "내 규칙", "matched"),
    ]
    rules = (await client.get("/owner-rules")).json()
    assert [(row["id"], row["className"]) for row in rules] == [(body["ruleId"], WEEKEND)]
    cards = {row["className"]: row for row in (await client.get("/fact-cards")).json()}
    assert cards[WEEKEND]["ruleCount"] == 1
    assert (await client.get("/judgments")).json() == []
    expect_price(model)
    written = (await client.post(f"/grounded-replies/{GROUNDED}/draft")).json()
    assert written["lock"] == "clear"
    assert "[내 규칙]\n- (주말 도자기 클래스) 6명부터 1인 3만 원을 받아요." in "\n".join(model.prompts)


async def test_an_answer_for_this_reply_only_saves_no_rule(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    judgment = await raise_judgment(database, client, model)
    expect_price(model)
    body = await answer(client, judgment, "once")
    assert (body["ruleId"], body["ruleText"], body["lock"]) == (None, None, "clear")
    assert (await client.get("/owner-rules")).json() == []
    assert "[이번 문의에 대한 사장님 답]" in "\n".join(model.prompts)
    async with database.connect() as connection:
        row = (await connection.execute(
            text("SELECT status, answer_text, rule_id FROM judgment_requests"),
        )).one()
    assert (row.status, row.answer_text, row.rule_id) == ("answered", ANSWER, None)


async def test_a_judgment_is_answered_once(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    judgment = await raise_judgment(database, client, model)
    model.rule = RULE
    expect_price(model)
    _ = await answer(client, judgment, "rule")
    body = {"answer": ANSWER, "scope": "once"}
    assert (await client.post(f"/judgments/{judgment}/answer", json=body)).status_code == 409
    preview = await client.post(f"/judgments/{judgment}/rule-preview", json={"answer": ANSWER})
    assert preview.status_code == 409
    missing = await client.post("/judgments/missing/answer", json=body)
    assert missing.status_code == 404
    empty = await client.post(f"/judgments/{judgment}/answer", json={"answer": " ", "scope": "once"})
    assert empty.status_code in {409, 422}


async def test_a_dismissed_judgment_leaves_the_list_and_cannot_be_answered(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    judgment = await raise_judgment(database, client, model)
    dismissed = await client.post(f"/judgments/{judgment}/dismiss", json={})
    assert dismissed.json()["status"] == "dismissed"
    assert (await client.get("/judgments")).json() == []
    assert (await client.post(f"/judgments/{judgment}/dismiss", json={})).status_code == 409


async def test_a_retired_rule_is_never_used_again(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    judgment = await raise_judgment(database, client, model)
    model.rule = RULE
    expect_price(model)
    body = await answer(client, judgment, "rule")
    retired = await client.delete(f"/owner-rules/{body['ruleId']}")
    assert retired.json()["ruleText"] == "6명부터 1인 3만 원을 받아요."
    assert (await client.delete(f"/owner-rules/{body['ruleId']}")).status_code == 404
    assert (await client.get("/owner-rules")).json() == []
    expect_price(model)
    prompts = len(model.prompts)
    _ = await client.post(f"/grounded-replies/{GROUNDED}/draft")
    later = "\n".join(model.prompts[prompts:])
    assert "6명부터 1인 3만 원을 받아요" not in later


async def test_control_inquiries_never_raise_judgments(
    database: AsyncEngine, client: AsyncClient, model: ScriptedModel,
) -> None:
    await add_inquiry(database, CONTROL)
    model.route = f'{{"route":"judgment","issue":"{ISSUE}"}}'
    model.drafts = ["이서준 님, 확인해서 다시 알려드릴게요."]
    body = (await client.post(f"/grounded-replies/{CONTROL}/draft")).json()
    assert (body["arm"], body["judgment"]) == ("control", None)
    assert (await client.get("/judgments")).json() == []
