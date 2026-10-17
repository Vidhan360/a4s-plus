"""Unit tests for database URL normalization and engine configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, normalize_database_url
from app.core.database import _create_engine


def test_normalize_database_url_postgresql_schemes() -> None:
    # Standard postgres:// schemes
    assert normalize_database_url("postgres://user:pass@host:5432/db") == (
        "postgresql+asyncpg://user:pass@host:5432/db"
    )

    # Standard postgresql:// schemes
    assert normalize_database_url("postgresql://user:pass@host:5432/db") == (
        "postgresql+asyncpg://user:pass@host:5432/db"
    )

    # Already asyncpg
    assert normalize_database_url("postgresql+asyncpg://user:pass@host:5432/db") == (
        "postgresql+asyncpg://user:pass@host:5432/db"
    )


def test_normalize_database_url_sslmode_query_param() -> None:
    # asyncpg expects ?ssl= instead of ?sslmode=
    raw = "postgresql://user:pass@ep-xyz.aws.neon.tech/neondb?sslmode=require"
    expected = "postgresql+asyncpg://user:pass@ep-xyz.aws.neon.tech/neondb?ssl=require"
    assert normalize_database_url(raw) == expected


def test_normalize_database_url_sqlite() -> None:
    assert normalize_database_url("sqlite:///app.db") == "sqlite+aiosqlite:///app.db"
    assert normalize_database_url("sqlite+aiosqlite:///app.db") == "sqlite+aiosqlite:///app.db"


def test_normalize_database_url_none_and_empty() -> None:
    assert normalize_database_url(None) is None
    assert normalize_database_url("") == ""


def test_settings_normalizes_database_url() -> None:
    with patch.dict(os.environ, {"A4S_DATABASE_URL": "postgresql://user:pass@dbhost:5432/dbname"}):
        s = Settings()
        assert s.database_url == "postgresql+asyncpg://user:pass@dbhost:5432/dbname"


def test_settings_falls_back_to_database_url_env_var() -> None:
    env = {
        "DATABASE_URL": "postgres://user:pass@render-db:5432/renderdb",
    }
    with patch.dict(os.environ, env, clear=False):
        s = Settings(_env_file=None, database_url=None)
        assert s.database_url == "postgresql+asyncpg://user:pass@render-db:5432/renderdb"


def test_create_engine_uses_asyncpg_dialect_with_postgres_url() -> None:
    with patch.dict(os.environ, {"A4S_DATABASE_URL": "postgres://mockuser:mockpass@localhost:5432/mockdb"}):
        test_engine = _create_engine()
        assert isinstance(test_engine, AsyncEngine)
        assert test_engine.dialect.name == "postgresql"
        assert test_engine.dialect.driver == "asyncpg"
        assert isinstance(test_engine.dialect, PGDialect_asyncpg)


def test_normalize_database_url_strips_unsupported_params() -> None:
    raw = (
        "postgresql://user:pass@ep-xyz.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require&options=endpoint%3Dep-xyz&gssencmode=disable"
    )
    cleaned = normalize_database_url(raw)
    assert cleaned == "postgresql+asyncpg://user:pass@ep-xyz.aws.neon.tech/neondb?ssl=require"


def test_normalize_database_url_neon_auto_ssl() -> None:
    raw = "postgresql://user:pass@ep-xyz-123.us-east-2.aws.neon.tech/neondb"
    cleaned = normalize_database_url(raw)
    assert cleaned == "postgresql+asyncpg://user:pass@ep-xyz-123.us-east-2.aws.neon.tech/neondb?ssl=require"
