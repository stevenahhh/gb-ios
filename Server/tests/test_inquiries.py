"""Real PostgreSQL HTTP integration: no SQLite, fake stores, or mocked writes."""

from dataclasses import dataclass
from typing import Final, Literal

import anyio
import pytest
from httpx2 import AsyncClient, Response
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncEngine

from database import get_engine
from init_db import initialize
from inquiries import Inquiry

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
INQUIRIES: Final = TypeAdapter(list[Inquiry])


@dataclass(frozen=True, slots=True)
class DecisionCase:
    decision: str
    draft: str
    status: str
    saved: str


async def current(client: AsyncClient, inquiry_id: str = "inquiry-clay") -> Inquiry:
    response = await client.get("/inquiries")
    assert response.status_code == 200
    return next(row for row in INQUIRIES.validate_json(response.content) if row.id == inquiry_id)


async def test_readiness_requires_initialized_schema(
    empty_database: AsyncEngine, client: AsyncClient,
) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 503
    await initialize(empty_database)
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


async def test_seed_has_three_canonical_synthetic_inquiries(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    response = await client.get("/inquiries")
    assert response.status_code == 200
    rows = INQUIRIES.validate_json(response.content)
    assert {row.id for row in rows} == {"inquiry-clay", "inquiry-group", "inquiry-change"}
    assert len(rows) == 3
    for row in rows:
        assert row.model_fields_set == {
            "id", "customer", "subject", "question", "facts", "draft", "status", "revision",
        }
        assert row.status == "pending"
        assert row.revision == 0
        assert "(가상 고객)" in row.customer
    clay = next(row for row in rows if row.id == "inquiry-clay")
    assert clay.customer == "김하늘 (가상 고객)"
    assert clay.facts[2] == "제작 안내 · 건조와 소성에 약 3주가 필요하며 당일 수령은 불가합니다."


async def test_edit_preserves_whitespace_and_survives_new_pool(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    edited = await client.patch(
        "/inquiries/inquiry-clay/draft",
        json={"draft": "  수정한 초안 \n", "expectedRevision": 0},
    )
    assert edited.status_code == 200
    # A new engine/physical pool must read committed data, not a session identity map.
    options = database.get_execution_options()
    await database.dispose()
    get_engine.cache_clear()
    fresh = get_engine()
    fresh.update_execution_options(**options)
    try:
        row = await current(client)
        assert row.draft == "  수정한 초안 \n"
        assert row.revision == 1
        assert row.status == "pending"
    finally:
        await fresh.dispose()
        get_engine.cache_clear()


async def test_reinitialization_preserves_decisions_and_edits(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    response = await client.post(
        "/inquiries/inquiry-clay/decision",
        json={"decision": "approve", "draft": "  보존할 답변  ", "expectedRevision": 0},
    )
    assert response.status_code == 200
    await initialize(database)
    await initialize(database)
    assert await current(client) == Inquiry.model_validate_json(response.content)
    assert len((await client.get("/inquiries")).json()) == 3


@pytest.mark.parametrize(
    "case",
    [
        DecisionCase("approve", " \n최종 답변\t ", "approved", "최종 답변"),
        DecisionCase("reject", " \n\t ", "rejected", ""),
        DecisionCase("reject", "  반려 초안 \n", "rejected", "반려 초안"),
    ],
)
async def test_decision_commits_trimmed_draft(
    database: AsyncEngine, client: AsyncClient, case: DecisionCase,
) -> None:
    response = await client.post(
        "/inquiries/inquiry-group/decision",
        json={"decision": case.decision, "draft": case.draft, "expectedRevision": 0},
    )
    assert response.status_code == 200
    row = await current(client, "inquiry-group")
    assert (row.status, row.draft, row.revision) == (case.status, case.saved, 1)


async def test_blank_approval_rolls_back_without_changing_revision(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    before = await current(client)
    response = await client.post(
        "/inquiries/inquiry-clay/decision",
        json={"decision": "approve", "draft": " \n\t ", "expectedRevision": 0},
    )
    assert response.status_code == 422
    assert await current(client) == before


@pytest.mark.parametrize("operation", ["draft", "decision"])
async def test_stale_revision_conflicts_while_pending(
    database: AsyncEngine, client: AsyncClient, operation: str,
) -> None:
    await client.patch("/inquiries/inquiry-clay/draft", json={"draft": "new", "expectedRevision": 0})
    body = {"draft": "stale", "expectedRevision": 0}
    if operation == "decision":
        body["decision"] = "approve"
    response = await client.request(
        "PATCH" if operation == "draft" else "POST",
        f"/inquiries/inquiry-clay/{operation}", json=body,
    )
    assert response.status_code == 409
    assert (await current(client)).draft == "new"


@pytest.mark.parametrize("first", ["approve", "reject"])
async def test_completed_inquiry_refuses_edits_and_repeat_decisions(
    database: AsyncEngine, client: AsyncClient, first: str,
) -> None:
    completed = await client.post(
        "/inquiries/inquiry-clay/decision",
        json={"decision": first, "draft": "final", "expectedRevision": 0},
    )
    for revision in [0, 1]:
        edit = await client.patch(
            "/inquiries/inquiry-clay/draft", json={"draft": "overwrite", "expectedRevision": revision},
        )
        assert edit.status_code == 409
        for decision in ["approve", "reject"]:
            response = await client.post(
                "/inquiries/inquiry-clay/decision",
                json={"decision": decision, "draft": "", "expectedRevision": revision},
            )
            assert response.status_code == 409
    assert await current(client) == Inquiry.model_validate_json(completed.content)


@pytest.mark.parametrize("operation", ["draft", "decision"])
async def test_missing_inquiry_returns_404(
    database: AsyncEngine, client: AsyncClient, operation: str,
) -> None:
    body = {"draft": "hello", "expectedRevision": 0}
    if operation == "decision":
        body["decision"] = "approve"
    response = await client.request(
        "PATCH" if operation == "draft" else "POST", f"/inquiries/missing/{operation}", json=body,
    )
    assert response.status_code == 404


@pytest.mark.parametrize("operations", [("draft", "draft"), ("decision", "decision"), ("draft", "decision")])
async def test_concurrent_writers_have_exactly_one_winner(
    database: AsyncEngine, client: AsyncClient, operations: tuple[Literal["draft", "decision"], ...],
) -> None:
    responses: list[Response] = []
    start = anyio.Event()

    async def write(operation: Literal["draft", "decision"]) -> None:
        await start.wait()
        body = {"draft": operation, "expectedRevision": 0}
        if operation == "decision":
            body["decision"] = "approve"
        responses.append(await client.request(
            "PATCH" if operation == "draft" else "POST",
            f"/inquiries/inquiry-clay/{operation}", json=body,
        ))

    async with anyio.create_task_group() as group:
        for operation in operations:
            group.start_soon(write, operation)
        start.set()
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(
        Inquiry.model_validate_json(response.content) for response in responses if response.status_code == 200
    )
    assert await current(client) == winner
    assert winner.revision == 1
