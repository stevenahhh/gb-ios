"""Nothing that names or reaches a customer may enter the model, a stored step or run, or a log line."""

# noqa: SIZE_OK
# One assigned file; the tables of written forms are data.

import json
import logging
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Final

import httpx
import pytest
from fastapi import HTTPException
from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agent_hcx import ModelUnavailableError
from agent_mask import Masker
from agent_tools import TOOLS
from agent_types import Outcome, Plan, TargetRef, ToolEnv
from agent_worker import run_tick
from ai import AskRequest, AskResponse
from b_k25_judgments import suggest_rule
from observability import JsonFormatter
from providers import ChatMessage, Sampling
from tests.agent_core_support import ask, chat_of, execute, rows, says, set_mode, wants
from tests.conftest import NOW

pytestmark = pytest.mark.anyio
NAME: Final = "김하늘"
PHONE: Final = "010-1234-5678"
EMAIL: Final = "haneul.kim@example.com"
ADDRESS: Final = "서울시 강남구 테헤란로 12"
ACCOUNT: Final = "국민은행 123456-01-123456"
RESIDENT: Final = "900101-1234567"
LAST_DIGITS: Final = 7
MASKER: Final = Masker.of([NAME, "남궁민수"])


def wide(text: str) -> str:
    """Write ASCII in full-width forms."""
    return "".join(chr(ord(char) + 0xFEE0) for char in text)


def arabic(text: str) -> str:
    """Write digits as Arabic-Indic digits."""
    return "".join(chr(0x0660 + int(char)) if char.isdigit() else char for char in text)


def folded(text: str) -> str:
    """Read through width, composition, invisible characters, spacing, and separators, as a person would."""
    kept = [
        char for char in unicodedata.normalize("NFKC", text)
        if unicodedata.category(char) not in {"Cf", "Pd", "Zs", "Cc"} and char not in "()."
    ]
    return unicodedata.normalize(
        "NFC", "".join(str(unicodedata.decimal(char, char)) for char in kept),
    ).casefold()


def exposes(text: str, secret: str) -> bool:
    """Tell whether a secret can still be read in a text."""
    return folded(secret) in folded(text)


async def leaks(engine: AsyncEngine, shown: str, *secrets: str) -> list[str]:
    """Name every sink that still holds one of the secrets; an empty sink fails because it proves nothing.

    An earlier draft may stay in undo_data for undo alone; its own test owns that.
    """
    sinks = {"model": shown}
    for table in ("agent_steps", "agent_runs"):
        found = await rows(engine, f"SELECT (to_jsonb(t) - 'undo_data')::text FROM {table} t")  # noqa: S608
        sinks[table] = "\n".join(str(row[0]) for row in found)
    assert all(sinks.values()), "every sink must have been written"
    return [
        f"{sink}: {secret}" for sink, text in sinks.items() for secret in secrets if exposes(text, secret)
    ]


# Text: every way a value is written.

