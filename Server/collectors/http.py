"""Outbound HTTP for collectors: one honest User-Agent, rate limit, bounded retries, and bounded bodies."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Final

import anyio
import httpx
from pydantic import BaseModel, ValidationError

PRODUCT: Final = "GongdoriCollector"
USER_AGENT: Final = f"{PRODUCT}/0.1"
TIMEOUT: Final = httpx.Timeout(15.0)
MAX_BYTES: Final = 4 * 1024 * 1024
ATTEMPTS: Final = 3
MAX_RETRY_AFTER: Final = 10.0
OK: Final = 200
TOO_MANY: Final = 429
SERVER_ERROR: Final = 500
type Sleep = Callable[[float], Awaitable[None]]


class SourceError(Exception):
    """A temporary upstream failure; the code holds no URL, body, or credential."""

    def __init__(self, code: str) -> None:
        """Keep a short code for the run record."""
        super().__init__(code)
        self.code: str = code


@dataclass(frozen=True, slots=True)
class Reply:
    """A complete, size-limited response."""

    status: int
    content: bytes

    def expect_ok(self) -> bytes:
        """Return the body of a successful response."""
        if self.status != OK:
            code = f"http_{self.status}"
            raise SourceError(code)
        return self.content


def parsed[T: BaseModel](model: type[T], content: bytes) -> T:
    """Parse an upstream body at the trust boundary."""
    try:
        return model.model_validate_json(content)
    except ValidationError:
        code = "malformed"
        raise SourceError(code) from None


def retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """Back off exponentially, or as long as the server asks within a limit."""
    headers = response.headers if response is not None else httpx.Headers()
    asked = headers["retry-after"] if "retry-after" in headers else ""  # noqa: SIM401 - get() is untyped.
    return min(float(asked), MAX_RETRY_AFTER) if asked.isdecimal() else float(1 << attempt)


@dataclass(slots=True)
class HttpSession:
    """Requests of one run, spaced by the source's minimum interval."""

    client: httpx.AsyncClient
    sleep: Sleep
    clock: Callable[[], float]
    gap: float
    last: float | None = None

    async def send(self, request: httpx.Request) -> Reply:
        """Send with spacing; retry connection failures, 429, and 5xx, then give up."""
        code = "network"
        for attempt in range(ATTEMPTS):
            await self.wait_turn()
            response: httpx.Response | None = None
            try:
                response = await self.client.send(request, stream=True)
                if response.status_code != TOO_MANY and response.status_code < SERVER_ERROR:
                    return Reply(response.status_code, await self.body(response))
                code = f"http_{response.status_code}"
            except httpx.HTTPError:
                code = "network"
            finally:
                if response is not None:
                    await response.aclose()
            if attempt + 1 < ATTEMPTS:
                await self.sleep(retry_delay(attempt, response))
        raise SourceError(code)

    async def get(self, url: str, params: dict[str, str] | None = None, bearer: str | None = None) -> Reply:
        """Send a GET request."""
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        return await self.send(self.client.build_request("GET", url, params=params, headers=headers))

    async def wait_turn(self) -> None:
        """Keep the source's minimum interval between requests."""
        if self.last is not None:
            remaining = self.gap - (self.clock() - self.last)
            if remaining > 0:
                await self.sleep(remaining)
        self.last = self.clock()

    async def body(self, response: httpx.Response) -> bytes:
        """Read a body and stop at the size limit."""
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks += chunk
            if len(chunks) > MAX_BYTES:
                code = "too_large"
                raise SourceError(code)
        return bytes(chunks)


@dataclass(frozen=True, slots=True)
class Gateway:
    """How collectors reach the network; tests replace only the transport and the clock."""

    transport: httpx.AsyncBaseTransport | None = None
    sleep: Sleep = anyio.sleep
    clock: Callable[[], float] = monotonic

    @asynccontextmanager
    async def connect(self, min_interval: float) -> AsyncGenerator[HttpSession]:
        """Open a client that never follows redirects to a host nobody checked."""
        async with httpx.AsyncClient(
            transport=self.transport, timeout=TIMEOUT, follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            yield HttpSession(client, self.sleep, self.clock, min_interval)
