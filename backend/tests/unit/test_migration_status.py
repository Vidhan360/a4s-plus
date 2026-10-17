"""Tests for database migration status and diagnostic inspection."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import session_scope
from app.core.migration_runner import get_migration_status
from app.main import create_app


@pytest.mark.asyncio
async def test_get_migration_status_reports_head() -> None:
    async with session_scope() as session:
        status = await get_migration_status(session)
        assert status["status"] == "ready"
        assert status["alembic_revision"] == "2b6d9bf2b390"
        assert status["users_table_exists"] is True
        assert status["table_count"] >= 23
        assert "users" in status["tables"]
        assert "alembic_version" in status["tables"]


@pytest.mark.asyncio
async def test_db_status_endpoint() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/db-status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["alembic_revision"] == "2b6d9bf2b390"
        assert body["users_table_exists"] is True
        assert "users" in body["tables"]