PHONES: Final = {
    "dashes": PHONE, "together": "01012345678", "spaces": "010 1234 5678", "dots": "010.1234.5678",
    "country": "+82 10-1234-5678", "country-together": "+821012345678", "old-prefix": "011-234-5678",
    "spaced-dashes": "010 - 1234 - 5678", "double-spaces": "010  1234  5678", "parentheses": "(010)1234-5678",
    "country-zero": "+82 (0)10-1234-5678", "seoul": "02-123-4567", "seoul-together": "0212345678",
    "internet": "070-1234-5678", "safe-number": "0507-1234-5678",
    "full-width": wide(PHONE), "full-width-together": wide("01012345678"),
    "half-and-full": f"010-{wide('1234')}-5678",
    "arabic-digits": arabic(PHONE), "bold-digits": "".join(chr(0x1D7CE + int(c)) for c in "01012345678"),
    "no-break-hyphen": PHONE.replace("-", "\u2011"), "long-dash": PHONE.replace("-", "\u2013"),
    "no-break-space": PHONE.replace("-", "\u00a0"), "zero-width": PHONE.replace("-", "\u200b"),
    "zero-width-inside": "010-12\u200b34-5678", "soft-hyphen": PHONE.replace("-", "\u00ad"),
    "word-joiner": "\u2060".join("01012345678"), "line-break": "010-1234\n-5678",
}
EMAILS: Final = {
    "plain": EMAIL, "upper": EMAIL.upper(), "tag": "haneul+class@mail.example.co.kr",
    "full-width": wide(EMAIL),
    "wide-at": EMAIL.replace("@", "\uff20"), "zero-width": EMAIL.replace("@", "\u200b@"),
}
ADDRESSES: Final = {
    "road": (ADDRESS, "테헤란로 12"), "floor": (f"{ADDRESS} 3층", "테헤란로 12"),
    "unit-after-comma": (f"{ADDRESS}, 101동 1203호", "101동 1203호"),
    "province": ("경기도 성남시 분당구 판교역로 235", "판교역로 235"),
    "lot": ("부산 해운대구 우동 1408", "우동 1408"),
    "village": ("충남 홍성군 홍동면 운월리 368-1", "운월리 368-1"),
    "no-district": ("세종특별자치시 한누리대로 2130", "한누리대로 2130"),
    "no-break-space": (ADDRESS.replace(" ", "\u00a0"), "테헤란로 12"),
    "full-width": (f"서울시 강남구 테헤란로 {wide('12')}", "테헤란로 12"),
    "decomposed": (unicodedata.normalize("NFD", ADDRESS), "테헤란로 12"),
    "zero-width": (ADDRESS.replace("테헤란로", "테헤\u200b란로"), "테헤란로 12"),
}
ACCOUNTS: Final = {
    "kookmin": (ACCOUNT, "123456-01-123456"), "shinhan": ("신한 110-123-456789", "110-123-456789"),
    "kakao": ("카카오뱅크 3333-01-1234567", "3333-01-1234567"),
    "together": ("입금 계좌 농협 3021234567891", "3021234567891"),
    "full-width": (f"국민은행 {wide('123456-01-123456')}", "123456-01-123456"),
    "tracking-shaped": ("계좌번호는 3333-0112-3456", "3333-0112-3456"),
    "spaced": ("계좌 110 123 456789", "110123456789"),
}
RESIDENTS: Final = {
    "dash": RESIDENT, "together": "9001011234567", "spaces": "900101 - 1234567",
    "foreigner": "900101-5234567",
    "full-width": wide(RESIDENT), "no-break-hyphen": RESIDENT.replace("-", "\u2011"),
    "zero-width": RESIDENT.replace("-", "\u200b"),
}
NAMES: Final = {
    "particle": ("김하늘님이 오셨어요", NAME), "compound": ("남궁민수 고객", "남궁민수"),
    "space": ("김 하늘 님", NAME),
    "zero-width": ("김\u200b하늘", NAME), "decomposed": (unicodedata.normalize("NFD", NAME), NAME),
    "no-break-space": ("김\u00a0하늘", NAME), "quoted": (f"'{NAME}'", NAME),
}


@pytest.mark.parametrize("written", PHONES.values(), ids=PHONES.keys())
def test_a_phone_number_is_hidden_however_it_is_written(written: str) -> None:
    assert not exposes(MASKER.text(f"연락처는 {written} 입니다"), folded(written)[-LAST_DIGITS:])


@pytest.mark.parametrize("written", EMAILS.values(), ids=EMAILS.keys())
def test_an_email_is_hidden(written: str) -> None:
    assert not exposes(MASKER.text(f"메일은 {written} 이에요"), written)


@pytest.mark.parametrize(("written", "secret"), ADDRESSES.values(), ids=ADDRESSES.keys())
def test_an_address_is_hidden(written: str, secret: str) -> None:
    assert not exposes(MASKER.text(f"주소는 {written} 이에요"), secret)


