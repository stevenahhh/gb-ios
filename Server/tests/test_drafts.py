"""Assistant text decisions persist locally and reopen linked work atomically."""

from typing import Final

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
DRAFTS: Final = (
    ("content", "draft-weekend-class"), ("recommendation", "recommendation-market"),
)


@pytest.mark.parametrize(("kind", "draft_id"), DRAFTS)
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_draft_edit_decision_and_reopen(
    database: AsyncEngine, client: AsyncClient, kind: str, draft_id: str, decision: str,
) -> None:
    path = f"/assistant-drafts/{kind}/{draft_id}"
    initial = (await client.get(path)).json()
    assert initial["status"] == "pending"
    assert initial["canReopen"] is False
    assert initial["text"] not in initial["lines"]
    expected_after = (
        "승인해도 자동으로 게시되지 않아요. 게시는 직접 해 주세요."
        if kind == "content" else "승인해도 자동으로 신청되거나 발송되지 않아요."
    )
    assert initial["afterApproval"] == expected_after
    edited = await client.patch(f"{path}/draft", json={"draft": " 수정 중 ", "expectedRevision": 0})
    assert edited.status_code == 200
    assert (edited.json()["text"], edited.json()["revision"]) == ("수정 중", 1)
    decided = await client.post(
        f"{path}/decision", json={"decision": decision, "draft": " 최종 초안 ", "expectedRevision": 1},
    )
    assert decided.status_code == 200, decided.text
    state = "approved" if decision == "approve" else "rejected"
    assert (decided.json()["status"], decided.json()["canReopen"], decided.json()["revision"]) == (
        state, True, 2,
    )
    assert (await client.get(path)).json() == decided.json()
    for revision in [1, 2]:
        assert (
            await client.patch(f"{path}/draft", json={"draft": "덮어쓰기", "expectedRevision": revision})
        ).status_code == 409
        assert (
            await client.post(
                f"{path}/decision",
                json={"decision": decision, "draft": "반복", "expectedRevision": revision},
            )
        ).status_code == 409
    assert (await client.post(f"{path}/reopen", json={"expectedRevision": 1})).status_code == 409
    reopened = await client.post(f"{path}/reopen", json={"expectedRevision": 2})
    assert reopened.status_code == 200
    assert (reopened.json()["status"], reopened.json()["text"], reopened.json()["revision"]) == (
        "pending", "최종 초안", 3,
    )
    assert reopened.json()["canReopen"] is False
    assert (await client.post(f"{path}/reopen", json={"expectedRevision": 3})).status_code == 409
    if kind == "content":
        linked = (await client.get("/assistant-drafts/recommendation/recommendation-weekend")).json()
        assert (linked["status"], linked["revision"]) == ("pending", 2)
        async with database.connect() as connection:
            assert (await connection.execute(text(
                "SELECT c.reviewed_at, r.acknowledged_at FROM content_drafts c "
                "JOIN assistant_recommendations r ON r.draft_id = c.id WHERE c.id = 'draft-weekend-class'",
            ))).one() == (None, None)


@pytest.mark.parametrize(("kind", "draft_id"), DRAFTS)
@pytest.mark.parametrize("operation", ["draft", "approve", "reject"])
async def test_blank_assistant_text_is_422_without_changes(
    database: AsyncEngine, client: AsyncClient, kind: str, draft_id: str, operation: str,
) -> None:
    path = f"/assistant-drafts/{kind}/{draft_id}"
    before = (await client.get(path)).json()
    body = {"draft": " \n\t ", "expectedRevision": 0}
    if operation != "draft":
        body["decision"] = operation
    result = await client.request(
        "PATCH" if operation == "draft" else "POST",
        f"{path}/{'draft' if operation == 'draft' else 'decision'}", json=body,
    )
    assert result.status_code == 422
    assert (await client.get(path)).json() == before


@pytest.mark.parametrize(("kind", "draft_id"), DRAFTS)
@pytest.mark.parametrize("operation", ["draft", "decision"])
async def test_stale_assistant_write_changes_nothing(
    database: AsyncEngine, client: AsyncClient, kind: str, draft_id: str, operation: str,
) -> None:
    path = f"/assistant-drafts/{kind}/{draft_id}"
    before = (await client.get(path)).json()
    body = {"draft": "수정", "expectedRevision": 99}
    if operation == "decision":
        body["decision"] = "reject"
    response = await client.request(
        "PATCH" if operation == "draft" else "POST", f"{path}/{operation}", json=body,
    )
    assert response.status_code == 409
    assert (await client.get(path)).json() == before


