"""``/api/v1/vitals`` — reading ingestion and cross-roster queries.

Manual ingestion exists so a reviewer can exercise the *entire* pipeline
(risk → prediction → alert → twin → WebSocket) without the simulation loop.
Provenance is forced to ``MANUAL``: a client can never label injected data as
sensor-measured.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession, require
from app.core.permissions import Perm
from app.datasources.base import EnvironmentSample, VitalSample
from app.models.enums import DataSourceKind
from app.repositories import personnel as personnel_repo
from app.schemas.personnel import VitalIngestRequest, VitalReadingOut
from app.services.audit_service import AuditService
from app.services.ingestion_service import IngestionService
from app.services.personnel_service import personnel_service

router = APIRouter(prefix="/vitals", tags=["vitals"])
ingestion = IngestionService()


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_reading(
    request: Request,
    payload: VitalIngestRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.VITALS_INGEST)],
) -> dict[str, Any]:
    person = await personnel_service.get_or_404(session, payload.personnel_id)
    sample = VitalSample(
        personnel_id=person.id,
        recorded_at=payload.recorded_at or datetime.now(timezone.utc),
        heart_rate=payload.heart_rate,
        spo2=payload.spo2,
        body_temp_c=payload.body_temp_c,
        respiratory_rate=payload.respiratory_rate,
        bp_systolic=payload.bp_systolic,
        bp_diastolic=payload.bp_diastolic,
        fatigue_score=payload.fatigue_score,
        activity_level=payload.activity_level,
        environment=EnvironmentSample(
            env_temp_c=payload.env_temp_c,
            wind_kph=payload.wind_kph,
            altitude_m=payload.altitude_m,
            latitude=payload.latitude,
            longitude=payload.longitude,
            grid_x=payload.grid_x,
            grid_y=payload.grid_y,
        ),
        source=DataSourceKind.MANUAL,
        scenario=None,
        meta={"injected_by": str(actor.id)},
    )
    result = await ingestion.ingest(
        session,
        sample,
        run_prediction=payload.run_prediction,
        model_name=payload.model_name,
    )
    await AuditService.log_from_request(
        session,
        request,
        action="vitals.ingest",
        resource_type="vital_reading",
        resource_id=str(result.reading.id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={
            "personnel_id": str(person.id),
            "risk_score": result.assessment.risk_score,
            "risk_category": result.assessment.category.value,
            "new_alerts": len(result.new_alerts),
            "provenance": DataSourceKind.MANUAL.value,
        },
    )
    return {
        "reading": VitalReadingOut.model_validate(result.reading),
        "risk": {
            "score": result.assessment.risk_score,
            "category": result.assessment.category.value,
            "top_factors": [f.as_dict() for f in result.assessment.top_factors[:6]],
        },
        "prediction": (
            {
                "model_name": result.prediction.model_name,
                "model_version": result.prediction.model_version,
                "risk_probability": round(result.prediction.risk_probability, 4),
                "predicted_category": result.prediction.predicted_category.value,
                "horizon_minutes": result.prediction.horizon_minutes,
                "explanation_method": result.prediction.explanation_method.value,
                "narrative": result.prediction.narrative,
                "fallback_reason": result.prediction.fallback_reason,
            }
            if result.prediction
            else None
        ),
        "alerts": result.alert_outcomes,
        "twin_updated": bool(result.twin_state),
        "provenance": DataSourceKind.MANUAL.value,
        "notice": (
            "Manually injected reading. Stored and labelled as MANUAL, not as sensor-measured data."
        ),
    }


@router.get("")
async def recent_vitals(
    session: DbSession,
    _user: Annotated[Any, require(Perm.VITALS_READ)],
    hours: Annotated[int, Query(ge=1, le=168)] = 6,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> dict[str, Any]:
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await personnel_repo.readings_between(session, None, since, limit=limit)
    return {
        "items": [VitalReadingOut.model_validate(r) for r in rows],
        "window_hours": hours,
        "provenance": "SIMULATED",
    }
