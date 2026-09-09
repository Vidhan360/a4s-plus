"""Digital twin state builder.

The twin is the composite current state of one person:

    PERSON + VITALS + ENVIRONMENT + LOCATION + RISK + PREDICTION + HISTORY

It is maintained as a denormalised row in ``digital_twin_states`` so the
dashboard and twin page read one row instead of joining six tables per render.
The row is rebuilt on every ingested reading, so it is never stale while the
pipeline is running.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.defaults import DATA_DISCLAIMER
from app.models.enums import AlertSeverity
from app.models.personnel import (
    DigitalTwinState,
    HealthAlert,
    HealthPrediction,
    Personnel,
    RiskAssessment,
    VitalReading,
)
from app.services.risk_engine import RiskAssessmentResult, recommended_action

#: A twin is considered stale if no reading has arrived within this window.
STALE_AFTER = timedelta(minutes=15)

#: Reference bands surfaced to the UI so gauges can render meaningful ranges.
VITAL_DISPLAY_RANGES: dict[str, dict[str, Any]] = {
    "heart_rate": {"min": 40, "max": 180, "normal_min": 50, "normal_max": 100, "unit": "bpm"},
    "spo2": {"min": 70, "max": 100, "normal_min": 92, "normal_max": 100, "unit": "%"},
    "respiratory_rate": {"min": 6, "max": 40, "normal_min": 10, "normal_max": 20, "unit": "br/min"},
    "body_temp_c": {"min": 33, "max": 40, "normal_min": 36, "normal_max": 37.5, "unit": "°C"},
    "fatigue_score": {"min": 0, "max": 100, "normal_min": 0, "normal_max": 60, "unit": "index"},
    "bp_systolic": {"min": 80, "max": 190, "normal_min": 100, "normal_max": 140, "unit": "mmHg"},
}


class DigitalTwinService:
    """Builds and persists the twin read model."""

    async def rebuild(
        self,
        session: AsyncSession,
        *,
        personnel: Personnel,
        reading: VitalReading,
        assessment: RiskAssessmentResult,
        risk_row: RiskAssessment | None = None,
        prediction: Any | None = None,
        prediction_row: HealthPrediction | None = None,
        open_alerts: Sequence[HealthAlert] = (),
        history: Sequence[VitalReading] = (),
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        state = self.serialise(
            personnel=personnel,
            reading=reading,
            assessment=assessment,
            prediction=prediction,
            open_alerts=open_alerts,
            history=history,
            now=now,
        )

        row = (
            await session.execute(
                select(DigitalTwinState).where(DigitalTwinState.personnel_id == personnel.id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = DigitalTwinState(personnel_id=personnel.id, updated_at=now)
            session.add(row)
        row.latest_reading_id = reading.id
        row.latest_risk_id = risk_row.id if risk_row else row.latest_risk_id
        row.latest_prediction_id = prediction_row.id if prediction_row else row.latest_prediction_id
        row.risk_score = assessment.risk_score
        row.risk_category = assessment.category.value
        row.open_alert_count = len(open_alerts)
        row.state = state
        row.is_stale = False
        row.updated_at = now
        await session.flush()
        return state

    def serialise(
        self,
        *,
        personnel: Personnel,
        reading: VitalReading,
        assessment: RiskAssessmentResult,
        prediction: Any | None,
        open_alerts: Sequence[HealthAlert],
        history: Sequence[VitalReading],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        recorded_at = reading.recorded_at
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (now - recorded_at).total_seconds())
        top = [f.feature for f in assessment.top_factors]
        severities = [AlertSeverity(a.severity) for a in open_alerts]
        highest = max(severities, key=lambda s: s.rank).value if severities else None

        return {
            "personnel": {
                "id": str(personnel.id),
                "call_sign": personnel.call_sign,
                "name": personnel.name,
                "age": personnel.age,
                "unit": personnel.unit,
                "rank": personnel.rank,
                "status": personnel.status,
                "baseline_heart_rate": personnel.baseline_heart_rate,
                "baseline_spo2": personnel.baseline_spo2,
            },
            "vitals": {
                "recorded_at": recorded_at.isoformat(),
                "age_seconds": round(age_seconds, 1),
                "heart_rate": reading.heart_rate,
                "spo2": reading.spo2,
                "body_temp_c": reading.body_temp_c,
                "respiratory_rate": reading.respiratory_rate,
                "bp_systolic": reading.bp_systolic,
                "bp_diastolic": reading.bp_diastolic,
                "fatigue_score": reading.fatigue_score,
                "activity_level": reading.activity_level,
                "deltas": {
                    "heart_rate": round(
                        reading.heart_rate - (personnel.baseline_heart_rate or 0), 1
                    ),
                    "spo2": round(reading.spo2 - (personnel.baseline_spo2 or 0), 1),
                },
                "ranges": VITAL_DISPLAY_RANGES,
            },
            "environment": {
                "env_temp_c": reading.env_temp_c,
                "wind_kph": reading.wind_kph,
                "altitude_m": reading.altitude_m,
                "wind_chill_note": (
                    "Combined cold and wind exposure is treated as one "
                    "environmental stress factor by the risk engine."
                ),
            },
            "location": {
                "latitude": reading.latitude,
                "longitude": reading.longitude,
                "grid_x": reading.grid_x,
                "grid_y": reading.grid_y,
                "altitude_m": reading.altitude_m,
            },
            "risk": {
                "score": assessment.risk_score,
                "category": assessment.category.value,
                "raw_ratio": assessment.raw_ratio,
                "scale_ratio": assessment.scale_ratio,
                "top_factors": [f.as_dict() for f in assessment.top_factors[:6]],
                "all_factors": [f.as_dict() for f in assessment.factors],
                "trends": {k: round(v, 3) for k, v in assessment.trends.items()},
                "recommended_action": recommended_action(assessment.category, top),
            },
            "prediction": (
                {
                    "model_name": prediction.model_name,
                    "model_version": prediction.model_version,
                    "risk_probability": round(prediction.risk_probability, 4),
                    "predicted_category": prediction.predicted_category.value,
                    "horizon_minutes": prediction.horizon_minutes,
                    "explanation_method": prediction.explanation_method.value,
                    "data_provenance": prediction.data_provenance,
                    "narrative": prediction.narrative,
                    "recommended_action": prediction.recommended_action,
                    "top_contributions": [
                        c.as_dict()
                        for c in sorted(
                            prediction.contributions, key=lambda c: -abs(c.contribution)
                        )[:6]
                    ],
                    "class_probabilities": {
                        k: round(v, 5) for k, v in prediction.class_probabilities.items()
                    },
                    "trajectory": prediction.trajectory,
                    "fallback_reason": prediction.fallback_reason,
                    "inference_ms": prediction.inference_ms,
                }
                if prediction is not None
                else None
            ),
            "alerts": {
                "open_count": len(open_alerts),
                "highest_severity": highest,
                "recent": [
                    {
                        "id": str(a.id),
                        "severity": a.severity,
                        "alert_type": a.alert_type,
                        "title": a.title,
                        "reason": a.reason,
                        "status": a.status,
                        "occurrence_count": a.occurrence_count,
                        "created_at": a.created_at.isoformat(),
                    }
                    for a in list(open_alerts)[:5]
                ],
            },
            "history": {
                "samples": len(history),
                "series": [
                    {
                        "recorded_at": (
                            r.recorded_at.replace(tzinfo=timezone.utc)
                            if r.recorded_at.tzinfo is None
                            else r.recorded_at
                        ).isoformat(),
                        "heart_rate": r.heart_rate,
                        "spo2": r.spo2,
                        "respiratory_rate": r.respiratory_rate,
                        "body_temp_c": r.body_temp_c,
                        "fatigue_score": r.fatigue_score,
                        "altitude_m": r.altitude_m,
                        "is_predicted": False,
                    }
                    for r in list(history)[-40:]
                ],
            },
            "provenance": {
                "source": reading.source,
                "scenario": reading.scenario,
                "is_simulated": reading.source == "SIMULATION",
                "disclaimer": DATA_DISCLAIMER,
            },
            "updated_at": now.isoformat(),
        }

    async def get(self, session: AsyncSession, personnel_id: Any) -> dict[str, Any] | None:
        """Read the stored twin, flagging staleness at read time."""
        row = (
            await session.execute(
                select(DigitalTwinState).where(DigitalTwinState.personnel_id == personnel_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        state = dict(row.state or {})
        updated = row.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        is_stale = (datetime.now(timezone.utc) - updated) > STALE_AFTER
        state["is_stale"] = is_stale
        if is_stale:
            state["stale_note"] = (
                "No reading has been ingested recently. Start the simulation to "
                "resume live updates."
            )
        return state

    async def mark_all_stale(self, session: AsyncSession) -> int:
        """Flag every twin stale, e.g. when the simulation stops."""
        rows = (await session.execute(select(DigitalTwinState))).scalars().all()
        for row in rows:
            row.is_stale = True
        await session.flush()
        return len(rows)

    @staticmethod
    def summary_row(row: DigitalTwinState) -> dict[str, Any]:
        """Compact projection for the personnel list and dashboard grid."""
        state = row.state or {}
        personnel = state.get("personnel", {})
        vitals = state.get("vitals", {})
        prediction = state.get("prediction") or {}
        return {
            "personnel_id": str(row.personnel_id),
            "call_sign": personnel.get("call_sign"),
            "name": personnel.get("name"),
            "unit": personnel.get("unit"),
            "status": personnel.get("status"),
            "risk_score": row.risk_score,
            "risk_category": row.risk_category,
            "open_alert_count": row.open_alert_count,
            "heart_rate": vitals.get("heart_rate"),
            "spo2": vitals.get("spo2"),
            "altitude_m": (state.get("environment") or {}).get("altitude_m"),
            "grid_x": (state.get("location") or {}).get("grid_x"),
            "grid_y": (state.get("location") or {}).get("grid_y"),
            "predicted_category": prediction.get("predicted_category"),
            "risk_probability": prediction.get("risk_probability"),
            "model_name": prediction.get("model_name"),
            "is_stale": row.is_stale,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
