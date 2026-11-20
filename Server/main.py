# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi>=0.121", "uvicorn>=0.30", "httpx>=0.27", "alembic>=1.14", "tzdata>=2025.1",
#     "sqlalchemy[asyncio]>=2.0,<2.1", "asyncpg>=0.30", "anyio>=4",
# ]
# ///
"""Roundup API server: the iOS app calls this server; only this server holds NCP keys."""

import hmac
import re
from typing import Annotated, Final, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from activities import router as activity_router
from assistant import build_context
from bookings import router as booking_router
from channels import router as channel_router
from common import Now, Session
from contracts import Card
from database import database_lifespan, schema_is_current
from details import router as detail_router
from drafts import router as draft_router
from inquiries import router as inquiry_router
from observability import RequestBoundary, configure_logging
from operations import router as operations_router
from orders import router as order_router
from providers import chat, geocode_address, require_env, static_map_image, transcribe
from recommendations import router as recommendation_router
from schedule import router as schedule_router
from shipments import router as shipment_router
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
for router in (
    inquiry_router, today_router, booking_router, order_router, shipment_router, channel_router,
    task_router, recommendation_router, schedule_router, operations_router, workshop_router,
    detail_router, draft_router, undo_router, activity_router,
):
    app.include_router(router)


class DraftRequest(BaseModel):
    """Inquiry fields used to write a reply draft."""

    customer: str = Field(max_length=200)
    subject: str = Field(max_length=200)
    question: str = Field(max_length=4000)
    facts: list[str] = Field(max_length=30)


class DraftResponse(BaseModel):
    """Generated reply draft."""

    draft: str


class AskRequest(BaseModel):
    """Owner question; workshop facts are always loaded by the server."""

    question: str = Field(min_length=1, max_length=1000)


class AskResponse(BaseModel):
    """Assistant answer and the cards it names, so the owner can act on them."""

    answer: str
    items: list[Card] = Field(default_factory=list)


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


@app.post("/draft")
async def draft(body: DraftRequest) -> DraftResponse:
    """Write a reply draft from the facts on the inquiry."""
    system = (
        "당신은 공방이 손님에게 보내는 답장 초안을 써요. 공방이 직접 말하는 1인칭으로 쓰고, "
        "'사장님께 문의하신 뒤'처럼 사장님을 3인칭으로 부르지 않아요. "
        "아래 '공방 안내'에 있는 사실만 근거로 2~4문장을 써요. "
        "모든 문장은 해요체로 끝내요(예: ~있어요, ~드릴게요, ~해 주세요). "
        "'~습니다', '~입니다' 같은 합쇼체는 쓰지 않아요. "
        "마크다운이나 별표 없이 평범한 문장으로만 써요. "
        "안내에 없는 내용은 추측하지 말고 '확인해서 다시 알려드릴게요'라고 써요. "
        "예약 확정이나 결제를 약속하지 않아요."
    )
    user = (
        "공방 안내:\n" + "\n".join(f"- {fact}" for fact in body.facts)
        + f"\n\n손님: {body.customer}\n제목: {body.subject}\n문의: {body.question}"
    )
    return DraftResponse(draft=await chat(system, user, 0.3))


ASK_ITEM_LIMIT: Final = 3
QUOTES: Final = "'\"\u2018\u2019\u201c\u201d"
# Only paired emphasis around real words; masked text such as ***-****-**** stays as written.
EMPHASIS: Final = re.compile(
    rf"[{QUOTES}]?(?<![*_])(\*\*|__)(?=[^\s*_])([^*_\n]+?)(?<=[^\s*_])\1(?![*_])[{QUOTES}]?",
)


def plain_answer(text: str) -> str:
    """Strip markdown the model sometimes adds; the app shows plain sentences."""
    text = EMPHASIS.sub(r"\2", text)
    text = re.sub(r"^\s*(#+|[-*•])\s+", "", text, flags=re.MULTILINE)
    return text.strip()


@app.post("/ask")
async def ask(body: AskRequest, now: Now) -> AskResponse:
    """Answer from facts read from PostgreSQL for this request."""
    system = (
        "당신은 작은 공방 사장님의 업무 비서예요. "
        "아래 '현재 공방 현황'에 있는 사실만 근거로 1~4문장으로 짧게 답해요. "
        "모든 문장은 해요체로 끝내요(예: ~있어요, ~해요, ~해 주세요). "
        "'~습니다', '~입니다' 같은 합쇼체는 쓰지 않아요. "
        "마크다운, 별표, 따옴표 강조, 목록 기호 없이 평범한 문장으로만 써요. "
        "'기한 지남'으로 표시된 발송 건은 수거를 놓친 것이니 오늘 수거할 건과 나눠서 말해요. "
        "현황에 없는 내용은 추측하지 말고 '지금 데이터로는 알 수 없어요'라고 답해요. "
        "예약 변경, 답변 발송, 결제 같은 일을 했다고 말하지 않아요. "
        "필요하면 사장님이 해당 화면에서 처리하도록 안내해요."
    )
    context, cards = await build_context(now)
    user = "현재 공방 현황:\n" + "\n".join(f"- {line}" for line in context) + f"\n\n질문: {body.question}"
    answer = plain_answer(await chat(system, user, 0.2))
    # One card per named product: a parcel to send comes before the order it belongs to.
    named = list({card.title: card for card in reversed(cards) if card.title in answer}.values())[::-1]
    return AskResponse(answer=answer, items=named[:ASK_ITEM_LIMIT])


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
