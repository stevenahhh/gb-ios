"""Public handles and links the owner saves per service; a saved value never means connected."""

import re
from collections.abc import Callable
from enum import StrEnum
from functools import partial
from typing import Annotated, Final, Literal, override
from urllib.parse import SplitResult, parse_qsl, unquote, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import CheckConstraint, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column

from bookings import ExpectedRevision
from common import Session
from contracts import ApiModel
from database import Base
from display import local
from models import REVISION_CHECK, Audited, TableArgs

router = APIRouter(prefix="/connections")
MAX_VALUE: Final = 200
EMPTY: Final = "값을 입력해 주세요."
TOO_LONG: Final = "200자까지 저장할 수 있어요."
SECRET: Final = "비밀번호나 토큰처럼 보이는 값은 저장하지 않아요. 공개 아이디나 주소만 입력해 주세요."  # noqa: S105
BAD_HANDLE: Final = "아이디 형식이 맞지 않아요. 다시 확인해 주세요."
BAD_LINK: Final = "주소 형식이 맞지 않아요. 다시 확인해 주세요."
HTTPS_ONLY: Final = "https://로 시작하는 주소만 저장할 수 있어요."
WRONG_HOST: Final = "이 서비스의 주소가 아니에요. 다시 확인해 주세요."
UNKNOWN: Final = "저장할 수 없는 서비스예요."
STALE: Final = "다른 곳에서 먼저 바뀌었어요. 새로 불러온 뒤 다시 시도해 주세요."

FORBIDDEN: Final = re.compile(r"[\s\\<>\"'`]")
SECRET_PAIR: Final = re.compile(
    r"""(?:pass(?:word|wd|code)?|pwd|secret|token|api[_-]?key|\bkey|auth|authorization|credential|session
    |signature|비밀번호|패스워드|비번)\s*[:=]""",
    re.IGNORECASE | re.VERBOSE,
)
KNOWN_TOKEN: Final = re.compile(
    r"""(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_\w{16,}
    |xox[a-z]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{10,}
    |EAA[A-Za-z0-9]{20,}|IG[A-Za-z0-9_-]{30,})""",
    re.VERBOSE,
)
LONG_RANDOM: Final = re.compile(r"(?=[A-Za-z_-]*\d)(?=[0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}")
INSTAGRAM_HANDLE: Final = re.compile(r"(?!.*\.\.)[a-z0-9_](?:[a-z0-9._]{0,28}[a-z0-9_])?")
BLOG_ID: Final = re.compile(r"[a-z0-9_-]{2,40}")
STORE: Final = re.compile(r"[A-Za-z0-9_-]{1,60}")
KAKAO_ID: Final = re.compile(r"_[A-Za-z0-9]{2,40}")

INSTAGRAM_HOSTS: Final = frozenset({"instagram.com", "www.instagram.com", "m.instagram.com"})
BLOG_HOSTS: Final = frozenset({"blog.naver.com", "m.blog.naver.com"})
STORE_HOSTS: Final = frozenset({"smartstore.naver.com", "m.smartstore.naver.com", "brand.naver.com"})
BOOKING_HOSTS: Final = frozenset({"booking.naver.com", "m.booking.naver.com"})
PLACE_HOSTS: Final = frozenset({
    "map.naver.com", "m.place.naver.com", "pcmap.place.naver.com", "naver.me",
})
KAKAO_HOSTS: Final = frozenset({"pf.kakao.com"})
GOOGLE_HOSTS: Final = frozenset({
    "maps.app.goo.gl", "maps.google.com", "www.google.com", "google.com",
})
GOOGLE_SEARCH_HOSTS: Final = frozenset({"www.google.com", "google.com"})


class RefusedValueError(Exception):
    """The value is not a public handle or link of its service; the message never repeats the value."""

    def __init__(self, message: str) -> None:
        """Keep the Korean message shown to the owner."""
        super().__init__(message)
        self.message: str = message

    @override
    def __str__(self) -> str:
        return self.message


