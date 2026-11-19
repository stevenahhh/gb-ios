"""Real PostgreSQL HTTP integration: no SQLite, fake stores, or mocked writes."""

from typing import Final, Literal

import anyio
import pytest
from httpx2 import AsyncClient, Response
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncEngine

from database import get_engine
from inquiries import Inquiry
from seed import apply_seed
from tests.conftest import NOW

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]
INQUIRIES: Final = TypeAdapter(list[Inquiry])


async def current(client: AsyncClient, inquiry_id: str = "inquiry-clay") -> Inquiry:
    response = await client.get("/inquiries")
    assert response.status_code == 200
    return next(row for row in INQUIRIES.validate_json(response.content) if row.id == inquiry_id)


async def test_seed_has_three_real_looking_inquiries(
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
        assert "가상" not in row.customer
    clay = next(row for row in rows if row.id == "inquiry-clay")
    assert clay.customer == "김하늘"
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
    await database.dispose()
    get_engine.cache_clear()
    row = await current(client)
    assert row.draft == "  수정한 초안 \n"
    assert row.revision == 1
    assert row.status == "pending"


async def test_reinitialization_preserves_decisions_and_edits(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    response = await client.post(
        "/inquiries/inquiry-clay/decision",
        json={"decision": "approve", "draft": "  보존할 답변  ", "expectedRevision": 0},
    )
    assert response.status_code == 200
    for _ in range(2):
        async with database.begin() as connection:
            _ = await apply_seed(connection, NOW.date())
    assert await current(client) == Inquiry.model_validate_json(response.content)
    assert len((await client.get("/inquiries")).json()) == 3


async def test_completion_commits_trimmed_reply(database: AsyncEngine, client: AsyncClient) -> None:
    response = await client.post(
        "/inquiries/inquiry-group/decision",
        json={"decision": "approve", "draft": " \n최종 답변\t ", "expectedRevision": 0},
    )
    assert response.status_code == 200
    row = await current(client, "inquiry-group")
    assert (row.status, row.draft, row.revision) == ("approved", "최종 답변", 1)


async def test_reject_decision_no_longer_exists(database: AsyncEngine, client: AsyncClient) -> None:
    before = await current(client)
    response = await client.post(
        "/inquiries/inquiry-clay/decision",
        json={"decision": "reject", "draft": "반려", "expectedRevision": 0},
    )
    assert response.status_code == 422
    assert await current(client) == before


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


async def test_completed_reply_stays_editable_but_never_blank(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    path = "/inquiries/inquiry-clay"
    done = {"decision": "approve", "expectedRevision": 0, "draft": "첫 답변"}
    assert (await client.post(f"{path}/decision", json=done)).status_code == 200

    edited = await client.patch(f"{path}/draft", json={"draft": "고친 답변", "expectedRevision": 1})
    assert edited.status_code == 200
    row = await current(client)
    assert (row.status, row.draft, row.revision) == ("approved", "고친 답변", 2)

    blank = await client.patch(f"{path}/draft", json={"draft": " \n", "expectedRevision": 2})
    assert blank.status_code == 422
    stale = await client.post(f"{path}/decision", json={**done, "draft": "늦은 답변"})
    assert stale.status_code == 409
    assert await current(client) == row

    body = {**done, "draft": " 다시 완료 ", "expectedRevision": 2}
    again = await client.post(f"{path}/decision", json=body)
    assert again.status_code == 200
    row = await current(client)
    assert (row.status, row.draft, row.revision) == ("approved", "다시 완료", 3)


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
