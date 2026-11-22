"""Collector behavior at the HTTP transport; no database and no real network."""

from datetime import timedelta

import httpx
import pytest

from collectors.base import CollectedItem, JsonObject, NeedsConnectionError, Window
from collectors.feed import parse_feed
from collectors.http import MAX_BYTES, USER_AGENT, SourceError
from collectors.instagram import InstagramCollector
from collectors.naver_blog import NaverBlogCollector
from collectors.naver_smartstore import SmartStoreCollector, signature
from collectors.registry import ALL_SOURCES, build
from collectors.robots import allows
from collectors.text import clean_raw, plain_text, safe_url
from tests.collector_fakes import FEED, FakeNetwork, json_reply, reply
from tests.conftest import NOW

pytestmark = pytest.mark.anyio
WINDOW = Window(since=NOW - timedelta(days=2), now=NOW)
BLOG: JsonObject = {"blog_id": "studio", "enabled": True}
FEED_PATH = "/studio.xml"


async def collect_blog(net: FakeNetwork) -> list[CollectedItem]:
    return await NaverBlogCollector(net.gateway, BLOG).collect(WINDOW)


@pytest.mark.parametrize(
    ("text", "path", "allowed"),
    [
        ("", "/a.xml", True),
        ("User-agent: *\nDisallow:", "/a.xml", True),
        ("User-agent: *\nDisallow: /", "/a.xml", False),
        ("\ufeffUser-agent: *\r\nDisallow: / # all", "/a.xml", False),
        ("User-agent: *\nDisallow: /*.xml$", "/a.xml", False),
        ("User-agent: *\nDisallow: /*.xml$", "/a.xml?x=1", True),
        ("User-agent: *\nAllow: /\nDisallow: /private", "/private/a", False),
        ("User-agent: *\nDisallow: /\nAllow: /feed/", "/feed/a.xml", True),
        ("User-agent: *\nDisallow: /a\nAllow: /a", "/a", False),
        ("User-agent: other\nDisallow: /", "/a.xml", True),
        ("User-agent: *\nAllow: /\n\nUser-agent: gongdoricollector\nDisallow: /", "/a.xml", False),
        ("User-agent: *\nDisallow: /\n\nUser-agent: GongdoriCollector/0.1\nAllow: /", "/a.xml", True),
        ("User-agent: other\nUser-agent: *\nDisallow: /", "/a.xml", False),
        ("User-agent: *\nDisallow: /%61", "/a.xml", False),
    ],
)
def test_robots_rules(text: str, path: str, *, allowed: bool) -> None:
    assert allows(text, path) is allowed


async def test_disallowing_robots_refuses_before_the_feed_is_requested() -> None:
    net = FakeNetwork({"/robots.txt": reply(text="User-agent: *\nDisallow: /"), FEED_PATH: reply(text=FEED)})
    with pytest.raises(NeedsConnectionError, match="정책"):
        _ = await collect_blog(net)
    assert net.paths == ["/robots.txt"]


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 418])
async def test_unreadable_robots_counts_as_disallowed(status: int) -> None:
    net = FakeNetwork({"/robots.txt": reply(status), FEED_PATH: reply(text=FEED)})
    with pytest.raises(NeedsConnectionError):
        _ = await collect_blog(net)
    assert net.paths == ["/robots.txt"]


async def test_unavailable_robots_stops_the_run_without_the_feed() -> None:
    net = FakeNetwork({"/robots.txt": reply(503), FEED_PATH: reply(text=FEED)})
    with pytest.raises(SourceError, match="http_503"):
        _ = await collect_blog(net)
    assert set(net.paths) == {"/robots.txt"}


@pytest.mark.parametrize("robots", [reply(404), reply(text="User-agent: *\nAllow: /")])
async def test_permitting_robots_lets_one_feed_request_through(robots: object) -> None:
    assert callable(robots)
    net = FakeNetwork({"/robots.txt": robots, FEED_PATH: reply(text=FEED)})
    assert len(await collect_blog(net)) == 2
    assert net.paths == ["/robots.txt", FEED_PATH]
    assert {request.headers["user-agent"] for request in net.requests} == {USER_AGENT}


async def test_feed_redirect_is_not_followed() -> None:
    moved = httpx.Response(302, headers={"location": "https://elsewhere.test/feed.xml"})
    net = FakeNetwork({"/robots.txt": reply(404), FEED_PATH: lambda _request: moved})
    with pytest.raises(SourceError, match="http_302"):
        _ = await collect_blog(net)
    assert {request.url.host for request in net.requests} == {"rss.blog.naver.com"}


