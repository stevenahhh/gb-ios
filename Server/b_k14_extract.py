"""Read one outreach inquiry into fields; the model copies text and rules decide everything else."""

import logging
import re
from collections.abc import Callable
from datetime import date
from typing import ClassVar, Final, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from b_k14_rules import (
    UNITS,
    amounts_in,
    budget_in,
    offers_margin,
    owner_buys_for_them,
    owner_pays_first,
    people_in,
    written_time_range,
)
from contracts import ApiModel
from providers import ChatMessage, Sampling, chat

LOGGER: Final = logging.getLogger("roundup.k14")
EXTRACT_SAMPLING: Final = Sampling(temperature=0.1, max_tokens=500)
ATTEMPTS: Final = 2
type OrgType = Literal["school", "public", "company", "welfare", "other", "unknown"]
type ContactKind = Literal["landline", "mobile", "email", "unknown"]
type Vat = Literal["included", "excluded", "unknown"]
type SignalCode = Literal[
    "mobile_only_contact", "proxy_purchase", "margin_offer", "same_day_pressure", "prepay_by_owner",
]
type Confidence = Literal["high", "low"]
SIGNAL_CODES: Final[tuple[SignalCode, ...]] = (
    "mobile_only_contact", "proxy_purchase", "margin_offer", "same_day_pressure", "prepay_by_owner",
)

SYSTEM: Final = """너는 공방에 온 출강 문의를 읽고 정해진 칸을 채우는 도우미다.
문장에 적힌 내용만 옮긴다. 적혀 있지 않은 값은 null로 둔다.
금액은 원 단위 정수로 바꾼다. "200만"은 2000000이다.
인원이 "30~40명"처럼 범위면 headcount_min과 headcount_max에 나눠 적는다.
날짜가 상대 표현("다음 주 토요일")이면 date는 null로 두고 date_text에 원문을 옮긴다.
사람 이름과 전화번호와 이메일 주소는 어떤 칸에도 옮기지 않는다.
연락 방식만 contact_kind에 landline, mobile, email, unknown 중 하나로 적는다.
아래 행동이 문장에 있으면 signals에 코드를 넣는다.
- 지정 업체에서 물건을 대신 사 달라는 요청: proxy_purchase
- 차액이나 수수료를 주겠다는 제안: margin_offer
- 오늘 안에 정해 달라는 재촉: same_day_pressure
- 공방이 먼저 돈을 내야 하는 흐름: prepay_by_owner
판단이나 조언은 쓰지 않는다. JSON 하나만 출력한다.
칸: org_type(school, public, company, welfare, other, unknown), org_name, headcount_min, headcount_max,
budget_krw, budget_vat(included, excluded, unknown), date(YYYY-MM-DD), date_text, time_range(HH:MM-HH:MM),
location_text, class_hint, contact_kind, signals(배열), low_confidence(칸 이름 배열)"""
RETRY: Final = "방금 출력이 정해진 JSON 형식이 아니었다. 모든 칸을 넣은 JSON 하나만 다시 출력한다."

EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
MOBILE: Final = re.compile(r"(?<!\d)(?:\+?82[-.\s]?)?0?1[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
LANDLINE: Final = re.compile(
    r"(?<!\d)(?:0(?:2|[3-6]\d|70)[-.)\s]?\d{3,4}[-.\s]?\d{4}|1[568]\d{2}[-.\s]?\d{4})(?!\d)",
)
NUMBER: Final = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|만|천)?")
TIME_RANGE: Final = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d")
MONTH_DAY: Final = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일")
RULES: Final[tuple[tuple[SignalCode, Callable[[str], bool]], ...]] = (
    ("proxy_purchase", owner_buys_for_them),
    ("margin_offer", offers_margin),
    ("same_day_pressure", lambda text: PRESSURE.search(text) is not None),
    ("prepay_by_owner", owner_pays_first),
)
PRESSURE: Final = re.compile(r"오늘\s*(?:안|중)|금일\s*(?:중|내)|당장\s*(?:결정|확정)")
ORG_RULES: Final[tuple[tuple[OrgType, re.Pattern[str]], ...]] = (
    ("school", re.compile(r"학교|초등|중학|고등|유치원|어린이집")),
    ("public", re.compile(
        (
            r"시청|구청|군청|도청|주민센터|행정복지센터|도서관|공공|"
            r"교육청|교육지원청|주무관|공문|나라장터"
        ),
    )),
    ("welfare", re.compile(r"복지관|복지센터|요양")),
    ("company", re.compile(r"주식회사|회사|기업|\(주\)")),
)


