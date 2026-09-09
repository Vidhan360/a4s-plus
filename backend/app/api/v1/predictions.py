"""``/api/v1/predictions`` — LSTM inference, model registry and explainability.

The "WHY THIS RISK?" panel is served from here. Two distinct explanations are
exposed and never conflated:

* **Rule engine** — fully transparent weighted factors. The contribution of
  each factor is exactly what the engine summed.
* **LSTM** — occlusion sensitivity in logit space: each input channel is
  replaced by its window mean and the change in the elevated-risk logit is
  measured. This is a real, measured attribution, not SHAP and not a
  hand-written story.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession, require
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.permissions import Perm
from app.repositories import personnel as personnel_repo
from app.schemas.personnel import HealthPredictionOut, ModelDescriptionOut
from app.services.audit_service import AuditService
from app.services.config_service import config_service
from app.services.personnel_service import personnel_service
from app.services.prediction_service import (
    EXPLANATION_DESCRIPTIONS,
    get_prediction_service,
)
from app.services.risk_engine import VitalSnapshot

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/models", response_model=list[ModelDescriptionOut])
async def list_models(
    _user: Annotated[Any, require(Perm.PREDICTION_READ)],
) -> list[ModelDescriptionOut]:
    """Registry view: which models loaded, their versions and measured metrics."""
    return [
        ModelDescriptionOut.model_validate(row) for row in get_prediction_service().describe_all()
    ]


@router.post("/reload")
async def reload_models(
    request: Request,
    session: DbSession,
    actor: Annotated[Any, require(Perm.CONFIG_WRITE)],
) -> dict[str, Any]:
    """Re-read the artifact registry, e.g. after retraining."""
    service = get_prediction_service()
    service.reload()
    await AuditService.log_from_request(
        session,
        request,
        action="prediction.reload_models",
        resource_type="ml_model",
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return {"models": service.describe_all()}


@router.post("/{personnel_id}/run")
async def run_prediction(
    request: Request,
    personnel_id: uuid.UUID,
    session: DbSession,
    actor: Annotated[Any, require(Perm.PREDICTION_RUN)],
    model: Annotated[str | None, Query(max_length=48)] = None,
    persist: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    person = await personnel_service.get_or_404(session, personnel_id)
    service = get_prediction_service()
    # No explicit model requested -> use the operator-configured active model.
    if model is None:
        prediction_cfg = await config_service.prediction(session)
        model = prediction_cfg.get("active_model") or settings.ml_active_model
    chosen = service.get(model)
    readings = await personnel_repo.recent_readings(
        session, personnel_id, limit=max(chosen.sequence_length, 40)
    )
    if not readings:
        raise ValidationError(
            "No readings stored for this person yet, so there is nothing to "
            "predict from. Start the simulation or ingest a reading first."
        )
    snapshots = [VitalSnapshot.from_reading(r, person) for r in readings]
    prediction = service.predict(readings, snapshots, model_name=model)

    row = None
    if persist:
        from app.models.personnel import HealthPrediction

        row = HealthPrediction(
            id=uuid.uuid4(),
            personnel_id=person.id,
            model_name=prediction.model_name,
            model_version=prediction.model_version,
            horizon_minutes=prediction.horizon_minutes,
            risk_probability=prediction.risk_probability,
            predicted_category=prediction.predicted_category.value,
            contributions=prediction.contributions_payload(),
            explanation_method=prediction.explanation_method.value,
            data_provenance=prediction.data_provenance,
            sequence_length=prediction.sequence_length,
            inference_ms=prediction.inference_ms,
            trajectory={"points": prediction.trajectory},
        )
        session.add(row)
        await session.flush()

    await AuditService.log_from_request(
        session,
        request,
        action="prediction.run",
        resource_type="personnel",
        resource_id=str(personnel_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={
            "model": prediction.model_name,
            "version": prediction.model_version,
            "persisted": persist,
        },
    )
    return {
        "personnel_id": str(personnel_id),
        "call_sign": person.call_sign,
        "model_name": prediction.model_name,
        "model_version": prediction.model_version,
        "risk_probability": round(prediction.risk_probability, 5),
        "predicted_category": prediction.predicted_category.value,
        "horizon_minutes": prediction.horizon_minutes,
        "sequence_length": prediction.sequence_length,
        "inference_ms": round(prediction.inference_ms, 3),
        "readings_used": len(readings),
        "explanation": prediction.contributions_payload(),
        "recommended_action": prediction.recommended_action,
        "trajectory": prediction.trajectory,
        "metrics": prediction.metrics,
        "data_provenance": prediction.data_provenance,
        "fallback_reason": prediction.fallback_reason,
        "persisted_id": str(row.id) if row is not None else None,
    }


@router.get("/{personnel_id}/compare")
async def compare_models(
    personnel_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.PREDICTION_READ)],
) -> dict[str, Any]:
    """Run every available model on the same window, side by side."""
    person = await personnel_service.get_or_404(session, personnel_id)
    readings = await personnel_repo.recent_readings(session, personnel_id, limit=60)
    if not readings:
        raise ValidationError("No readings stored for this person yet.")
    snapshots = [VitalSnapshot.from_reading(r, person) for r in readings]
    service = get_prediction_service()
    return {
        "personnel_id": str(personnel_id),
        "call_sign": person.call_sign,
        "readings_used": len(readings),
        "results": service.compare(readings, snapshots),
        "note": (
            "Live side-by-side inference on the same input window. The offline "
            "held-out metrics reported on the Analytics page are the correct "
            "basis for comparing model quality; this view shows agreement or "
            "disagreement on one person right now."
        ),
    }


@router.get("/{personnel_id}/history", response_model=list[HealthPredictionOut])
async def prediction_history(
    personnel_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.PREDICTION_READ)],
    model: Annotated[str | None, Query(max_length=48)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[HealthPredictionOut]:
    await personnel_service.get_or_404(session, personnel_id)
    rows = await personnel_repo.prediction_history(
        session, personnel_id, limit=limit, model_name=model
    )
    return [HealthPredictionOut.model_validate(r) for r in rows]


@router.get("/explain/{prediction_id}")
async def explain_prediction(
    prediction_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.PREDICTION_READ)],
) -> dict[str, Any]:
    """ "WHY THIS RISK?" for one stored prediction."""
    from app.models.personnel import HealthPrediction

    row = await session.get(HealthPrediction, prediction_id)
    if row is None:
        raise NotFoundError("Prediction not found.")
    from app.models.enums import ExplanationMethod

    method = ExplanationMethod(row.explanation_method)
    return {
        "prediction_id": str(row.id),
        "personnel_id": str(row.personnel_id),
        "model_name": row.model_name,
        "model_version": row.model_version,
        "predicted_category": row.predicted_category,
        "risk_probability": row.risk_probability,
        "horizon_minutes": row.horizon_minutes,
        "explanation_method": method.value,
        "method_description": EXPLANATION_DESCRIPTIONS[method],
        "explanation": row.contributions,
        "trajectory": row.trajectory,
        "data_provenance": row.data_provenance,
        "created_at": row.created_at,
    }


@router.get("/methods")
async def explanation_methods(
    _user: Annotated[Any, require(Perm.PREDICTION_READ)],
) -> dict[str, Any]:
    return {
        "methods": [
            {"code": method.value, "description": description}
            for method, description in EXPLANATION_DESCRIPTIONS.items()
        ],
        "not_implemented": [
            {
                "name": "SHAP",
                "reason": (
                    "Kernel/Deep SHAP is not used in this prototype. Rather than "
                    "present approximate values as SHAP, the system reports "
                    "occlusion sensitivity, which is directly measured from the "
                    "trained network."
                ),
            }
        ],
    }
