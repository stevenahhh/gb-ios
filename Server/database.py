"""PostgreSQL engine, request transactions, and migrated-schema readiness."""

import logging
import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from os import environ
from pathlib import Path
from typing import Final, override

from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from sqlalchemy import Text, column, select, table
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

LOGGER: Final = logging.getLogger("roundup.database")
MIGRATIONS: Final = Path(__file__).resolve().parent / "migrations"
SCHEMA_NAME: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")
UNSTORABLE_TEXT: Final = frozenset({"22021", "22P05"})  # a NUL in text or in JSON; not an outage


class DatabaseConfigurationError(Exception):
    """Configuration errors never include the credential-bearing input."""

    @override
    def __str__(self) -> str:
        return (
            "Configure DATABASE_URL for PostgreSQL, DATABASE_SSLMODE as disable, "
            "require, or verify-full, and DATABASE_SCHEMA as a lowercase identifier"
        )


class Base(DeclarativeBase):
    """Metadata shared by every table and by Alembic."""


def server_settings() -> dict[str, str]:
    """Select the optional dedicated schema through the connection search path."""
    schema = environ.get("DATABASE_SCHEMA", "")
    if not schema:
        return {}
    if SCHEMA_NAME.fullmatch(schema) is None:
        raise DatabaseConfigurationError
    return {"search_path": schema}


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Parse configuration once; never substitute another storage backend."""
    raw_url = environ.get("DATABASE_URL", "")
    try:
        url = make_url(raw_url)
    except ArgumentError:
        raise DatabaseConfigurationError from None
    if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise DatabaseConfigurationError
    ssl_mode = environ.get("DATABASE_SSLMODE", "verify-full")
    # True uses the system CA store; asyncpg's literal "verify-full" requires a
    # separate ~/.postgresql/root.crt and fails before any network connection.
    ssl_options: dict[str, bool | str] = {
        "disable": False, "require": "require", "verify-full": True,
    }
    if ssl_mode not in ssl_options:
        raise DatabaseConfigurationError
    if {"ssl", "sslmode"} & url.query.keys():
        raise DatabaseConfigurationError
    return create_async_engine(
        url.set(drivername="postgresql+asyncpg"),
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        connect_args={
            "timeout": 10,
            "command_timeout": 15,
            "ssl": ssl_options[ssl_mode],
            "server_settings": server_settings(),
        },
    )


@asynccontextmanager
async def database_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Fail startup on missing configuration and release the pool on shutdown."""
    engine = get_engine()
    try:
        yield
    finally:
        await engine.dispose()
        get_engine.cache_clear()


@asynccontextmanager
async def transaction() -> AsyncGenerator[AsyncSession]:
    """Run one transaction and redact infrastructure errors at the boundary."""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    try:
        async with factory.begin() as db:
            yield db
    except IntegrityError as error:
        LOGGER.warning("database_constraint_rejected", extra={"error_type": type(error).__name__})
        raise HTTPException(409, "request conflicts with current data") from None
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        if isinstance(error, DBAPIError) and getattr(error.orig, "sqlstate", None) in UNSTORABLE_TEXT:
            raise HTTPException(422, "text holds a character that cannot be stored") from None
        LOGGER.error("database_unavailable", extra={"error_type": type(error).__name__})  # noqa: TRY400
        raise HTTPException(503, "service unavailable") from None


async def session() -> AsyncIterator[AsyncSession]:
    """Give each HTTP request one transaction that commits before the response."""
    async with transaction() as db:
        yield db


@lru_cache(maxsize=1)
def expected_schema_revision() -> str | None:
    """Read the newest migration shipped with this release."""
    return ScriptDirectory(str(MIGRATIONS)).get_current_head()


async def schema_is_current(db: AsyncSession) -> bool:
    """Compare the database migration version with this release."""
    version = column("version_num", Text)
    applied = await db.scalar(select(version).select_from(table("alembic_version")))
    return applied == expected_schema_revision()
