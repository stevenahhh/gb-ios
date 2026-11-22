"""A scripted network for collectors; only the HTTP transport and the clock are replaced."""

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from collectors.http import Gateway

type Answer = Callable[[httpx.Request], httpx.Response]

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>손끝 공방</title>
<item><guid>https://feed.test/posts/2</guid><link>https://feed.test/posts/2</link>
<title><![CDATA[가을 컵 <b>소식</b>]]></title><author>maker</author>
<description><![CDATA[<p>새 컵이 나왔어요.</p><script>steal()</script>&lt;img onerror=x&gt;]]></description>
<pubDate>Tue, 17 Nov 2026 10:00:00 +0900</pubDate></item>
<item><guid>https://feed.test/posts/1</guid><link>javascript:alert(1)</link><title>첫 글</title>
<description>안녕하세요</description><pubDate>not a date</pubDate></item>
<item><title>식별자 없는 글</title></item>
</channel></rss>"""


@dataclass
class FakeNetwork:
    """Answers by path, records every request, and advances a fake clock instead of sleeping."""

    answers: dict[str, Answer] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)
    now: float = 0.0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.get(request.url.path)
        return answer(request) if answer else httpx.Response(404)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    @property
    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    @property
    def gateway(self) -> Gateway:
        return Gateway(httpx.MockTransport(self.handle), self.sleep, lambda: self.now)


def reply(status: int = 200, text: str = "") -> Answer:
    return lambda _request: httpx.Response(status, text=text)


def json_reply(body: object, status: int = 200) -> Answer:
    return lambda _request: httpx.Response(status, json=body)
