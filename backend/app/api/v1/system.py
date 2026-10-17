"""``/api/v1`` system endpoints: health, readiness and metadata."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings
from app.core.events import get_event_bus
from app.core.logging import get_logger
from app.schemas.system import HealthCheckOut
from app.services.dashboard_service import DISCLAIMER
from app.services.prediction_service import get_prediction_service

router = APIRouter(tags=["system"])
logger = get_logger("app.system")
STARTED_AT = time.time()


@router.get("/health", response_model=HealthCheckOut)
async def health(session: DbSession) -> HealthCheckOut:
    """Liveness plus dependency status. Unauthenticated by design."""
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("database_health_check_failed", extra={"error": str(exc)})
        database = f"error: {type(exc).__name__}: {exc}"

    service = get_prediction_service()
    from app.simulation.engine import simulation_engine

    return HealthCheckOut(
        status="ok" if database == "ok" else "degraded",
        version=settings.app_version,
        environment=settings.env,
        database=database,
        event_bus=get_event_bus().backend,
        ml_models={
            model["name"]: {
                "available": model["available"],
                "version": model["version"],
                "load_error": model.get("load_error"),
            }
            for model in service.describe_all()
        },
        simulation=simulation_engine.status.value,
        uptime_seconds=round(time.time() - STARTED_AT, 1),
        disclaimer=DISCLAIMER,
    )


@router.get("/meta")
async def meta() -> dict[str, Any]:
    """Static project metadata used by the UI footer and about panel."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "team": "The Third Eye",
        "tagline": "From detection → prediction → prevention",
        "prototype_status": "SOFTWARE PROTOTYPE",
        "data_mode": "SIMULATED DATA",
        "validation_status": "NOT CLINICALLY VALIDATED",
        "capabilities": {
            "real_sensors": False,
            "real_uav_control": False,
            "clinical_validation": False,
            "encrypted_data_at_rest": False,
            "authenticated_encryption_demo": True,
        },
        "disclaimer": DISCLAIMER,
    }


@router.get("/db-status")
async def db_status(session: DbSession) -> dict[str, Any]:
    """Database schema and migration status inspection (no secrets)."""
    from app.core.migration_runner import get_migration_status

    return await get_migration_status(session)