@pytest.mark.parametrize("stored", [{}, {"blog_id": "studio"}, {"enabled": True}, {"blog_id": "../x"}])
def test_blog_is_off_until_the_owner_sets_it_up(stored: JsonObject) -> None:
    assert NaverBlogCollector(FakeNetwork().gateway, stored).connection_problem() is not None


def test_feed_items_are_plain_text_with_safe_links() -> None:
    first, second = parse_feed(FEED.encode())
    assert first.external_id == "https://feed.test/posts/2"
    assert (first.title, first.author) == ("가을 컵 소식", "maker")
    assert first.body == "새 컵이 나왔어요.\n&lt;img onerror=x&gt;"
    assert "steal" not in first.body
    assert first.published_at is not None
    assert first.published_at.isoformat() == "2026-11-17T10:00:00+09:00"
    assert second.url is None
    assert second.published_at is None


@pytest.mark.parametrize(
    "content",
    [
        b"", b"not xml", b"<html/>",
        b'<!DOCTYPE r [<!ENTITY a "b">]><rss><channel><item><guid>&a;</guid></item></channel></rss>',
        b'<!DOCTYPE r SYSTEM "file:///etc/passwd"><rss/>',
    ],
)
def test_unsafe_or_broken_feed_is_rejected(content: bytes) -> None:
    with pytest.raises(SourceError, match="malformed"):
        _ = parse_feed(content)


def test_stored_text_and_json_are_bounded() -> None:
    assert plain_text("a\x00b\ud800<i>c</i> &lt;d&gt;", 100) == "ab?c &lt;d&gt;"
    assert len(plain_text("가" * 9000, 4000)) == 4000
    assert safe_url("file:///etc/passwd") is None
    assert safe_url("https://feed.test/1") == "https://feed.test/1"
    assert clean_raw({"a": "x\x00", "b": ["\x00"]}) == {"a": "x", "b": [""]}
    assert clean_raw({"a": "x" * 40_000}) == {"truncated": True}


async def test_requests_are_spaced_by_the_source_interval() -> None:
    net = FakeNetwork({"/robots.txt": reply(404), FEED_PATH: reply(text=FEED)})
    _ = await collect_blog(net)
    assert net.sleeps == [NaverBlogCollector.min_interval]


async def test_temporary_failures_back_off_then_succeed() -> None:
    left = [httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(500), httpx.Response(404)]
    net = FakeNetwork({"/robots.txt": lambda _request: left.pop(0), FEED_PATH: reply(text=FEED)})
    assert len(await collect_blog(net)) == 2
    assert net.sleeps == [7.0, 2.0, 2.0]


async def test_connection_failures_stop_after_three_attempts() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        message = "secret-host"
        raise httpx.ConnectError(message, request=request)

    net = FakeNetwork({"/robots.txt": broken})
    with pytest.raises(SourceError) as failure:
        _ = await collect_blog(net)
    assert failure.value.code == "network"
    assert len(net.requests) == 3


async def test_oversized_body_is_refused() -> None:
    net = FakeNetwork({"/robots.txt": reply(404), FEED_PATH: reply(text="x" * (MAX_BYTES + 1))})
    with pytest.raises(SourceError, match="too_large"):
        _ = await collect_blog(net)