@pytest.mark.parametrize(("written", "secret"), ACCOUNTS.values(), ids=ACCOUNTS.keys())
def test_an_account_number_is_hidden(written: str, secret: str) -> None:
    assert not exposes(MASKER.text(f"{written} 로 보내요"), secret)


@pytest.mark.parametrize("written", RESIDENTS.values(), ids=RESIDENTS.keys())
def test_a_resident_number_is_hidden(written: str) -> None:
    assert not exposes(MASKER.text(f"주민번호 {written} 예요"), folded(written)[-LAST_DIGITS:])


@pytest.mark.parametrize(("written", "secret"), NAMES.values(), ids=NAMES.keys())
def test_a_customer_name_is_hidden(written: str, secret: str) -> None:
    assert not exposes(MASKER.text(written), secret)


@pytest.mark.parametrize("kept", [
    "#1042", "1041번", "381234567890", "3812-3456-7890", "6012345678901", "010123456789",
    wide("381234567890"),
    "30,000원", "2026-11-20", "14:30",
])
def test_order_and_tracking_numbers_beside_personal_data_stay_readable(kept: str) -> None:
    assert exposes(MASKER.text(f"{NAME} {PHONE} 송장 {kept} 등록"), kept)


@pytest.mark.parametrize("kept", [
    "시간을 오후로 3시", "송장 6012345678901", "송장번호 9001011234567", "농협 택배 송장 381234567890",
    "은행 들렀다가 381234567890 보냈어", "계좌 확인하고 1040 포장", "\u2460 1:1 수업 \u00bd",
    "오늘 날씨 좋네요",
    "손글씨 수업", "새 고객님께 안내", "선생님 수업", "이 준비물", f"송장 {wide('3812-3456-7890')}",
])
def test_an_ordinary_sentence_stays_exactly_as_written(kept: str) -> None:
    assert Masker.of([NAME, "이준"]).text(kept) == kept


@pytest.mark.parametrize("word", [
    "고객", "손님", "구매자", "문의자", "주문자", "네이버 고객", "스마트스토어 고객", "고객님", "이",
])
def test_a_general_word_is_never_taken_for_a_name(word: str) -> None:
    sentence = f"{word} 응대와 {word} 안내"
    assert Masker.of([word]).text(sentence) == sentence


def test_a_name_beside_a_general_word_is_still_hidden() -> None:
    assert not exposes(Masker.of(["김하늘 고객"]).text("김하늘 고객 문의"), NAME)


@pytest.mark.parametrize(("turn", "hidden", "name"), [
    ("김 하늘 님 예약금", "김*늘", NAME), ("김\u200b하늘 예약금", "김*늘", NAME),
    (unicodedata.normalize("NFD", "김하늘 예약금"), "김*늘", NAME), ("황보라 님 두 명", "황*라", "황보라"),
])
def test_a_name_hidden_in_the_turn_goes_back_to_the_real_one(turn: str, hidden: str, name: str) -> None:
    assert hidden in MASKER.text(turn)
    assert MASKER.aliases(turn) == {hidden: name}


@pytest.mark.parametrize("secret", [NAME, PHONE, ADDRESS, EMAIL, "123456-01-123456", RESIDENT])
def test_personal_data_is_hidden_anywhere_in_a_long_text(secret: str) -> None:
    filler = "도자기 수업 안내 " * 3000
    shown = MASKER.text(f"{secret} {filler}{secret} {filler}주문 1040 송장 381234567890 {secret}")
    assert not exposes(shown, secret)
    assert "주문 1040 송장 381234567890" in shown


@pytest.mark.parametrize("args", [
    {"a": {"b": [{"c": [f"{NAME} {PHONE}"]}]}}, {"name": {"memo": f"{NAME} {PHONE}"}},
    {"customer": [NAME, [PHONE]]}, {f"{NAME} {PHONE}": "x"}, {"phone": 1012345678},
    {"note": {NAME: {PHONE: None}}},
], ids=["deep", "name-object", "name-list", "key", "integer", "nested-key"])
def test_stored_arguments_hide_personal_data_at_every_depth(args: dict[str, JsonValue]) -> None:
    stored = json.dumps(MASKER.args(args), ensure_ascii=False)
    assert [secret for secret in (NAME, PHONE, "1012345678") if exposes(stored, secret)] == []