@pytest.mark.parametrize("kind", ["content", "recommendation"])
@pytest.mark.parametrize("operation", [
    ("GET", "", {}),
    ("PATCH", "/draft", {"draft": "수정", "expectedRevision": 0}),
    ("POST", "/decision", {"decision": "approve", "draft": "수정", "expectedRevision": 0}),
    ("POST", "/reopen", {"expectedRevision": 0}),
])
async def test_assistant_missing_and_unknown_kind(
    database: AsyncEngine, client: AsyncClient, kind: str, operation: tuple[str, str, dict[str, str | int]],
) -> None:
    method, suffix, body = operation
    assert (
        await client.request(method, f"/assistant-drafts/{kind}/missing{suffix}", json=body)
    ).status_code == 404
    assert (
        await client.request(method, f"/assistant-drafts/unknown/missing{suffix}", json=body)
    ).status_code == 422


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_content_decision_updates_link_and_remains_visible(
    database: AsyncEngine, client: AsyncClient, decision: str,
) -> None:
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "INSERT INTO assistant_recommendations (id, kind, title, body, draft_id, status) "
            "SELECT 'recommendation-second', kind, title, body, draft_id, status "
            "FROM assistant_recommendations WHERE id = 'recommendation-weekend'",
        ))
    response = await client.post(
        "/assistant-drafts/content/draft-weekend-class/decision",
        json={"decision": decision, "draft": "새 모집 글", "expectedRevision": 0},
    )
    assert response.status_code == 200
    state = "approved" if decision == "approve" else "rejected"
    linked = (await client.get("/assistant-drafts/recommendation/recommendation-weekend")).json()
    assert (linked["status"], linked["revision"]) == (state, 1)
    second = (await client.get("/assistant-drafts/recommendation/recommendation-second")).json()
    assert (second["status"], second["revision"]) == (state, 1)
    async with database.begin() as connection:
        rows = (await connection.execute(text(
            "SELECT c.reviewed_at, r.acknowledged_at FROM content_drafts c "
            "JOIN assistant_recommendations r ON r.draft_id = c.id WHERE c.id = 'draft-weekend-class'",
        ))).all()
        assert rows == [(NOW, NOW)] * 2
        # A decided recommendation remains undoable even when its basis disappears.
        _ = await connection.execute(text(
            "UPDATE class_sessions SET capacity = 5 WHERE id = 'session-weekend'",
        ))
    today = (await client.get("/today")).json()
    card = next(card for card in today["suggestions"]["items"] if card["id"] == "recommendation-weekend")
    assert card["draft"] == {
        "kind": "content", "id": "draft-weekend-class", "status": state, "preview": "새 모집 글",
    }
    assert card["action"] is None
    if decision == "reject":
        assert card["status"] == {"text": "반려함", "tone": "neutral"}
    assert next(m["value"] for m in today["suggestions"]["metrics"] if m["key"] == "openRecommendations") == 2
    content = (await client.get("/channels", params={"section": "content"})).json()
    card = next(card for card in content["items"] if card["id"] == "draft-weekend-class")
    assert card["draft"]["status"] == state
    assert card["action"] is None
    assert len((await client.get("/opportunities")).json()) == 1
    assert (
        await client.post(
            "/assistant-drafts/content/draft-weekend-class/reopen", json={"expectedRevision": 1},
        )
    ).status_code == 200
    for row_id in ["recommendation-weekend", "recommendation-second"]:
        linked = (await client.get(f"/assistant-drafts/recommendation/{row_id}")).json()
        assert (linked["status"], linked["revision"]) == ("pending", 2)


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_decided_recommendation_recent_window_and_reopen(
    database: AsyncEngine, client: AsyncClient, decision: str,
) -> None:
    path = "/assistant-drafts/recommendation/recommendation-market"
    assert (
        await client.post(
            f"{path}/decision", json={"decision": decision, "draft": "새 추천", "expectedRevision": 0},
        )
    ).status_code == 200
    today = (await client.get("/today")).json()
    card = next(item for item in today["suggestions"]["items"] if item["id"] == "recommendation-market")
    state = "approved" if decision == "approve" else "rejected"
    assert card["draft"] == {
        "kind": "recommendation", "id": "recommendation-market", "status": state, "preview": "새 추천",
    }
    assert {m["key"]: m["value"] for m in today["suggestions"]["metrics"]} == {
        "openRecommendations": 2, "drafts": 2, "acknowledgedThisWeek": 1,
    }
    async with database.begin() as connection:
        _ = await connection.execute(text(
            "UPDATE assistant_recommendations SET acknowledged_at = '2026-11-10T11:00:00+09:00' "
            "WHERE id = 'recommendation-market'",
        ))
    today = (await client.get("/today")).json()
    assert {item["id"] for item in today["suggestions"]["items"]} == {
        "recommendation-deposit", "recommendation-weekend",
    }
    assert len((await client.get("/opportunities")).json()) == 1
    assert (await client.post(f"{path}/reopen", json={"expectedRevision": 1})).status_code == 200
    today = (await client.get("/today")).json()
    assert {m["key"]: m["value"] for m in today["suggestions"]["metrics"]} == {
        "openRecommendations": 3, "drafts": 2, "acknowledgedThisWeek": 0,
    }
