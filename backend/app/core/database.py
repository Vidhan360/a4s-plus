"""Async SQLAlchemy engine, session factory and declarative base."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool
from sqlalchemy.types import JSON, TypeDecorator

from app.core.config import normalize_database_url, settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class GUID(TypeDecorator):
    """UUID column: native ``uuid`` on PostgreSQL, ``CHAR(36)`` elsewhere.

    Keeps the test suite runnable on SQLite while production uses PostgreSQL's
    native UUID type.
    """

    impl = PGUUID(as_uuid=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        from sqlalchemy import CHAR

        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


#: JSONB on PostgreSQL, JSON elsewhere.
JSONType = JSONB().with_variant(JSON(), "sqlite")


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict: JSONType, uuid.UUID: GUID}


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def _create_engine() -> AsyncEngine:
    url = normalize_database_url(settings.database_url) or ""
    kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
    if settings.env == "test":
        # Pytest gives each test its own event loop. A pooled asyncpg
        # connection created in one loop cannot be reused from another, so the
        # test environment deliberately opts out of connection pooling.
        kwargs["poolclass"] = NullPool
    elif not url.startswith("sqlite"):
        kwargs |= {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
        }
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = _create_engine()
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, autoflush=False
)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Transactional session for background tasks (simulation loop, seeds)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a transactional session."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


__all__ = [
    "GUID",
    "Base",
    "JSONType",
    "SessionLocal",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "engine",
    "get_db",
    "session_scope",
]
