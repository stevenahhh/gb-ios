"""Structured logs and request boundaries implemented as one ASGI middleware."""

import json
import logging
import sys
from datetime import UTC, datetime
from os import environ
from time import perf_counter
from typing import Final, override
from uuid import uuid4

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

type JsonValue = str | int | float | bool | None

LOGGER: Final = logging.getLogger("roundup.http")
MAX_JSON_BYTES: Final = 64 * 1024
MAX_AUDIO_BYTES: Final = 2 * 1024 * 1024
LOG_FIELDS: Final = (
    "request_id", "method", "route", "status", "duration_ms", "error_type", "upstream_status",
    "intent", "intent_source", "confidence",
)


class BodyTooLargeError(Exception):
    """The streamed request body passed its route limit."""


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
    """Send application logs to stdout for the service manager."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("roundup")
    logger.handlers[:] = [handler]
    logger.setLevel(environ.get("ROUNDUP_LOG_LEVEL", "INFO").upper())
    logger.propagate = False


def body_limit(path: str) -> int:
    """Allow audio only on the speech route."""
    return MAX_AUDIO_BYTES if path == "/stt" else MAX_JSON_BYTES


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

    def __init__(self, receive: Receive, send: Send, limit: int) -> None:
        """Wrap one connection's channels."""
        self.upstream_receive: Receive = receive
        self.upstream_send: Send = send
        self.limit: int = limit
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
        """Remember the status the client receives."""
        if message["type"] == "http.response.start":
            self.response_started = True
            self.status = message["status"]
        await self.upstream_send(message)

    async def fail(self, status: int, detail: str) -> None:
        """Replace an unstarted response with a generic error."""
        if not self.response_started:
            await send_json(self.send, status, detail)


class RequestBoundary:
    """Limit bodies, redact unexpected failures, and log one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next ASGI application."""
        self.app: ASGIApp = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        started = perf_counter()
        limit = body_limit(request.url.path)
        exchange = Exchange(receive, send, limit)
        error_type: str | None = None
        try:
            if declared_length(request) > limit:
                raise BodyTooLargeError  # noqa: TRY301
            await self.app(scope, exchange.receive, exchange.send)
        except BodyTooLargeError:
            await exchange.fail(413, "request body too large")
        except Exception as error:  # noqa: BLE001 - last boundary: log the type, return a generic body.
            error_type = type(error).__name__
            await exchange.fail(500, "internal server error")
        LOGGER.info("http_request", extra={
            "request_id": uuid4().hex,
            "method": request.method,
            "route": str(getattr(scope.get("route"), "path", "unmatched")),
            "status": exchange.status,
            "duration_ms": round((perf_counter() - started) * 1000, 1),
            "error_type": error_type,
        })
