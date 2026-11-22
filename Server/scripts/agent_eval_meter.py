"""Count what a live evaluation costs and let it reach only the model endpoint."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import httpx
from fastapi import HTTPException
from pydantic import JsonValue, TypeAdapter

import providers

type Send = Callable[[httpx.Request, str | None], Awaitable[httpx.Response]]

MODEL_HOST: Final = httpx.URL(providers.CLOVA_URL).host
JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class CapReachedError(Exception):
    """The call or token cap would be exceeded by the next model call."""


@dataclass(slots=True)
class Meter:
    """Count model calls and tokens; once a cap is reached the next call is refused."""

    max_calls: int
    max_tokens: int
    calls: int = 0
    tokens: int = 0
    capped: bool = False

    def admit(self) -> None:
        """Refuse the next call at the cap."""
        if self.calls >= self.max_calls or self.tokens >= self.max_tokens:
            self.capped = True
            raise CapReachedError

    def add(self, tokens: int) -> None:
        """Count one finished call."""
        self.calls += 1
        self.tokens += tokens


def tokens_in(value: JsonValue) -> int:
    """Find the first totalTokens number in a model response."""
    if isinstance(value, dict):
        total = value.get("totalTokens")
        if isinstance(total, int):
            return total
        return next((found for child in value.values() if (found := tokens_in(child))), 0)
    if isinstance(value, list):
        return next((found for child in value if (found := tokens_in(child))), 0)
    return 0


def metered_send(original: Send, meter: Meter) -> Send:
    """Wrap the one outbound HTTP function: model host only, every call counted and capped."""

    async def send(request: httpx.Request, denied: str | None = None) -> httpx.Response:
        if request.url.host != MODEL_HOST:
            message = f"only the model endpoint may be reached, not {request.url.host}"
            raise HTTPException(502, message)
        meter.admit()
        response = await original(request, denied)
        meter.add(tokens_in(JSON.validate_json(response.content)))
        return response

    return send


def canned_send(original: Send, meter: Meter) -> Send:
    """Answer every outbound request with a short Korean line and no network."""
    del original, meter
    body = {"result": {"message": {"content": "확인했어요."}, "usage": {"totalTokens": 0}}}

    async def send(request: httpx.Request, denied: str | None = None) -> httpx.Response:
        del denied
        return httpx.Response(200, json=body, request=request)

    return send
