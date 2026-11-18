#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastapi>=0.121", "sqlalchemy[asyncio]>=2.0,<2.1", "asyncpg>=0.30", "anyio>=4"]
# ///
# How to run: install uv, then from Server run `uv run init_db.py`.
"""Explicit initial schema creation and non-overwriting synthetic seed."""

import sys

import anyio
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from database import Base, DatabaseConfigurationError, InquiryRow, get_engine
from seed import SEED_INQUIRIES


async def initialize(engine: AsyncEngine) -> None:
    """Apply v1 schema and insert only missing canonical IDs in one transaction."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        _ = await connection.execute(
            insert(InquiryRow)
            .values([item.model_dump() for item in SEED_INQUIRIES])
            .on_conflict_do_nothing(index_elements=[InquiryRow.id]),
        )


async def main() -> None:
    """Exit without credential-bearing tracebacks on initialization failures."""
    try:
        engine = get_engine()
        try:
            await initialize(engine)
        finally:
            await engine.dispose()
            get_engine.cache_clear()
    except (DatabaseConfigurationError, SQLAlchemyError, OSError, TimeoutError):
        message = "Database initialization failed; check PostgreSQL configuration and access."
        raise SystemExit(message) from None
    _ = sys.stdout.write("Inquiry schema initialized; missing synthetic inquiries inserted.\n")


if __name__ == "__main__":
    anyio.run(main)