class Service(StrEnum):
    """Services with a public value to save, in the order the API lists them."""

    INSTAGRAM = "instagram"
    NAVER_SMARTSTORE = "naver_smartstore"
    NAVER_BLOG = "naver_blog"
    NAVER_BOOKING = "naver_booking"
    NAVER_PLACE = "naver_place"
    KAKAO_CHANNEL = "kakao_channel"
    GOOGLE_MAPS = "google_maps"


class ConnectionRow(Audited, Base):
    """One saved value; a cleared row keeps its revision, so a stale writer cannot restore it."""

    __tablename__: str = "connections"
    __table_args__: TableArgs = (
        CheckConstraint(f"btrim(value) <> '' AND length(value) <= {MAX_VALUE}"),
        CheckConstraint(REVISION_CHECK),
    )
    service: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class Connection(ApiModel):
    """One service as the app shows it."""

    service: Service
    value: str | None
    state: Literal["saved", "none"]
    updated_at: str | None
    revision: int


class ConnectionList(ApiModel):
    """Every service that can hold a value."""

    items: list[Connection]


class ConnectionSave(ExpectedRevision):
    """A handle or link to save; revision 0 saves the first one."""

    value: str


def link(value: str, hosts: frozenset[str]) -> SplitResult:
    """Parse a plain https URL on one of the hosts."""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise RefusedValueError(BAD_LINK) from None
    if parts.scheme != "https":
        raise RefusedValueError(HTTPS_ONLY)
    if port is not None or "@" in parts.netloc or {".", ".."} & set(unquote(parts.path).split("/")):
        raise RefusedValueError(BAD_LINK)
    if parts.hostname not in hosts:
        raise RefusedValueError(WRONG_HOST)
    return parts


def segments(parts: SplitResult) -> list[str]:
    """Split a path into its non-empty parts."""
    return [part for part in parts.path.split("/") if part]


def handle(value: str, hosts: frozenset[str], pattern: re.Pattern[str]) -> str:
    """Read a handle written alone, with @, or as a profile link; store it in lowercase."""
    name = value.removeprefix("@")
    if "/" in value:
        path = segments(link(value, hosts))
        if len(path) != 1:
            raise RefusedValueError(BAD_LINK)
        name = path[0].removeprefix("@")
    if pattern.fullmatch(name.lower()) is None:
        raise RefusedValueError(BAD_HANDLE)
    return name.lower()


def store_link(value: str) -> str:
    """Reduce a store or product link to the store page."""
    parts = link(value, STORE_HOSTS)
    path = segments(parts)
    if not path or STORE.fullmatch(path[0]) is None:
        raise RefusedValueError(BAD_LINK)
    return f"https://{(parts.hostname or '').removeprefix('m.')}/{path[0]}"


def kakao_link(value: str) -> str:
    """Reduce a channel link, such as its chat page, to the channel page."""
    path = segments(link(value, KAKAO_HOSTS))
    if not path or KAKAO_ID.fullmatch(path[0]) is None:
        raise RefusedValueError(BAD_LINK)
    return f"https://pf.kakao.com/{path[0]}"


def page_link(value: str, hosts: frozenset[str]) -> str:
    """Keep the host and path of a page link without its query or fragment."""
    parts = link(value, hosts)
    path = segments(parts)
    if not path:
        raise RefusedValueError(BAD_LINK)
    return f"https://{parts.hostname}/{'/'.join(path)}"


def google_link(value: str) -> str:
    """Accept map links only, and keep the numeric place id some of them carry in the query."""
    parts = link(value, GOOGLE_HOSTS)
    path = segments(parts)
    on_search_host = parts.hostname in GOOGLE_SEARCH_HOSTS
    if on_search_host and path[:1] != ["maps"]:
        raise RefusedValueError(WRONG_HOST)
    place = next(
        (item for key, item in parse_qsl(parts.query) if key == "cid" and re.fullmatch(r"[0-9]{1,20}", item)),
        None,
    )
    if place is None and path in ([], ["maps"]):
        raise RefusedValueError(BAD_LINK)
    query = f"?cid={place}" if place else ""
    return f"https://{parts.hostname}/{'/'.join(path)}{query}"


