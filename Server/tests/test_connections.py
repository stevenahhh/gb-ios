"""Saved handles and links: what is accepted, revisions, and the additive migration."""

from datetime import datetime, timedelta

import anyio
import pytest
from httpx2 import AsyncClient, Response
from pydantic import JsonValue
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from connections import RefusedValueError, Service, normalised
from tests.conftest import downgrade, upgrade

TOKEN = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"  # noqa: S105 - synthetic


async def put(client: AsyncClient, service: str, value: str, revision: int) -> Response:
    return await client.put(f"/connections/{service}", json={"value": value, "expectedRevision": revision})


async def delete(client: AsyncClient, service: str, revision: int) -> Response:
    return await client.request("DELETE", f"/connections/{service}", json={"expectedRevision": revision})


def item(value: str | None, revision: int) -> dict[str, JsonValue]:
    return {
        "service": "instagram", "value": value, "state": "none" if value is None else "saved",
        "revision": revision,
    }


def untimed(response: Response) -> dict[str, JsonValue]:
    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body.pop("updatedAt")).utcoffset() == timedelta(hours=9)
    return body


@pytest.mark.parametrize(
    ("service", "raw", "stored"),
    [
        ("instagram", "  @Nolli.Studio ", "nolli.studio"),
        ("instagram", "https://www.instagram.com/Nolli.Studio/?igsh=abc", "nolli.studio"),
        ("naver_blog", "Nolli-Studio", "nolli-studio"),
        ("naver_blog", "https://m.blog.naver.com/nolli_studio", "nolli_studio"),
        (
            "naver_smartstore", "https://m.smartstore.naver.com/nolli/products/1?NaPm=hk%3D" + TOKEN,
            "https://smartstore.naver.com/nolli",
        ),
        ("naver_smartstore", "HTTPS://BRAND.naver.com/Nolli", "https://brand.naver.com/Nolli"),
        (
            "naver_booking", "https://m.booking.naver.com/booking/12/bizes/345/?area=x#top",
            "https://m.booking.naver.com/booking/12/bizes/345",
        ),
        ("naver_place", "https://naver.me/xAbC12d", "https://naver.me/xAbC12d"),
        (
            "naver_place", "https://map.naver.com/p/entry/place/1234567?c=15",
            "https://map.naver.com/p/entry/place/1234567",
        ),
        ("kakao_channel", "https://pf.kakao.com/_abCD/chat", "https://pf.kakao.com/_abCD"),
        ("google_maps", "https://maps.app.goo.gl/AbC123xyz", "https://maps.app.goo.gl/AbC123xyz"),
        ("google_maps", "https://maps.google.com/?cid=123&hl=ko", "https://maps.google.com/?cid=123"),
        (
            "google_maps", "https://www.google.com/maps/place/%EB%86%80%EB%A6%AC?authuser=0",
            "https://www.google.com/maps/place/%EB%86%80%EB%A6%AC",
        ),
    ],
)
def test_public_value_is_normalised(service: str, raw: str, stored: str) -> None:
    assert normalised(Service(service), raw) == stored


@pytest.mark.parametrize(
    ("service", "raw"),
    [
        ("instagram", " "),
        ("instagram", "a..b"),
        ("instagram", "공방"),
        ("instagram", "https://www.instagram.com/p/abc"),
        ("instagram", "https://www.instagram.com.evil.example/nolli"),
        ("naver_blog", "n"),
        ("naver_blog", "https://blog.example.com/nolli"),
        ("naver_smartstore", "nolli"),
        ("naver_smartstore", "http://smartstore.naver.com/nolli"),
        ("naver_smartstore", "https://smartstore.naver.com/"),
        ("naver_smartstore", "https://smartstore.naver.com@evil.example/nolli"),
        ("naver_smartstore", "https://id:pw@smartstore.naver.com/nolli"),
        ("naver_smartstore", "https://smartstore.naver.com:8443/nolli"),
        ("naver_booking", "https://booking.naver.com/%2e%2e/x"),
        ("naver_booking", "https://booking.naver.com/a%0d%0ab"),
        ("naver_booking", "https://[booking.naver.com/a"),
        ("naver_place", "https://naver.me"),
        ("naver_place", "javascript:alert(1)"),
        ("kakao_channel", "https://pf.kakao.com/nolli"),
        ("google_maps", "https://www.google.com/search"),
        ("google_maps", "https://www.google.com/mapsearch/x"),
        ("google_maps", "https://www.google.com/maps"),
        ("google_maps", "https://maps.app.goo.gl/" + "가" * 200),
    ],
)
def test_value_of_another_shape_or_host_is_refused(service: str, raw: str) -> None:
    with pytest.raises(RefusedValueError):
        _ = normalised(Service(service), raw)


