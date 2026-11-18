"""Alembic runner; the database URL comes only from the server environment."""

import anyio
from alembic import context
from sqlalchemy import Connection, text

from database import get_engine
from models import InquiryRow

MIGRATION_LOCK = 7_277_041_218


def run_on(connection: Connection) -> None:
    """Apply migrations in one transaction under a cluster-wide advisory lock."""
    context.configure(connection=connection, target_metadata=InquiryRow.metadata, compare_type=True)
    with context.begin_transaction():
        _ = connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        context.run_migrations()


async def run_online() -> None:
    """Open the configured engine and migrate."""
    engine = get_engine()
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_on)
    finally:
        await engine.dispose()
        get_engine.cache_clear()


supplied = context.config.attributes.get("connection")
if isinstance(supplied, Connection):
    run_on(supplied)
else:
    anyio.run(run_online)