class ModelReading(BaseModel):
    """The exact JSON the model must print; a missing key or wrong type is refused."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)
    org_type: OrgType
    org_name: str | None
    headcount_min: int | None
    headcount_max: int | None
    budget_krw: int | None
    budget_vat: Vat
    date: str | None
    date_text: str | None
    time_range: str | None
    location_text: str | None
    class_hint: str | None
    contact_kind: ContactKind
    signals: list[SignalCode]
    low_confidence: list[str]


class ExtractedFields(ApiModel):
    """Fields read from one inquiry; the text itself is dropped after this."""

    org_type: OrgType = "unknown"
    org_name: str | None = None
    headcount: int | None = None
    headcount_max: int | None = None
    budget_krw: int | None = None
    budget_vat: Vat = "unknown"
    date: str | None = None
    date_text: str | None = None
    time_range: str | None = None
    location_text: str | None = None
    class_hint: str | None = None
    contact_kind: ContactKind = "unknown"


class Extraction(ApiModel):
    """The extract endpoint's answer; `error` means the owner should check every field by hand."""

    fields: ExtractedFields
    confidence: dict[str, Confidence] = Field(default_factory=dict)
    signals: list[SignalCode] = Field(default_factory=list)
    locked: bool = False
    error: Literal["extract_failed"] | None = None


def mask(text: str) -> str:
    """Hide phone numbers and email addresses before the text leaves the server."""
    text = EMAIL.sub("[이메일]", text)
    text = MOBILE.sub("[휴대폰 번호]", text)
    return LANDLINE.sub("[대표 번호]", text)


def scrub(text: str | None, limit: int = 200) -> str | None:
    """Drop contact details a field must never carry."""
    if text is None:
        return None
    cleaned = LANDLINE.sub("", MOBILE.sub("", EMAIL.sub("", text))).strip()
    if cleaned != text.strip():
        LOGGER.warning("k14_contact_removed")
    return cleaned[:limit] or None


def contact_kind(text: str) -> ContactKind:
    """Read the contact channel from the original text, strongest first."""
    if LANDLINE.search(MOBILE.sub("", text)):
        return "landline"
    if EMAIL.search(text):
        return "email"
    return "mobile" if MOBILE.search(text) else "unknown"


def numbers(text: str) -> set[int]:
    """Collect every number the inquiry states, in won or people."""
    found = amounts_in(text)
    for match in NUMBER.finditer(text):
        value = float(match.expand(r"\1").replace(",", ""))
        found.add(round(value * UNITS[match.expand(r"\2")]))
    return found


def rule_signals(text: str) -> list[SignalCode]:
    """Find the risk wording without a model."""
    return [code for code, found in RULES if found(text)]


def with_server_signals(
    signals: list[SignalCode], org_type: str, kind: str,
) -> list[SignalCode]:
    """Add the contact signal and keep one stable order."""
    found = set(signals) - {"mobile_only_contact"}
    if kind == "mobile" and org_type in {"public", "school"}:
        found.add("mobile_only_contact")
    return [code for code in SIGNAL_CODES if code in found]


def is_locked(signals: list[SignalCode]) -> bool:
    """Lock the export only for the combinations the design chapter names."""
    found = set(signals)
    return bool(found & {"prepay_by_owner", "proxy_purchase"}) or (
        {"mobile_only_contact", "margin_offer"} <= found
    )


