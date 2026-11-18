"""PostgreSQL schema and process-owned async connection pool."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from os import environ
from typing import override

from fastapi import FastAPI, HTTPException
from sqlalchemy import CheckConstraint, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class DatabaseConfigurationError(Exception):
    """Configuration errors never include the credential-bearing input."""

    @override
    def __str__(self) -> str:
        return (
            "Configure DATABASE_URL for PostgreSQL and DATABASE_SSLMODE "
            "as disable, require, or verify-full"
        )


class Base(DeclarativeBase):
    """Metadata for the initial inquiry schema."""


class InquiryRow(Base):
    """Mutable ORM row; all application writes hold its transaction row lock."""

    __tablename__: str = "inquiries"
    __table_args__: tuple[CheckConstraint, ...] = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')"),
        CheckConstraint("revision >= 0"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    facts: Mapped[list[str]] = mapped_column(ARRAY(Text))
    draft: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)


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
        connect_args={"timeout": 10, "command_timeout": 15, "ssl": ssl_options[ssl_mode]},
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


async def session() -> AsyncIterator[AsyncSession]:
    """Give each HTTP request a transaction and redact infrastructure errors."""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    try:
        async with factory.begin() as db:
            yield db
    except (SQLAlchemyError, OSError, TimeoutError):
        raise HTTPException(503, "inquiry database unavailable") from None