@pytest.mark.parametrize(
    ("service", "raw"),
    [
        ("instagram", "nolli password: hunter2"),
        ("instagram", "비밀번호=1234"),
        ("naver_blog", TOKEN),
        ("naver_blog", "ghp_abcdefghijklmnop1234"),
        ("naver_smartstore", "https://smartstore.naver.com/nolli?access_token=abc"),
        ("naver_smartstore", "https://smartstore.naver.com/nolli?access%5Ftoken%3Dabc"),
        ("naver_booking", f"https://booking.naver.com/booking/{TOKEN}"),
        ("google_maps", "https://www.google.com/maps/embed?key=abc"),
        ("naver_place", "https://naver.me/eyJhbGciOiJIUzI1NiJ9.eyJzdWIi"),
    ],
)
def test_secret_looking_value_is_refused_and_not_repeated(service: str, raw: str) -> None:
    with pytest.raises(RefusedValueError) as refused:
        _ = normalised(Service(service), raw)
    assert "비밀번호나 토큰" in refused.value.message
    assert raw not in refused.value.message


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_routes_require_the_shared_key(client: AsyncClient, method: str) -> None:
    path = "/connections" if method == "GET" else "/connections/instagram"
    response = await client.request(method, path, headers={"X-Roundup-Key": "wrong"}, json={})
    assert response.status_code == 401


@pytest.mark.anyio
@pytest.mark.postgres
async def test_every_service_is_listed_before_anything_is_saved(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    response = await client.get("/connections")
    assert response.status_code == 200
    assert response.json() == {"items": [
        {"service": service, "value": None, "state": "none", "updatedAt": None, "revision": 0}
        for service in (
            "instagram", "naver_smartstore", "naver_blog", "naver_booking", "naver_place", "kakao_channel",
            "google_maps",
        )
    ]}


@pytest.mark.anyio
@pytest.mark.postgres
async def test_save_change_and_clear_raise_the_revision(database: AsyncEngine, client: AsyncClient) -> None:
    assert untimed(await put(client, "instagram", "@Nolli", 0)) == item("nolli", 1)
    assert untimed(await put(client, "instagram", "nolli.studio", 1)) == item("nolli.studio", 2)
    assert untimed(await delete(client, "instagram", 2)) == item(None, 3)
    assert untimed(await delete(client, "instagram", 3)) == item(None, 3)
    restored = await put(client, "instagram", "nolli", 3)
    assert untimed(restored) == item("nolli", 4)
    assert (await client.get("/connections")).json()["items"][0] == restored.json()


@pytest.mark.anyio
@pytest.mark.postgres
async def test_stale_writer_gets_a_korean_conflict_and_changes_nothing(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    _ = await put(client, "naver_blog", "nolli", 0)
    stale = [
        await put(client, "naver_blog", "other", 0),
        await delete(client, "naver_blog", 2),
        await put(client, "instagram", "nolli", 1),
        await delete(client, "instagram", 1),
    ]
    assert {response.status_code for response in stale} == {409}
    assert {response.json()["detail"] for response in stale} == {
        "다른 곳에서 먼저 바뀌었어요. 새로 불러온 뒤 다시 시도해 주세요.",
    }
    items = (await client.get("/connections")).json()["items"]
    assert [(row["value"], row["revision"]) for row in items if row["revision"]] == [("nolli", 1)]


@pytest.mark.anyio
@pytest.mark.postgres
async def test_concurrent_first_saves_have_one_winner(database: AsyncEngine, client: AsyncClient) -> None:
    statuses: list[int] = []

    async def save(value: str) -> None:
        statuses.append((await put(client, "instagram", value, 0)).status_code)

    async with anyio.create_task_group() as group:
        group.start_soon(save, "first")
        group.start_soon(save, "second")
    assert sorted(statuses) == [200, 409]


@pytest.mark.anyio
@pytest.mark.postgres
async def test_refused_value_and_unknown_service_are_not_stored(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    refused = await put(client, "naver_blog", TOKEN, 0)
    assert refused.status_code == 422
    assert TOKEN not in refused.text
    for unknown in (await put(client, "calendar", "x", 0), await delete(client, "bank", 0)):
        assert (unknown.status_code, unknown.json()["detail"]) == (404, "저장할 수 없는 서비스예요.")
    items = (await client.get("/connections")).json()["items"]
    assert {row["state"] for row in items} == {"none"}


@pytest.mark.anyio
@pytest.mark.postgres
async def test_saved_blog_id_leaves_collection_off(database: AsyncEngine, client: AsyncClient) -> None:
    before = (await client.get("/collectors/status")).json()
    _ = await put(client, "naver_blog", "nolli", 0)
    assert (await client.get("/collectors/status")).json() == before


@pytest.mark.anyio
@pytest.mark.postgres
async def test_downgrade_drops_only_the_connections_table(migrated: AsyncEngine) -> None:
    def names(connection: Connection) -> set[str]:
        return set(inspect(connection).get_table_names())

    async def tables() -> set[str]:
        async with migrated.connect() as connection:
            return await connection.run_sync(names)

    before = await tables()
    await downgrade(migrated, "0006_agent")
    assert before - await tables() == {"connections"}
    await upgrade(migrated)
    assert await tables() == before
