"""Structured logs and request boundaries implemented as one ASGI middleware."""

import json
import logging
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from os import environ
from time import perf_counter
from typing import Final, override
from uuid import uuid4

from fastapi import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

type JsonValue = str | int | float | bool | None

LOGGER: Final = logging.getLogger("roundup.http")
MAX_JSON_BYTES: Final = 64 * 1024
MAX_AUDIO_BYTES: Final = 2 * 1024 * 1024
MAX_FILE_BYTES: Final = 2 * 1024 * 1024
INVOICE_ROUTES: Final = "/agent/invoices/"
AGENT_ROUTES: Final = "/agent/"
AGENT_UNAVAILABLE: Final = "잠깐 문제가 생겼어요. 조금 있다가 한 번 더 해 주세요."
AGENT_ERRORS: Final[Mapping[int, str]] = {
    401: "앱 연결 정보가 맞지 않아요. 연결 설정을 살펴봐 주세요.",
    404: "찾으시는 게 없어요.",
    409: "그새 바뀐 게 있어요. 새로고침해서 봐 주세요.",
    413: "용량이 너무 커서 못 받았어요.",
    422: "적으신 내용에 틀린 데가 있어요. 한 번 더 봐 주세요.",
}
LOG_FIELDS: Final = (
    "request_id", "method", "route", "status", "duration_ms", "error_type", "upstream_status",
    "intent", "intent_source", "confidence", "source", "collected", "inserted", "mapped",
)


class BodyTooLargeError(HTTPException):
    """The streamed request body passed its route limit; FastAPI passes only HTTP errors through."""

    def __init__(self) -> None:
        """Answer 413 wherever the body is read."""
        super().__init__(413, "request body too large")


class JsonFormatter(logging.Formatter):
    """Write allow-listed fields so request data cannot enter logs by accident."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, JsonValue] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = record.__dict__
        entry.update({name: fields[name] for name in LOG_FIELDS if name in fields})
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> None:
    """Send application logs to stdout; httpx request lines are off because they hold query tokens."""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("roundup")
    logger.handlers[:] = [handler]
    logger.setLevel(environ.get("ROUNDUP_LOG_LEVEL", "INFO").upper())
    logger.propagate = False


def body_limit(path: str) -> int:
    """Allow audio on the speech route and a carrier file on the invoice routes."""
    if path == "/stt":
        return MAX_AUDIO_BYTES
    return MAX_FILE_BYTES if path.startswith(INVOICE_ROUTES) else MAX_JSON_BYTES


def public_detail(path: str, status: int, detail: str) -> str:
    """Answer agent routes in Korean: shared English errors are replaced, a route's own words are kept."""
    if not path.startswith(AGENT_ROUTES) or not detail.isascii():
        return detail
    return AGENT_ERRORS.get(status, AGENT_UNAVAILABLE)


def declared_length(request: Request) -> int:
    """Read Content-Length; malformed values are left to the size counter."""
    value = request.headers.get("content-length", "0")
    return int(value) if value.isdecimal() else 0


async def send_json(send: Send, status: int, detail: str) -> None:
    """Send a small generic JSON error."""
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start", "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


class Exchange:
    """Mutable per-request state: bytes received and the response status."""

    def __init__(self, receive: Receive, send: Send, path: str) -> None:
        """Wrap one connection's channels."""
        self.upstream_receive: Receive = receive
        self.upstream_send: Send = send
        self.path: str = path
        self.limit: int = body_limit(path)
        self.received: int = 0
        self.status: int = 500
        self.response_started: bool = False

    async def receive(self) -> Message:
        """Count body bytes as the application reads them."""
        message = await self.upstream_receive()
        match message:
            case {"body": bytes() as body}:
                self.received += len(body)
            case _:
                pass
        if self.received > self.limit:
            raise BodyTooLargeError
        return message

    async def send(self, message: Message) -> None:
        """Remember the status the client receives; agent answers are never stored by a cache."""
        if message["type"] == "http.response.start":
            self.response_started = True
            self.status = message["status"]
            if self.path.startswith(AGENT_ROUTES):
                MutableHeaders(scope=message)["cache-control"] = "no-store"
        await self.upstream_send(message)

    async def fail(self, status: int, detail: str) -> None:
        """Replace an unstarted response with a generic error."""
        if not self.response_started:
            await send_json(self.send, status, detail)


class RequestBoundary:
    """Limit bodies, redact unexpected failures, and log one line per request."""

    def __init__(self, app: ASGIApp, check_key: Callable[[str], None]) -> None:
        """Wrap the next ASGI application; agent routes check the key before any body is read."""
        self.app: ASGIApp = app
        self.check_key: Callable[[str], None] = check_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        started = perf_counter()
        exchange = Exchange(receive, send, request.url.path)
        error_type: str | None = None
        try:
            if exchange.path.startswith(AGENT_ROUTES):
                self.check_key(request.headers.get("x-roundup-key", ""))
            if declared_length(request) > exchange.limit:
                raise BodyTooLargeError  # noqa: TRY301
            await self.app(scope, exchange.receive, exchange.send)
        except HTTPException as error:
            detail = public_detail(exchange.path, error.status_code, error.detail)
            await exchange.fail(error.status_code, detail)
        except Exception as error:  # noqa: BLE001 - last boundary: log the type, return a generic body.
            error_type = type(error).__name__
            await exchange.fail(500, public_detail(exchange.path, 500, "internal server error"))
        LOGGER.info("http_request", extra={
            "request_id": uuid4().hex,
            "method": request.method,
            "route": str(getattr(scope.get("route"), "path", "unmatched")),
            "status": exchange.status,
            "duration_ms": round((perf_counter() - started) * 1000, 1),
            "error_type": error_type,
        })
