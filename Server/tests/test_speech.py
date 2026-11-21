from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest
from httpx2 import AsyncClient

type Handler = Callable[[httpx.Request], httpx.Response]


def fake_clova_voice(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[httpx.Request]:
    sent: list[httpx.Request] = []
    real = httpx.AsyncClient

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    def client(**options: object) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(record), **options)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr("providers.httpx.AsyncClient", client)
    return sent


@pytest.mark.anyio
async def test_tts_reads_plain_text_with_the_configured_voice(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NCP_TTS_CLIENT_ID", "tts-id")
    monkeypatch.setenv("NCP_TTS_CLIENT_SECRET", "tts-secret")
    monkeypatch.delenv("TTS_SPEAKER", raising=False)
    sent = fake_clova_voice(monkeypatch, lambda _: httpx.Response(200, content=b"ID3-mp3"))

    response = await client.post("/tts", json={"text": "## 오늘 할 일\n- **머그컵 2종 세트** 포장"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3-mp3"
    [request] = sent
    assert str(request.url) == "https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts"
    assert request.headers["X-NCP-APIGW-API-KEY-ID"] == "tts-id"
    assert request.headers["X-NCP-APIGW-API-KEY"] == "tts-secret"
    form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
    assert form == {
        "speaker": "vyuna", "text": "오늘 할 일\n머그컵 2종 세트 포장", "format": "mp3",
        "speed": "0", "pitch": "0", "volume": "0",
    }


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["", "**  ** #", "가" * 2001])
async def test_tts_rejects_text_with_nothing_to_speak_or_too_long(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, text: str,
) -> None:
    sent = fake_clova_voice(monkeypatch, lambda _: httpx.Response(200, content=b"unused"))

    response = await client.post("/tts", json={"text": text})

    assert response.status_code == 422
    assert sent == []


@pytest.mark.anyio
@pytest.mark.parametrize(("upstream", "status"), [(401, 503), (403, 503), (500, 502)])
async def test_tts_reports_provider_failures(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, upstream: int, status: int,
) -> None:
    monkeypatch.delenv("NCP_TTS_CLIENT_ID", raising=False)
    monkeypatch.delenv("NCP_TTS_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("NCP_CSR_CLIENT_ID", "csr-id")
    monkeypatch.setenv("NCP_CSR_CLIENT_SECRET", "csr-secret")
    monkeypatch.setenv("TTS_SPEAKER", "nara")
    sent = fake_clova_voice(monkeypatch, lambda _: httpx.Response(upstream, json={"error": "denied"}))

    response = await client.post("/tts", json={"text": "안녕하세요"})

    assert response.status_code == status
    [request] = sent
    assert request.headers["X-NCP-APIGW-API-KEY-ID"] == "csr-id"
    assert parse_qs(request.content.decode())["speaker"] == ["nara"]
    if status == 503:
        assert "NAVER API app" in response.json()["detail"]