PARSERS: Final[dict[Service, Callable[[str], str]]] = {
    Service.INSTAGRAM: partial(handle, hosts=INSTAGRAM_HOSTS, pattern=INSTAGRAM_HANDLE),
    Service.NAVER_SMARTSTORE: store_link,
    Service.NAVER_BLOG: partial(handle, hosts=BLOG_HOSTS, pattern=BLOG_ID),
    Service.NAVER_BOOKING: partial(page_link, hosts=BOOKING_HOSTS),
    Service.NAVER_PLACE: partial(page_link, hosts=PLACE_HOSTS),
    Service.KAKAO_CHANNEL: kakao_link,
    Service.GOOGLE_MAPS: google_link,
}


def normalised(service: Service, raw: str) -> str:
    """Turn owner input into the stored value, or refuse it without repeating it."""
    value = raw.strip()
    if not value:
        raise RefusedValueError(EMPTY)
    if len(value) > MAX_VALUE:
        raise RefusedValueError(TOO_LONG)
    decoded = unquote(value)
    if SECRET_PAIR.search(decoded) or KNOWN_TOKEN.search(decoded):
        raise RefusedValueError(SECRET)
    if FORBIDDEN.search(decoded) or not decoded.isprintable():
        raise RefusedValueError(BAD_LINK)
    stored = PARSERS[service](value)
    # Dropped queries hold long tracking ids, so only what would be stored is checked here.
    if LONG_RANDOM.search(unquote(stored)):
        raise RefusedValueError(SECRET)
    return stored


def known_service(service: str) -> Service:
    """Read the path segment; an unlisted service has nothing to save."""
    try:
        return Service(service)
    except ValueError:
        raise HTTPException(404, UNKNOWN) from None


KnownService = Annotated[Service, Depends(known_service)]


def view(service: Service, row: ConnectionRow | None) -> Connection:
    """Present a row; a service never touched has revision 0."""
    if row is None:
        return Connection(service=service, value=None, state="none", updated_at=None, revision=0)
    return Connection(
        service=service, value=row.value, state="none" if row.value is None else "saved",
        updated_at=local(row.updated_at).isoformat(timespec="seconds"), revision=row.revision,
    )


async def locked_row(db: Session, service: Service, expected_revision: int) -> ConnectionRow | None:
    """Lock the row and refuse a write based on a stale read."""
    row = await db.get(ConnectionRow, service.value, with_for_update=True)
    if (row.revision if row else 0) != expected_revision:
        raise HTTPException(409, STALE)
    return row


def change(row: ConnectionRow, value: str | None) -> None:
    """Replace the value of a locked row."""
    row.value = value
    row.revision += 1


@router.get("")
async def connections(db: Session) -> ConnectionList:
    """List every service with its saved value."""
    rows = {row.service: row for row in await db.scalars(select(ConnectionRow))}
    return ConnectionList(items=[view(service, rows.get(service.value)) for service in Service])


@router.put("/{service}")
async def save(service: KnownService, body: ConnectionSave, db: Session) -> Connection:
    """Save a public handle or link."""
    try:
        value = normalised(service, body.value)
    except RefusedValueError as refused:
        raise HTTPException(422, refused.message) from None
    row = await locked_row(db, service, body.expected_revision)
    if row is None:
        row = await db.scalar(
            insert(ConnectionRow)
            .values(service=service.value, value=value, revision=1)
            .on_conflict_do_nothing(index_elements=[ConnectionRow.service])
            .returning(ConnectionRow),
        )
        if row is None:
            raise HTTPException(409, STALE)
        return view(service, row)
    change(row, value)
    await db.flush()
    return view(service, row)


@router.delete("/{service}")
async def clear(service: KnownService, body: ExpectedRevision, db: Session) -> Connection:
    """Remove the saved value and keep counting revisions."""
    row = await locked_row(db, service, body.expected_revision)
    if row is not None and row.value is not None:
        change(row, None)
        await db.flush()
    return view(service, row)
