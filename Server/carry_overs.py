"""Overdue work the owner approved for today's list; the original deadline never changes."""

from datetime import date
from typing import Annotated, Final, Literal, assert_never

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common import Now, Session, ShortText
from contracts import ApiRequest
from display import day_start
from metrics import UNSHIPPED
from models import CarryOverRow, Entity, ShipmentRow, TaskRow

router = APIRouter()
MAX_ITEMS: Final = 100
type Target = Literal["task", "shipment"]
type Key = tuple[Target, str]


class CarryOverItem(ApiRequest):
    """One task or parcel on the today list."""

    target: Target
    id: ShortText


class CarryOverBatch(ApiRequest):
    """Work carried or returned together."""

    items: Annotated[list[CarryOverItem], Field(min_length=1, max_length=MAX_ITEMS)]

    def ordered(self) -> list[Key]:
        """List each row once, sorted so overlapping requests lock in one order."""
        return sorted({(item.target, item.id) for item in self.items})


async def carried_on(db: AsyncSession, day: date) -> frozenset[tuple[str, str]]:
    """Return the (target, id) pairs carried into a day."""
    rows = await db.execute(
        select(CarryOverRow.target, CarryOverRow.target_id).where(CarryOverRow.carried_on == day),
    )
    return frozenset(rows.tuples())


async def locked_row[T: Entity](db: AsyncSession, model: type[T], row_id: str) -> T:
    """Lock the work a carry-over names."""
    row = await db.get(model, row_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "찾을 수 없는 항목이에요.")
    return row


async def is_left_over(db: AsyncSession, key: Key, today: date) -> bool:
    """Tell whether locked work is unfinished and was due before today."""
    target, row_id = key
    match target:
        case "task":
            task = await locked_row(db, TaskRow, row_id)
            return task.status == "open" and task.due_at < day_start(today)
        case "shipment":
            parcel = await locked_row(db, ShipmentRow, row_id)
            return parcel.status in UNSHIPPED and parcel.ship_by_at < day_start(today)
        case _:
            assert_never(target)


@router.post("/today/carry-overs", status_code=204)
async def carry_over(body: CarryOverBatch, db: Session, now: Now) -> None:
    """Put left-over work into today's list; one row that cannot move refuses the whole batch."""
    today, keys = now.date(), body.ordered()
    for key in keys:
        if not await is_left_over(db, key, today):
            raise HTTPException(409, "기한이 어제까지였고 아직 끝나지 않은 일만 오늘 할 일에 넣을 수 있어요.")
    _ = await db.execute(
        insert(CarryOverRow)
        .values([{"target": target, "target_id": row_id, "carried_on": today} for target, row_id in keys])
        .on_conflict_do_update(
            index_elements=[CarryOverRow.target, CarryOverRow.target_id], set_={"carried_on": today},
        ),
    )


@router.post("/today/carry-overs/undo", status_code=204)
async def undo_carry_over(body: CarryOverBatch, db: Session) -> None:
    """Take work back out of the list; rows that are not carried are left alone."""
    for target, row_id in body.ordered():
        _ = await db.execute(
            delete(CarryOverRow).where(CarryOverRow.target == target, CarryOverRow.target_id == row_id),
        )
