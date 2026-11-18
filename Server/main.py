# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi>=0.121", "uvicorn>=0.30", "httpx>=0.27",
#     "sqlalchemy[asyncio]>=2.0,<2.1", "asyncpg>=0.30", "anyio>=4",
# ]
# ///
"""Roundup API server: the iOS app calls this server; only this server holds NCP keys."""
import hmac
import os

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from database import database_lifespan
from inquiries import router as inquiry_router

CLOVA_URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005"
CSR_URL = "https://naveropenapi.apigw.ntruss.com/recog/v1/stt"
GEOCODE_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
STATIC_MAP_URL = "https://maps.apigw.ntruss.com/map-static/v2/raster"
TIMEOUT = httpx.Timeout(20.0)

def key(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HTTPException(503, f"{name} is not configured on the server")
    return value


def require_api_key(x_roundup_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_roundup_key, key("ROUNDUP_API_KEY")):
        raise HTTPException(401, "invalid api key")


app = FastAPI(
    title="Roundup API",
    dependencies=[Depends(require_api_key)],
    lifespan=database_lifespan,
)
app.include_router(inquiry_router)


def maps_headers() -> dict[str, str]:
    return {
        "x-ncp-apigw-api-key-id": key("NCP_MAPS_CLIENT_ID"),
        "x-ncp-apigw-api-key": key("NCP_MAPS_CLIENT_SECRET"),
    }


async def call(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as error:
        raise HTTPException(502, f"NCP request failed: {type(error).__name__}") from error
    if response.status_code != 200:
        raise HTTPException(502, f"NCP returned {response.status_code}")
    return response


class DraftRequest(BaseModel):
    customer: str
    subject: str
    question: str
    facts: list[str]


class DraftResponse(BaseModel):
    draft: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/draft")
async def draft(body: DraftRequest) -> DraftResponse:
    system = (
        "당신은 작은 공방 사장님의 답변 초안을 쓰는 비서입니다. "
        "아래 '공방 안내'에 있는 사실만 근거로 2~4문장의 정중한 존댓말 답변을 씁니다. "
        "안내에 없는 내용은 추측하지 말고 '사장님이 확인 후 안내드리겠습니다'라고 씁니다. "
        "예약 확정이나 결제를 약속하지 않습니다."
    )
    user = (
        "공방 안내:\n" + "\n".join(f"- {fact}" for fact in body.facts)
        + f"\n\n손님: {body.customer}\n제목: {body.subject}\n문의: {body.question}"
    )
    response = await call(
        "POST", CLOVA_URL,
        headers={"Authorization": f"Bearer {key('CLOVA_STUDIO_API_KEY')}"},
        json={
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "maxTokens": 300,
            "temperature": 0.3,
        },
    )
    text = response.json()["result"]["message"]["content"].strip()
    return DraftResponse(draft=text)


class AskRequest(BaseModel):
    question: str
    context: list[str]


@app.post("/ask")
async def ask(body: AskRequest) -> dict[str, str]:
    system = (
        "당신은 작은 공방 사장님의 업무 비서입니다. "
        "아래 '현재 공방 현황'에 있는 사실만 근거로 1~4문장으로 짧게 답합니다. "
        "현황에 없는 내용은 추측하지 말고 '지금 데이터로는 알 수 없어요'라고 답합니다. "
        "예약 변경, 답변 발송, 결제 같은 일을 했다고 말하지 않습니다. 필요하면 사장님이 해당 화면에서 처리하도록 안내합니다."
    )
    user = "현재 공방 현황:\n" + "\n".join(f"- {line}" for line in body.context) + f"\n\n질문: {body.question}"
    response = await call(
        "POST", CLOVA_URL,
        headers={"Authorization": f"Bearer {key('CLOVA_STUDIO_API_KEY')}"},
        json={
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "maxTokens": 300,
            "temperature": 0.2,
        },
    )
    return {"answer": response.json()["result"]["message"]["content"].strip()}


@app.post("/stt")
async def stt(request: Request) -> dict[str, str]:
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty audio")
    response = await call(
        "POST", CSR_URL, params={"lang": "Kor"},
        headers={
            "X-NCP-APIGW-API-KEY-ID": key("NCP_CSR_CLIENT_ID"),
            "X-NCP-APIGW-API-KEY": key("NCP_CSR_CLIENT_SECRET"),
            "Content-Type": "application/octet-stream",
        },
        content=audio,
    )
    return {"text": response.json().get("text", "")}


@app.get("/geocode")
async def geocode(query: str) -> dict[str, object]:
    response = await call("GET", GEOCODE_URL, params={"query": query}, headers=maps_headers())
    addresses = response.json().get("addresses", [])
    if not addresses:
        raise HTTPException(404, "address not found")
    first = addresses[0]
    return {"address": first["roadAddress"], "lat": float(first["y"]), "lng": float(first["x"])}


@app.get("/staticmap")
async def static_map(lat: float, lng: float, w: int = 600, h: int = 300) -> Response:
    response = await call(
        "GET", STATIC_MAP_URL,
        params={"w": w, "h": h, "center": f"{lng},{lat}", "level": 16, "scale": 2,
                "markers": f"type:d|size:mid|pos:{lng} {lat}"},
        headers=maps_headers(),
    )
    return Response(response.content, media_type="image/jpeg")