# Runs: what the model is shown and what a run leaves behind.

SECRETS: Final = {
    "name": (NAME, NAME), "phone": (PHONE, PHONE), "phone-together": ("01012345678", "01012345678"),
    "phone-full-width": (wide(PHONE), PHONE), "email": (EMAIL, EMAIL), "address": (ADDRESS, "테헤란로 12"),
    "account": (ACCOUNT, "123456-01-123456"), "resident": (RESIDENT, RESIDENT),
}
INQUIRY: Final = (
    "INSERT INTO inquiries (id, customer, subject, question, facts, draft, status, revision)"
    " VALUES ('inquiry-pii', :customer, '문의', :question, '{}', '', 'pending', 0)"
)
by_secret = pytest.mark.parametrize(("written", "secret"), SECRETS.values(), ids=SECRETS.keys())


@pytest.fixture
async def database(database: AsyncEngine) -> AsyncEngine:
    """Switch the assistant on; a new schema leaves it off."""
    await set_mode(database, "auto")
    return database


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record what the plain model calls send, at the wire."""
    sent: list[str] = []

    async def send(request: httpx.Request) -> httpx.Response:
        sent.append("\n".join(turn["content"] for turn in json.loads(request.content)["messages"]))
        return httpx.Response(200, json={"result": {"message": {"content": "확인해서 다시 알려드릴게요."}}})

    monkeypatch.setenv("CLOVA_STUDIO_API_KEY", "synthetic")
    monkeypatch.setattr("providers.send", send)
    return sent


class Keep(logging.Handler):
    """Keep every record as the server writes it, as a plain formatter would, and raw."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.extend((JsonFormatter().format(record), logging.Formatter().format(record)))
        self.lines.append(str(record.__dict__))


@pytest.fixture
def logged() -> Iterator[list[str]]:
    """Record every log line of the server."""
    handler = Keep()
    loggers = [logging.getLogger("roundup"), logging.getLogger()]
    for logger in loggers:
        logger.addHandler(handler)
    yield handler.lines
    for logger in loggers:
        logger.removeHandler(handler)


@pytest.mark.postgres
@by_secret
async def test_the_owners_words_and_history_are_hidden(
    database: AsyncEngine, client: AsyncClient, written: str, secret: str,
) -> None:
    chat = chat_of(wants("mark_packed", order="1040"), says("확인했어요."))
    _ = await ask(
        client, chat, f"1040 포장 끝났어. 참고 {written}",
        history=[{"role": "assistant", "text": f"지난번 {written}"}],
    )
    assert await leaks(database, chat.shown(), secret) == []
    assert "1040" in chat.shown()


@pytest.mark.postgres
@by_secret
async def test_a_customers_words_in_a_tool_result_are_hidden(
    database: AsyncEngine, client: AsyncClient, written: str, secret: str,
) -> None:
    await execute(database, INQUIRY, customer=NAME, question=f"1042 주문인데 {written} 로 연락 주세요")
    chat = chat_of(wants("find_inquiries"), says("문의가 있어요."))
    _ = await ask(client, chat, "문의 보여줘")
    assert "1042 주문인데" in chat.shown()
    assert await leaks(database, chat.shown(), secret) == []