def parse_date(value: str | None) -> str | None:
    """Keep only a real calendar date."""
    try:
        return None if value is None else date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def parse_reading(raw: str) -> ModelReading | None:
    """Read the first JSON object the model printed."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return ModelReading.model_validate_json(raw[start:end + 1])
    except ValidationError:
        return None


async def model_reading(masked: str) -> ModelReading | None:
    """Ask the model, with one corrective retry for a broken shape."""
    messages = [ChatMessage("system", SYSTEM), ChatMessage("user", masked)]
    for _ in range(ATTEMPTS):
        raw = await chat(messages, EXTRACT_SAMPLING)
        reading = parse_reading(raw)
        if reading is not None:
            return reading
        LOGGER.warning("k14_extract_rejected")
        messages += [ChatMessage("assistant", raw), ChatMessage("user", RETRY)]
    return None


def checked_budget(answer: int | None, masked: str, stated: set[int]) -> tuple[int | None, bool]:
    """Keep the model's total only when the text supports it; a per-person price is multiplied or dropped."""
    value = answer if answer is not None and answer > 0 else None
    written = budget_in(masked)
    if written.per_person:
        return written.total, value == written.total and written.consistent and value is not None
    if value in written.other_amounts and value != written.total:
        return None, False
    return value, value is None or value in stated


def from_reading(reading: ModelReading, masked: str, kind: ContactKind) -> tuple[ExtractedFields, set[str]]:
    """Turn a valid reading into fields plus the names that still need the owner's check."""
    stated = numbers(masked)
    answered = (reading.headcount_min, reading.headcount_max)
    people = [value for value in answered if value is not None and value > 0]
    low = {to_field(name) for name in reading.low_confidence}
    written = people_in(masked)
    if written.grouped:
        # A per-group number is stated too, so the model's answer must equal the multiplied one.
        expected = [value for value in (written.low, written.high) if value is not None]
        if not expected or set(expected) != set(people):
            low.add("headcount")
        people = expected
    elif not set(people) <= stated:
        low.add("headcount")
    budget, sure = checked_budget(reading.budget_krw, masked, stated)
    if not sure:
        low.add("budget_krw")
    org_type = reading.org_type
    if org_type == "unknown":
        org_type = org_by_rules(masked)
        low.add("org_type")
    time_range = reading.time_range if TIME_RANGE.fullmatch(reading.time_range or "") else None
    fields = ExtractedFields(
        org_type=org_type, org_name=scrub(reading.org_name, 80),
        headcount=min(people, default=None), headcount_max=max(people, default=None),
        budget_krw=budget,
        budget_vat=reading.budget_vat, date=parse_date(reading.date), date_text=scrub(reading.date_text),
        time_range=time_range, location_text=scrub(reading.location_text),
        class_hint=scrub(reading.class_hint), contact_kind=kind,
    )
    return fields, low


def to_field(name: str) -> str:
    """Map the model's range columns onto the single headcount field."""
    return "headcount" if name in {"headcount_min", "headcount_max"} else name


def org_by_rules(text: str) -> OrgType:
    """Name the institution type from plain words."""
    for org, pattern in ORG_RULES:
        if pattern.search(text):
            return org
    return "unknown"


def from_rules(masked: str, kind: ContactKind) -> ExtractedFields:
    """Fill what plain patterns can prove when the model is unavailable or malformed."""
    people = people_in(masked)
    day = MONTH_DAY.search(masked)
    return ExtractedFields(
        org_type=org_by_rules(masked), headcount=people.low, headcount_max=people.high,
        budget_krw=budget_in(masked).total, date_text=day.group() if day is not None else None,
        time_range=written_time_range(masked), contact_kind=kind,
    )


async def extract(text: str) -> Extraction:
    """Read the inquiry, verify it, and fall back to rules when the model fails."""
    masked = mask(text)
    kind = contact_kind(text)
    try:
        reading = await model_reading(masked)
    except HTTPException:
        LOGGER.warning("k14_extract_upstream_failed")
        reading = None
    if reading is None:
        fields, low = from_rules(masked, kind), set(ExtractedFields.model_fields)
        error: Literal["extract_failed"] | None = "extract_failed"
        model_signals: list[SignalCode] = []
    else:
        fields, low = from_reading(reading, masked, kind)
        error, model_signals = None, reading.signals
    signals = with_server_signals(
        list({*model_signals, *rule_signals(masked)}), fields.org_type, fields.contact_kind,
    )
    read = set(fields.model_dump(exclude_defaults=True)) - low
    confidence: dict[str, Confidence] = {
        camel(name): "high" if name in read else "low" for name in ExtractedFields.model_fields
    }
    return Extraction(
        fields=fields, confidence=confidence, signals=signals, locked=is_locked(signals), error=error,
    )


def camel(name: str) -> str:
    """Use the JSON field name as the confidence key."""
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)
