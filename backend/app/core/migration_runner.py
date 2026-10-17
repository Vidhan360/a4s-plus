"""Programmatic database migration and reference data seeding.

Safely applies pending Alembic migrations on startup and seeds baseline
reference data (permissions, default configuration, synthetic personnel,
terrain, UAVs) without requiring shell access on managed platforms like Render.
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine, session_scope
from app.core.logging import get_logger
from app.models.auth import User

logger = get_logger("app.database.migration")


def _get_alembic_config() -> Config:
    backend_dir = pathlib.Path(__file__).resolve().parent.parent.parent
    ini_path = backend_dir / "alembic.ini"
    if not ini_path.exists():
        ini_path = pathlib.Path("alembic.ini")
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


async def run_migrations() -> None:
    """Apply any pending Alembic migrations up to head.

    Executes on a background worker thread so the async event loop is not
    blocked, and Alembic's online runner can manage its own async connections.
    """
    if settings.env == "test":
        return

    logger.info("checking_and_applying_database_migrations")
    try:
        cfg = _get_alembic_config()
        await asyncio.to_thread(command.upgrade, cfg, "head")
        logger.info("database_migrations_completed_successfully")
    except Exception as exc:
        logger.exception("database_migration_failed", extra={"error": str(exc)})
        raise


async def get_migration_status(session: AsyncSession) -> dict[str, Any]:
    """Inspect current schema and migration state without exposing credentials."""
    # 1. Alembic current revision
    alembic_rev = None
    try:
        async with engine.connect() as conn:
            def _read_rev(sync_conn: Any) -> str | None:
                ctx = MigrationContext.configure(sync_conn)
                return ctx.get_current_revision()

            alembic_rev = await conn.run_sync(_read_rev)
    except Exception as exc:
        alembic_rev = f"error: {type(exc).__name__}"

    # 2. Check if users table exists and get count
    users_table_exists = False
    users_count = 0
    try:
        res = await session.execute(
            text(
                "SELECT EXISTS ("
                "SELECT FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'users'"
                ")"
            )
        )
        users_table_exists = bool(res.scalar())
        if users_table_exists:
            count_res = await session.execute(select(func.count()).select_from(User))
            users_count = int(count_res.scalar() or 0)
    except Exception:
        pass

    # 3. List all public tables
    tables: list[str] = []
    try:
        t_res = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
        tables = [row[0] for row in t_res.fetchall()]
    except Exception:
        pass

    return {
        "status": "ready" if users_table_exists else "uninitialized",
        "alembic_revision": alembic_rev,
        "users_table_exists": users_table_exists,
        "users_count": users_count,
        "table_count": len(tables),
        "tables": tables,
    }


async def run_auto_seed() -> dict[str, Any]:
    """Idempotently seed reference data and demo users if configured."""
    if settings.env == "test":
        return {"status": "skipped_test_mode"}

    summary: dict[str, Any] = {}
    try:
        from seeds.seed import (
            resolve_seed_passwords,
            seed_config,
            seed_permissions,
            seed_personnel,
            seed_terrain,
            seed_uav,
            seed_users,
        )

        async with session_scope() as session:
            # 1. Permissions and roles (safe & idempotent)
            summary["permissions"] = await seed_permissions(session)
            # 2. System configurations
            summary["config"] = await seed_config(session)
            # 3. Simulated personnel roster
            summary["personnel"] = await seed_personnel(session)
            # 4. Synthetic terrain map
            summary["terrain"] = await seed_terrain(session)
            # 5. UAV swarm & missions
            summary["uav"] = await seed_uav(session)

            # 6. Demo users (only if table is empty and passwords configured)
            user_count = (
                await session.execute(select(func.count()).select_from(User))
            ).scalar_one()

            if user_count == 0:
                try:
                    resolve_seed_passwords()
                    summary["users"] = await seed_users(session)
                    logger.info("demo_users_seeded_successfully")
                except SystemExit:
                    summary["users"] = "skipped_passwords_missing"
                    logger.info("demo_users_seeding_skipped_passwords_missing")
            else:
                summary["users"] = f"already_seeded_count_{user_count}"

        return summary
    except Exception as exc:
        logger.exception("auto_seed_failed", extra={"error": str(exc)})
        return {"error": str(exc)}
