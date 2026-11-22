# How to run: from Server, after `uv run alembic upgrade head`, run `uv run python seed.py`.
"""Explicit seed command: inserts missing rows and never updates existing ones."""

import sys
from datetime import date, datetime

import anyio
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from collectors.mapping import retire_seed_rows
from database import DatabaseConfigurationError, get_engine
from display import SEOUL
from models import InquiryRow
from seed_data import build_seed


async def apply_seed(connection: AsyncConnection, today: date) -> int:
    """Insert missing seed rows, link adopted inquiries, and keep out rows that real data replaced."""
    inserted = 0
    tables = build_seed(today)
    for model, rows in tables:
        result = await connection.execute(insert(model).values(list(rows)).on_conflict_do_nothing())
        inserted += result.rowcount
    inquiry_rows = next(rows for model, rows in tables if model is InquiryRow)
    for row in inquiry_rows:
        # Links are not user-editable, so filling a NULL cannot overwrite owner work.
        _ = await connection.execute(
            update(InquiryRow)
            .where(InquiryRow.id == row["id"], InquiryRow.customer_id.is_(None))
            .values(customer_id=row["customer_id"], channel_id=row["channel_id"]),
        )
    return inserted - await retire_seed_rows(connection, today)


async def main() -> None:
    """Seed in one transaction without credential-bearing tracebacks."""
    try:
        engine = get_engine()
        try:
            async with engine.begin() as connection:
                inserted = await apply_seed(connection, datetime.now(SEOUL).date())
        finally:
            await engine.dispose()
            get_engine.cache_clear()
    except (DatabaseConfigurationError, SQLAlchemyError, OSError, TimeoutError):
        message = "Seeding failed; run migrations and check PostgreSQL configuration."
        raise SystemExit(message) from None
    _ = sys.stdout.write(f"Seed complete: {inserted} rows inserted.\n")


if __name__ == "__main__":
    anyio.run(main)