@pytest.mark.postgres
async def test_every_read_tool_hides_what_rows_hold(database: AsyncEngine, client: AsyncClient) -> None:
    await execute(
        database, "UPDATE calendar_events SET title = :words, detail = :words", words=f"상담 {NAME} {PHONE}",
    )
    await execute(
        database, "UPDATE tasks SET title = :words, detail = :words", words=f"연락 {NAME} {PHONE}",
    )
    await execute(database, "UPDATE settings_items SET body = :words", words=f"담당 {NAME} {PHONE}")
    await execute(
        database, "INSERT INTO agent_memories (id, kind, text, source_quote, created_at)"
        " VALUES ('memory-pii', 'fact', :words, :words, now())", words=f"단골 {NAME} {PHONE}",
    )
    chat = chat_of(
        wants("read_calendar", start="2026-11-16", end="2026-11-29"), wants("read_rules"), wants("recall"),
        says("봤어요."),
    )
    _ = await ask(client, chat, "일정이랑 규정 보여줘")
    for marker in ("연락 김*늘", "담당 김*늘", "단골 김*늘"):
        assert marker in chat.shown()
    assert await leaks(database, chat.shown(), NAME, PHONE) == []


@pytest.mark.postgres
async def test_a_writer_who_is_not_a_customer_yet_is_hidden(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    await execute(database, INQUIRY, customer="황보라", question="저는 황보라 예요. 수업 문의드려요")
    chat = chat_of(wants("find_inquiries"), says("문의가 있어요."))
    _ = await ask(client, chat, "문의 보여줘")
    assert "수업 문의드려요" in chat.shown()
    assert await leaks(database, chat.shown(), "황보라") == []


@pytest.mark.postgres
async def test_a_new_customer_the_owner_names_is_hidden(database: AsyncEngine, client: AsyncClient) -> None:
    chat = chat_of(wants("find_sessions"), says("어느 수업인가요?"))
    _ = await ask(client, chat, "황보라 님 토요일 수업 두 명 예약해줘")
    assert await leaks(database, chat.shown(), "황보라") == []


@pytest.mark.postgres
@pytest.mark.parametrize("kept", [9, 11])
async def test_a_phone_cut_by_a_clipped_inquiry_leaves_no_digits(
    database: AsyncEngine, client: AsyncClient, kept: int,
) -> None:
    await execute(database, INQUIRY, customer=NAME, question="가" * (199 - kept) + PHONE)
    chat = chat_of(wants("find_inquiries"), says("문의가 있어요."))
    _ = await ask(client, chat, "문의 보여줘")
    assert "가가가" in chat.shown()
    assert await leaks(database, chat.shown(), "010-1234") == []


@pytest.mark.postgres
async def test_a_phone_cut_by_a_clipped_rule_leaves_no_digits(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    await execute(database, "UPDATE settings_items SET body = :body", body="가" * 190 + PHONE)
    chat = chat_of(wants("read_rules"), says("봤어요."))
    _ = await ask(client, chat, "규정 보여줘")
    assert "가가가" in chat.shown()
    assert await leaks(database, chat.shown(), "010-1234") == []


@pytest.mark.postgres
async def test_a_phone_cut_by_an_evidence_excerpt_leaves_no_digits(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    chat = chat_of(wants("mark_packed", order="1040"), says("확인했어요."))
    body = await ask(client, chat, f"1040 포장 끝났어, 고객님 {PHONE}")
    assert body["steps"][0]["evidence"]
    assert await leaks(database, chat.shown(), "010-1234") == []


@pytest.mark.postgres
async def test_the_title_of_a_new_entry_is_hidden_in_every_record(
    database: AsyncEngine, client: AsyncClient,
) -> None:
    chat = chat_of(
        wants("add_event", title=f"{NAME} {PHONE} 상담", day="2026-11-20", time="15:00"), says("넣었어요."),
    )
    body = await ask(client, chat, f"금요일 3시에 {NAME} {PHONE} 상담 넣어줘")
    assert [step["decision"] for step in body["steps"]] == ["auto"]
    assert await leaks(database, chat.shown(), NAME, PHONE) == []


@pytest.mark.postgres
async def test_an_unknown_tool_name_is_hidden(database: AsyncEngine, client: AsyncClient) -> None:
    chat = chat_of(wants(f"call_{NAME}_{PHONE}"), says("할 수 없어요."))
    _ = await ask(client, chat, "전화해줘")
    assert await leaks(database, chat.shown(), NAME, PHONE) == []


async def replaced_draft(database: AsyncEngine, client: AsyncClient) -> tuple[str, str, str]:
    """Let the assistant replace a draft that holds personal data; return the run, step, and response."""
    await execute(database, "UPDATE content_drafts SET title = '가을 소식', status = 'draft'"
                  " WHERE id = (SELECT min(id) FROM content_drafts)")
    await execute(database, "UPDATE content_drafts SET body = :body", body=f"문의 {NAME} {PHONE}")
    chat = chat_of(wants("save_content_draft", draft="가을 소식", text="새 글"), says("저장했어요."))
    body = await ask(client, chat, "가을 소식 초안을 새 글로 바꿔줘")
    [step] = body["steps"]
    assert step["decision"] == "auto"
    assert await leaks(database, chat.shown(), NAME, PHONE) == []
    return body["runId"], step["id"], f"{body}"


async def undo_secrets(database: AsyncEngine) -> list[str]:
    """Name the secrets undo_data still holds."""
    held = "\n".join(str(row[0]) for row in await rows(database, "SELECT undo_data::text FROM agent_steps"))
    return [secret for secret in (NAME, PHONE) if exposes(held, secret)]


@pytest.mark.postgres
async def test_an_earlier_draft_serves_undo_only_and_is_cleared_after_it(
    database: AsyncEngine, client: AsyncClient, logged: list[str],
) -> None:
    run_id, step_id, shown = await replaced_draft(database, client)
    seen = [shown, (await client.get(f"/agent/runs/{run_id}")).text, (await client.get("/agent/runs")).text]
    undone = await client.post(f"/agent/steps/{step_id}/undo")
    assert undone.status_code == 200
    restored = await rows(database, "SELECT body FROM content_drafts WHERE title = '가을 소식'")
    assert restored == [(f"문의 {NAME} {PHONE}",)]
    everything = "\n".join([*seen, undone.text, *logged])
    assert [secret for secret in (NAME, PHONE) if exposes(everything, secret)] == []
    assert await undo_secrets(database) == []


@pytest.mark.postgres
async def test_an_earlier_draft_is_cleared_after_48_hours(database: AsyncEngine, client: AsyncClient) -> None:
    _ = await replaced_draft(database, client)
    await execute(database, "UPDATE agent_steps SET undo_until = undo_until - interval '49 hours'")
    _ = await ask(client, chat_of(says("네.")), "안녕")
    _ = await run_tick(NOW)
    assert await undo_secrets(database) == []


@pytest.mark.postgres
async def test_a_stored_plain_answer_is_hidden(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answered(body: AskRequest, now: datetime) -> AskResponse:
        del body, now
        return AskResponse(answer=f"{NAME} 님 번호는 {PHONE} 이에요.", intent="lookup")

    monkeypatch.setattr("agent_run.ask", answered)
    chat = chat_of(wants("find_orders"), ModelUnavailableError())
    body = await ask(client, chat, "번호 알려줘")
    assert body["status"] == "fallback"
    assert await leaks(database, chat.shown(), NAME, PHONE) == []


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("written", "secret"), list(SECRETS.values())[1:], ids=list(SECRETS)[1:],
)
async def test_the_plain_answer_model_is_shown_no_contact(
    database: AsyncEngine, client: AsyncClient, wire: list[str], written: str, secret: str,
) -> None:
    # Names stay for now: the plain answer's own context still holds them, and the owner decides about that.
    body = await ask(
        client, chat_of(ModelUnavailableError()), f"1040 주문 {written} 상황 알려줘",
        history=[{"role": "owner", "text": f"지난번 {written}"}],
    )
    assert body["status"] == "fallback"
    assert "1040" in "\n".join(wire)
    assert not exposes("\n".join(wire), secret)


@pytest.mark.postgres
@by_secret
async def test_the_reply_model_is_shown_no_personal_data(
    database: AsyncEngine, client: AsyncClient, wire: list[str], written: str, secret: str,
) -> None:
    await execute(database, INQUIRY, customer=NAME, question=f"도자기 수업인데 {written} 로 연락 주세요")
    body = await ask(
        client, chat_of(wants("save_reply_draft", inquiry="문의"), says("저장했어요.")),
        "문의 답장 초안 써줘",
    )
    assert [step["decision"] for step in body["steps"]] == ["auto"]
    assert "도자기 수업인데" in "\n".join(wire)
    # The engine asks with a name from its fixed prompt example, so only the question is searched.
    asked = "\n".join(line for text in wire for line in text.splitlines() if "도자기 수업인데" in line)
    assert not exposes(asked, secret)


# The owner's own answers are workshop facts: only a phone number is hidden in them.

OWNER_ANSWER: Final = f"{ADDRESS} 건물 뒤 주차장이에요 {PHONE}"
OWNER_FACT: Final = f"{ADDRESS} 건물 뒤 주차장"


def answering(monkeypatch: pytest.MonkeyPatch, target: str, reply: dict[str, str]) -> list[str]:
    """Answer one K25 model call and keep what it was shown."""
    shown: list[str] = []

    async def chat(messages: Sequence[ChatMessage], _sampling: Sampling) -> str:
        shown.extend(message.content for message in messages)
        return json.dumps(reply, ensure_ascii=False)

    monkeypatch.setattr(target, chat)
    return shown


@pytest.mark.postgres
async def test_an_owners_interview_answer_keeps_its_address(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown = answering(monkeypatch, "b_k25.chat", {"value": OWNER_FACT})
    response = await client.post(
        "/fact-cards/card/interview", json={"field": "parking", "answer": OWNER_ANSWER},
    )
    assert response.json()["value"] == OWNER_FACT
    assert exposes("\n".join(shown), ADDRESS)
    assert not exposes("\n".join(shown), PHONE)


async def test_an_owners_judgment_answer_keeps_its_address(monkeypatch: pytest.MonkeyPatch) -> None:
    shown = answering(monkeypatch, "b_k25_judgments.chat", {"rule": OWNER_FACT, "applies_to": "전체"})
    suggestion = await suggest_rule("주차", OWNER_ANSWER, ())
    assert suggestion.rule == OWNER_FACT
    assert exposes("\n".join(shown), ADDRESS)
    assert not exposes("\n".join(shown), PHONE)


# Logs: failures are named by type only.


@pytest.mark.postgres
async def test_a_failing_run_logs_no_personal_data(
    database: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, logged: list[str],
) -> None:
    secrets = [secret for _, secret in SECRETS.values()]
    everything = " ".join(secrets)
    async def refused(body: AskRequest, now: datetime) -> AskResponse:
        raise HTTPException(502, everything)

    plan = TOOLS["mark_packed"].plan

    async def failing(db: AsyncSession, raw: dict[str, JsonValue], env: ToolEnv) -> Plan:
        async def execute_badly(session: AsyncSession, target: TargetRef) -> Outcome:
            raise IntegrityError(everything, {"value": everything}, RuntimeError(everything))

        return replace(await plan(db, raw, env), execute=execute_badly)

    monkeypatch.setattr("agent_run.ask", refused)
    object.__setattr__(TOOLS["mark_packed"], "plan", failing)
    try:
        body = await ask(
            client, chat_of(wants("mark_packed", order="1040"), ModelUnavailableError()), "1040 포장 끝났어",
            history=[{"role": "owner", "text": everything}],
        )
    finally:
        object.__setattr__(TOOLS["mark_packed"], "plan", plan)
    assert body["status"] == "fallback"
    lines = "\n".join(logged)
    for event in ("agent_storage_refused", "agent_fallback_failed", "http_request"):
        assert event in lines
    assert [secret for secret in secrets if exposes(lines, secret)] == []
