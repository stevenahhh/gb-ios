"""Outbound NCP calls; credentials stay in the server environment."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from os import environ
from typing import ClassVar, Final, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

CLOVA_URL: Final = "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005"
CSR_URL: Final = "https://naveropenapi.apigw.ntruss.com/recog/v1/stt"
GEOCODE_URL: Final = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
STATIC_MAP_URL: Final = "https://maps.apigw.ntruss.com/map-static/v2/raster"
TIMEOUT: Final = httpx.Timeout(20.0)
LOGGER: Final = logging.getLogger("roundup.providers")
UPSTREAM_FAILED: Final = "upstream service failed"
HTTP_OK: Final = 200
type ChatRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One turn sent to the chat model."""

    role: ChatRole
    content: str


@dataclass(frozen=True, slots=True)
class Sampling:
    """Per-endpoint generation settings."""

    temperature: float
    max_tokens: int


class ClovaMessage(BaseModel):
    """Assistant message in a CLOVA response."""

    content: str


class ClovaResult(BaseModel):
    """Result envelope in a CLOVA response."""

    message: ClovaMessage


class ClovaResponse(BaseModel):
    """Only the CLOVA fields this server uses."""

    result: ClovaResult


class SpeechResponse(BaseModel):
    """CSR transcription response."""

    text: str = ""


class GeocodeAddress(BaseModel):
    """One Maps geocoding match."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)
    roadAddress: str  # noqa: N815
    x: float
    y: float


class GeocodeResponse(BaseModel):
    """Maps geocoding matches."""

    addresses: list[GeocodeAddress] = []


def require_env(name: str) -> str:
    """Read a server credential without exposing which one is missing."""
    value = environ.get(name)
    if not value:
        LOGGER.error("configuration_missing")
        raise HTTPException(503, "service unavailable")
    return value


def maps_headers() -> dict[str, str]:
    """Build Maps credentials."""
    return {
        "x-ncp-apigw-api-key-id": require_env("NCP_MAPS_CLIENT_ID"),
        "x-ncp-apigw-api-key": require_env("NCP_MAPS_CLIENT_SECRET"),
    }


async def send(request: httpx.Request) -> httpx.Response:
    """Send one upstream request and hide provider failure details."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.send(request)
    except httpx.HTTPError as error:
        LOGGER.warning("upstream_failed", extra={"error_type": type(error).__name__})
        raise HTTPException(502, UPSTREAM_FAILED) from None
    if response.status_code != HTTP_OK:
        LOGGER.warning("upstream_rejected", extra={"upstream_status": response.status_code})
        raise HTTPException(502, UPSTREAM_FAILED)
    return response


def parsed[T: BaseModel](model: type[T], response: httpx.Response) -> T:
    """Parse an upstream body at the trust boundary."""
    try:
        return model.model_validate_json(response.content)
    except ValidationError as error:
        LOGGER.warning("upstream_malformed", extra={"error_type": type(error).__name__})
        raise HTTPException(502, UPSTREAM_FAILED) from None


async def chat(messages: Sequence[ChatMessage], sampling: Sampling) -> str:
    """Ask HyperCLOVA X for the next assistant turn."""
    response = await send(httpx.Request(
        "POST", CLOVA_URL,
        headers={"Authorization": f"Bearer {require_env('CLOVA_STUDIO_API_KEY')}"},
        json={
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "maxTokens": sampling.max_tokens,
            "temperature": sampling.temperature,
        },
    ))
    return parsed(ClovaResponse, response).result.message.content.strip()


async def transcribe(audio: bytes) -> str:
    """Convert Korean speech to text."""
    response = await send(httpx.Request(
        "POST", CSR_URL, params={"lang": "Kor"}, content=audio,
        headers={
            "X-NCP-APIGW-API-KEY-ID": require_env("NCP_CSR_CLIENT_ID"),
            "X-NCP-APIGW-API-KEY": require_env("NCP_CSR_CLIENT_SECRET"),
            "Content-Type": "application/octet-stream",
        },
    ))
    return parsed(SpeechResponse, response).text


async def geocode_address(query: str) -> GeocodeAddress | None:
    """Return the first Maps match."""
    response = await send(httpx.Request("GET", GEOCODE_URL, params={"query": query}, headers=maps_headers()))
    return next(iter(parsed(GeocodeResponse, response).addresses), None)


async def static_map_image(lat: float, lng: float, size: tuple[int, int]) -> bytes:
    """Render a small map around a coordinate."""
    response = await send(httpx.Request(
        "GET", STATIC_MAP_URL, headers=maps_headers(),
        params={
            "w": size[0], "h": size[1], "center": f"{lng},{lat}", "level": 16, "scale": 2,
            "markers": f"type:d|size:mid|pos:{lng} {lat}",
        },
    ))
    return response.content
