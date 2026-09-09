"""``/api/v1/dashboard`` and ``/api/v1/analytics``."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession, require
from app.core.permissions import Perm
from app.schemas.system import AnalyticsOut, DashboardOut
from app.services.analytics_service import analytics_service
from app.services.dashboard_service import dashboard_service
from app.services.twin_service import DigitalTwinService

router = APIRouter(tags=["dashboard"])
twins = DigitalTwinService()


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    session: DbSession,
    _user: Annotated[Any, require(Perm.DASHBOARD_READ)],
) -> DashboardOut:
    return DashboardOut.model_validate(await dashboard_service.snapshot(session))


@router.get("/dashboard/twins")
async def twin_grid(
    session: DbSession,
    _user: Annotated[Any, require(Perm.TWIN_READ)],
) -> dict[str, Any]:
    """Compact twin rows for the dashboard grid."""
    from app.repositories import personnel as personnel_repo

    rows = await personnel_repo.twin_rows(session)
    return {
        "items": [twins.summary_row(r) for r in rows],
        "total": len(rows),
        "provenance": "SIMULATED",
    }


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(
    session: DbSession,
    _user: Annotated[Any, require(Perm.ANALYTICS_READ)],
    hours: Annotated[int, Query(ge=1, le=336)] = 24,
    bucket_minutes: Annotated[int, Query(ge=5, le=360)] = 30,
    personnel_id: Annotated[uuid.UUID | None, Query()] = None,
) -> AnalyticsOut:
    return AnalyticsOut.model_validate(
        await analytics_service.overview(
            session,
            hours=hours,
            bucket_minutes=bucket_minutes,
            personnel_id=personnel_id,
        )
    )


@router.get("/analytics/model-comparison")
async def model_comparison(
    _user: Annotated[Any, require(Perm.ANALYTICS_READ)],
) -> dict[str, Any]:
    """Measured offline metrics from the last training run."""
    from app.services.analytics_service import load_model_comparison

    rows, source = load_model_comparison()
    return {
        "models": rows,
        "source": source,
        "caveats": [
            "Training and evaluation data are synthetic, produced by this "
            "project's own simulation engine.",
            "Labels are the rule engine's risk category at t + horizon, so the "
            "learned models are compared against a deterministic teacher, not "
            "against clinical ground truth.",
            "These numbers say nothing about real-world physiological accuracy.",
        ],
    }