@pytest.mark.parametrize("source", ALL_SOURCES)
async def test_every_source_without_setup_needs_connection(
    monkeypatch: pytest.MonkeyPatch, source: str,
) -> None:
    for name in (
        "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID",
        "NAVER_COMMERCE_CLIENT_ID", "NAVER_COMMERCE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    net = FakeNetwork()
    known = next(each for each in ALL_SOURCES if each == source)
    assert build(known, net.gateway, {}).connection_problem()
    assert net.requests == []


def test_signature_matches_the_official_example() -> None:
    assert signature("aaaabbbbcccc", "$2a$10$abcdefghijklmnopqrstuv", 1643961623299) == (
        "JDJhJDEwJGFiY2RlZmdoaWprbG1ub3BxcnN0dXVCVldZSk42T0VPdEx1OFY0cDQxa2IuTnpVaUEzbmsy"
    )


def instagram(monkeypatch: pytest.MonkeyPatch, net: FakeNetwork) -> InstagramCollector:
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.setenv("INSTAGRAM_USER_ID", "17")
    return InstagramCollector(net.gateway, {})


async def test_instagram_reads_media_comments_and_insights(monkeypatch: pytest.MonkeyPatch) -> None:
    media = {
        "id": "5", "caption": "새 컵", "permalink": "https://www.instagram.com/p/x/", "username": "studio",
        "timestamp": "2026-11-17T01:00:00+0000", "comments_count": 1,
    }
    comment = {
        "id": "9", "text": "가격이 궁금해요", "timestamp": "2026-11-17T02:00:00+0000", "username": "guest",
    }
    net = FakeNetwork({
        "/v27.0/17/media": json_reply({"data": [media]}),
        "/v27.0/5/comments": json_reply({"data": [comment]}),
        "/v27.0/17/insights": json_reply({"data": [{"name": "reach", "total_value": {"value": 12}}]}),
    })
    items = await instagram(monkeypatch, net).collect(WINDOW)
    assert [(item.kind, item.external_id) for item in items] == [
        ("post", "media:5"), ("comment", "comment:9"), ("insight", "insight:2026-11-18"),
    ]
    assert items[2].body == "도달 12"
    assert "synthetic-token" not in str(items)
    assert {request.url.host for request in net.requests} == {"graph.instagram.com"}
    assert {request.headers["user-agent"] for request in net.requests} == {USER_AGENT}


async def test_instagram_expired_token_needs_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    net = FakeNetwork({"/v27.0/17/media": json_reply({"error": {"code": 190}}, 400)})
    with pytest.raises(NeedsConnectionError):
        _ = await instagram(monkeypatch, net).collect(WINDOW)


async def test_instagram_without_insight_permission_keeps_media(monkeypatch: pytest.MonkeyPatch) -> None:
    net = FakeNetwork({
        "/v27.0/17/media": json_reply({"data": []}),
        "/v27.0/17/insights": json_reply({"error": {"code": 10}}, 400),
    })
    assert await instagram(monkeypatch, net).collect(WINDOW) == []


def store(monkeypatch: pytest.MonkeyPatch, net: FakeNetwork) -> SmartStoreCollector:
    monkeypatch.setenv("NAVER_COMMERCE_CLIENT_ID", "synthetic-id")
    monkeypatch.setenv("NAVER_COMMERCE_CLIENT_SECRET", "$2a$04$abcdefghijklmnopqrstuv")
    return SmartStoreCollector(net.gateway, {})


async def test_smartstore_reads_orders_inquiries_and_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    api = "/external/v1"
    changed = {"lastChangeStatuses": [{"productOrderId": "2026111700000001"}]}
    detail = {
        "order": {
            "orderDate": "2026-11-17T10:00:00.000+09:00", "ordererId": "buyer", "ordererName": "김바다",
            "ordererTel": "01000000000",
        },
        "productOrder": {
            "productOrderId": "2026111700000001", "productName": "머그컵", "productOrderStatus": "PAYED",
            "quantity": 1, "totalPaymentAmount": 24000, "shippingAddress": {"baseAddress": "순천시"},
        },
    }
    inquiry = {
        "inquiryNo": 3, "title": "배송 문의", "inquiryContent": "언제 오나요?", "answered": False,
        "inquiryRegistrationDateTime": "2026-11-17T11:00:00.000+09:00", "orderId": "1",
        "customerId": "buyer", "customerName": "김바다",
    }
    question = {"questionId": 4, "question": "크기는요?", "createDate": "2026-11-17T12:00:00.000+09:00"}
    net = FakeNetwork({
        f"{api}/oauth2/token": json_reply({"access_token": "synthetic-access"}),
        f"{api}/pay-order/seller/product-orders/last-changed-statuses": json_reply({"data": changed}),
        f"{api}/pay-order/seller/product-orders/query": json_reply({"data": [detail]}),
        f"{api}/pay-user/inquiries": json_reply({"content": [inquiry], "last": True}),
        f"{api}/contents/qnas": json_reply({"contents": [question], "last": True}),
    })
    items = await store(monkeypatch, net).collect(WINDOW)
    assert [item.external_id for item in items] == ["order:2026111700000001", "inquiry:3", "qna:4"]
    assert "01000000000" not in str(items)
    assert "순천시" not in str(items)
    assert "abcdefghijklmnopqrstuv" not in net.requests[0].content.decode()
    assert all(
        request.headers["authorization"] == "Bearer synthetic-access" for request in net.requests[1:]
    )
    assert {request.headers["user-agent"] for request in net.requests} == {USER_AGENT}


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_smartstore_refused_credentials_need_connection(
    monkeypatch: pytest.MonkeyPatch, status: int,
) -> None:
    net = FakeNetwork({"/external/v1/oauth2/token": json_reply({"code": "BadRequest"}, status)})
    with pytest.raises(NeedsConnectionError):
        _ = await store(monkeypatch, net).collect(WINDOW)
