"""Workshop profile and owner-maintained settings text."""

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from bookings import ExpectedRevision
from channels import channel_cards
from common import LongText, Now, Session, ShortText, require_revision, required_text
from contracts import ApiModel, Card
from models import SettingItemRow, WorkshopRow

router = APIRouter()


class Workshop(ApiModel):
    """Workshop profile."""

    name: str
    owner_title: str
    phone: str
    address: str
    description: str
    latitude: float | None
    longitude: float | None
    revision: int


class WorkshopUpdate(ExpectedRevision):
    """Full profile edit; revision 0 creates the first profile."""

    name: ShortText
    owner_title: ShortText
    phone: Annotated[str, Field(max_length=40)]
    address: Annotated[str, Field(max_length=200)]
    description: LongText
    latitude: Annotated[float, Field(ge=-90, le=90, strict=False)] | None
    longitude: Annotated[float, Field(ge=-180, le=180, strict=False)] | None


class SettingItem(ApiModel):
    """One text setting."""

    key: str
    section: str
    title: str
    symbol: str
    body: str
    is_editable: bool
    revision: int


class SettingUpdate(ExpectedRevision):
    """New text for one setting."""

    body: LongText


class Settings(ApiModel):
    """Everything shown on the settings tab."""

    workshop: Workshop | None
    items: list[SettingItem]
    channels: list[Card]


def workshop_view(row: WorkshopRow) -> Workshop:
    """Serialize the profile."""
    return Workshop(
        name=row.name, owner_title=row.owner_title, phone=row.phone, address=row.address,
        description=row.description, latitude=row.latitude, longitude=row.longitude, revision=row.revision,
    )


def item_view(row: SettingItemRow) -> SettingItem:
    """Serialize a setting."""
    return SettingItem(
        key=row.key, section=row.section, title=row.title, symbol=row.symbol, body=row.body,
        is_editable=row.is_editable, revision=row.revision,
    )


@router.get("/settings")
async def settings(db: Session, now: Now) -> Settings:
    """Return the profile, text settings, and real channel states."""
    workshop = await db.get(WorkshopRow, 1)
    items = await db.scalars(select(SettingItemRow).order_by(SettingItemRow.sort_order, SettingItemRow.key))
    return Settings(
        workshop=workshop_view(workshop) if workshop else None,
        items=[item_view(row) for row in items],
        channels=await channel_cards(db, now.date()),
    )


@router.put("/workshop")
async def update_workshop(body: WorkshopUpdate, db: Session) -> Workshop:
    """Create or replace the profile under optimistic concurrency."""
    name, owner_title = required_text(body.name), required_text(body.owner_title)
    phone, address, description = body.phone.strip(), body.address.strip(), body.description.strip()
    row = await db.get(WorkshopRow, 1, with_for_update=True)
    if row is None:
        if body.expected_revision != 0:
            raise HTTPException(409, "revision is stale")
        inserted = await db.scalar(
            insert(WorkshopRow).values(
                id=1, revision=1, name=name, owner_title=owner_title, phone=phone, address=address,
                description=description, latitude=body.latitude, longitude=body.longitude,
            ).on_conflict_do_nothing(index_elements=[WorkshopRow.id]).returning(WorkshopRow),
        )
        if inserted is None:
            raise HTTPException(409, "revision is stale")
        return workshop_view(inserted)
    require_revision(row.revision, body.expected_revision)
    row.name, row.owner_title = name, owner_title
    row.phone, row.address, row.description = phone, address, description
    row.latitude, row.longitude = body.latitude, body.longitude
    row.revision += 1
    await db.flush()
    return workshop_view(row)


@router.patch("/settings/{key}")
async def update_setting(key: str, body: SettingUpdate, db: Session) -> SettingItem:
    """Save an editable text setting."""
    row = await db.get(SettingItemRow, key, with_for_update=True)
    if row is None:
        raise HTTPException(404, "resource not found")
    require_revision(row.revision, body.expected_revision)
    if not row.is_editable:
        raise HTTPException(409, "setting is read only")
    row.body = required_text(body.body)
    row.revision += 1
    await db.flush()
    return item_view(row)
