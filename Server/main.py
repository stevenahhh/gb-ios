# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi>=0.121", "uvicorn>=0.30", "httpx>=0.27", "alembic>=1.14", "tzdata>=2025.1",
#     "sqlalchemy[asyncio]>=2.0,<2.1", "asyncpg>=0.30", "anyio>=4",
# ]
# ///
"""Roundup API server: the iOS app calls this server; only this server holds NCP keys."""

import hmac
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from activities import router as activity_router
from ai import router as ai_router
from b_k06 import router as k06_router
from bookings import router as booking_router
from channels import router as channel_router
from common import Session
from database import database_lifespan, schema_is_current
from details import router as detail_router
from drafts import router as draft_router
from inquiries import router as inquiry_router
from observability import RequestBoundary, configure_logging
from operations import router as operations_router
from orders import router as order_router
from providers import geocode_address, require_env, static_map_image, transcribe
from recommendations import router as recommendation_router
from schedule import router as schedule_router
from shipments import router as shipment_router
from speech import router as speech_router
from tasks import router as task_router
from today import router as today_router
from undo import router as undo_router
from workshop import router as workshop_router


def require_api_key(x_roundup_key: Annotated[str, Header()] = "") -> None:
    """Compare the shared key in constant time."""
    expected = require_env("ROUNDUP_API_KEY")
    if not hmac.compare_digest(x_roundup_key.encode(), expected.encode()):
        raise HTTPException(401, "invalid api key")


configure_logging()
app = FastAPI(
    title="Roundup API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    dependencies=[Depends(require_api_key)],
    lifespan=database_lifespan,
)
app.add_middleware(RequestBoundary)
app.include_router(k06_router)  # first, so /class-sessions/under-min is not read as a class id
for router in (
    inquiry_router, today_router, booking_router, order_router, shipment_router, channel_router,
    task_router, recommendation_router, schedule_router, operations_router, workshop_router,
    detail_router, draft_router, undo_router, ai_router, activity_router, speech_router,
):
    app.include_router(router)


class Health(BaseModel):
    """Liveness response."""

    status: Literal["ok"] = "ok"


class Ready(BaseModel):
    """A successful database and schema readiness response."""

    status: Literal["ready"] = "ready"


class Transcript(BaseModel):
    """Speech recognition result."""

    text: str


class Place(BaseModel):
    """A confirmed road address."""

    address: str
    lat: float
    lng: float


@app.get("/health")
async def health() -> Health:
    """Report process liveness."""
    return Health()


@app.get("/health/ready")
async def ready(db: Session) -> Ready:
    """Require connectivity and the schema version shipped with this release."""
    if not await schema_is_current(db):
        raise HTTPException(503, "service unavailable")
    return Ready()


@app.post("/stt")
async def stt(request: Request) -> Transcript:
    """Transcribe recorded Korean speech."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty audio")
    return Transcript(text=await transcribe(audio))


@app.get("/geocode")
async def geocode(query: Annotated[str, Query(min_length=1, max_length=200)]) -> Place:
    """Resolve a road address."""
    match = await geocode_address(query)
    if match is None:
        raise HTTPException(404, "address not found")
    return Place(address=match.roadAddress, lat=match.y, lng=match.x)


@app.get("/staticmap")
async def static_map(
    lat: Annotated[float, Query(ge=-90, le=90)], lng: Annotated[float, Query(ge=-180, le=180)],
    w: Annotated[int, Query(ge=1, le=1024)] = 600, h: Annotated[int, Query(ge=1, le=1024)] = 300,
) -> Response:
    """Return a map image for a coordinate."""
    return Response(await static_map_image(lat, lng, (w, h)), media_type="image/jpeg")
