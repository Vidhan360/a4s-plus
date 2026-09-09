"""Vitals ingestion pipeline — the single entry point for all telemetry.

    DataSource (SimulationDataSource today, hardware later)
        └── IngestionService.ingest()
              ├── persist VitalReading            (storage)
              ├── RiskEngine.evaluate()           (analysis)
              ├── PredictionService.predict()     (prediction, throttled)
              ├── AlertEngine.submit()            (early alert)
              ├── DigitalTwinService.rebuild()    (twin state)
              └── EventBus.publish()              (WebSocket fan-out)

There is deliberately **no** second, simulation-only path. The simulation
engine calls exactly this method, so replacing ``SimulationDataSource`` with a
wearable or UAV source requires no change to anything downstream. The
``POST /api/v1/vitals`` endpoint also calls exactly this method, which is how a
future hardware gateway would push data in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.defaults import DATA_DISCLAIMER
from app.core.events import Topic, get_event_bus
from app.core.logging import get_logger
from app.datasources.base import VitalSample
from app.models.enums import AlertStatus, RiskEngineKind
from app.models.personnel import (
    HealthAlert,
    HealthPrediction,
    Personnel,
    RiskAssessment,
    VitalReading,
)
from app.services.alert_engine import AlertEngine
from app.services.config_service import config_service
from app.services.prediction_service import (
    Prediction,
    PredictionService,
    get_prediction_service,
)
from app.services.risk_engine import RiskAssessmentResult, RiskEngine, VitalSnapshot
from app.services.twin_service import DigitalTwinService

logger = get_logger(__name__)

#: How many historical readings to load for trend and sequence analysis.
HISTORY_LIMIT = 40


@dataclass
class IngestionResult:
    """What one ingested reading produced across the pipeline."""

    personnel_id: UUID
    call_sign: str
    reading: VitalReading
    assessment: RiskAssessmentResult
    risk_row: RiskAssessment
    prediction: Prediction | None = None
    prediction_row: HealthPrediction | None = None
    new_alerts: list[HealthAlert] = field(default_factory=list)
    alert_outcomes: list[dict[str, Any]] = field(default_factory=list)
    twin_state: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "personnel_id": str(self.personnel_id),
            "call_sign": self.call_sign,
            "risk_score": self.assessment.risk_score,
            "risk_category": self.assessment.category.value,
            "prediction": (
                {
                    "model_name": self.prediction.model_name,
                    "model_version": self.prediction.model_version,
                    "risk_probability": round(self.prediction.risk_probability, 4),
                    "predicted_category": self.prediction.predicted_category.value,
                }
                if self.prediction
                else None
            ),
            "new_alerts": len(self.new_alerts),
            "source": self.reading.source,
        }


class IngestionService:
    """Runs the detection → analysis → prediction → alert pipeline."""

    def __init__(
        self,
        prediction_service: PredictionService | None = None,
        twin_service: DigitalTwinService | None = None,
    ) -> None:
        self.predictions = prediction_service or get_prediction_service()
        self.twins = twin_service or DigitalTwinService()

    async def ingest(
        self,
        session: AsyncSession,
        sample: VitalSample,
        *,
        run_prediction: bool = True,
        model_name: str | None = None,
        publish: bool = True,
    ) -> IngestionResult:
        """Ingest one reading and run the full pipeline."""
        personnel = (
            await session.execute(select(Personnel).where(Personnel.id == sample.personnel_id))
        ).scalar_one_or_none()
        if personnel is None:
            raise KeyError(f"Unknown personnel {sample.personnel_id}")

        now = datetime.now(timezone.utc)
        row_data = sample.to_row()
        reading = VitalReading(**row_data, created_at=now)
        session.add(reading)
        await session.flush()

        # --- history for trends and model sequences (oldest-first) ---
        history_rows = list(
            reversed(
                (
                    await session.execute(
                        select(VitalReading)
                        .where(VitalReading.personnel_id == personnel.id)
                        .order_by(VitalReading.recorded_at.desc())
                        .limit(HISTORY_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
        )
        snapshots = [VitalSnapshot.from_reading(r, personnel) for r in history_rows]
        if not snapshots:
            snapshots = [VitalSnapshot.from_reading(reading, personnel)]

        # --- analysis ---
        engine: RiskEngine = await config_service.risk_engine(session)
        assessment = engine.evaluate(snapshots[-1], snapshots)
        risk_row = RiskAssessment(
            personnel_id=personnel.id,
            vital_reading_id=reading.id,
            risk_score=assessment.risk_score,
            category=assessment.category.value,
            engine=RiskEngineKind.RULE.value,
            factors=assessment.factors_payload(),
            config_version=assessment.config_version,
            created_at=now,
        )
        session.add(risk_row)
        await session.flush()

        # --- prediction ---
        prediction: Prediction | None = None
        prediction_row: HealthPrediction | None = None
        if run_prediction:
            prediction_cfg = await config_service.prediction(session)
            chosen = model_name or prediction_cfg.get("active_model", "rule_baseline")
            try:
                prediction = self.predictions.predict(history_rows, snapshots, chosen)
            except (RuntimeError, ValueError, KeyError) as exc:
                logger.info(
                    "prediction_unavailable",
                    extra={"personnel_id": str(personnel.id), "reason": str(exc)},
                )
            if prediction is not None:
                prediction_row = HealthPrediction(
                    personnel_id=personnel.id,
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
                    created_at=now,
                )
                session.add(prediction_row)
                await session.flush()

        # --- alerting ---
        alert_rules = await config_service.alert_rules(session)
        thresholds = await config_service.thresholds(session)
        alert_engine = AlertEngine(alert_rules)
        candidates = alert_engine.evaluate_health(
            personnel.id, personnel.call_sign, assessment, thresholds, reading
        )
        if prediction is not None:
            candidates += alert_engine.evaluate_prediction(
                personnel.id, personnel.call_sign, prediction
            )

        new_alerts: list[HealthAlert] = []
        outcomes: list[dict[str, Any]] = []
        for candidate in candidates:
            outcome = await alert_engine.submit(session, candidate, now)
            outcomes.append(
                {
                    "dedup_key": candidate.dedup_key,
                    "action": outcome.action,
                    "reason": outcome.reason,
                    "severity": candidate.severity.value,
                }
            )
            if outcome.alert is not None and outcome.action in ("created", "escalated"):
                new_alerts.append(outcome.alert)

        # --- digital twin read model ---
        open_alerts = (
            (
                await session.execute(
                    select(HealthAlert)
                    .where(
                        HealthAlert.personnel_id == personnel.id,
                        HealthAlert.status.in_(
                            [AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]
                        ),
                    )
                    .order_by(HealthAlert.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )

        twin_state = await self.twins.rebuild(
            session,
            personnel=personnel,
            reading=reading,
            assessment=assessment,
            risk_row=risk_row,
            prediction=prediction,
            prediction_row=prediction_row,
            open_alerts=list(open_alerts),
            history=history_rows,
        )

        result = IngestionResult(
            personnel_id=personnel.id,
            call_sign=personnel.call_sign,
            reading=reading,
            assessment=assessment,
            risk_row=risk_row,
            prediction=prediction,
            prediction_row=prediction_row,
            new_alerts=new_alerts,
            alert_outcomes=outcomes,
            twin_state=twin_state,
        )

        if publish:
            await self._publish(result)
        return result

    async def ingest_many(
        self,
        session: AsyncSession,
        samples: Sequence[VitalSample],
        *,
        run_prediction: bool = True,
        model_name: str | None = None,
        publish: bool = True,
    ) -> list[IngestionResult]:
        results = []
        for sample in samples:
            try:
                results.append(
                    await self.ingest(
                        session,
                        sample,
                        run_prediction=run_prediction,
                        model_name=model_name,
                        publish=publish,
                    )
                )
            except KeyError as exc:
                logger.warning("ingest_skipped_unknown_personnel", extra={"error": str(exc)})
        return results

    @staticmethod
    async def _publish(result: IngestionResult) -> None:
        bus = get_event_bus()
        reading = result.reading
        await bus.publish(
            Topic.VITALS.value,
            "vitals.reading",
            {
                "personnel_id": str(result.personnel_id),
                "call_sign": result.call_sign,
                "recorded_at": reading.recorded_at.isoformat(),
                "heart_rate": reading.heart_rate,
                "spo2": reading.spo2,
                "body_temp_c": reading.body_temp_c,
                "respiratory_rate": reading.respiratory_rate,
                "bp_systolic": reading.bp_systolic,
                "bp_diastolic": reading.bp_diastolic,
                "altitude_m": reading.altitude_m,
                "fatigue_score": reading.fatigue_score,
                "activity_level": reading.activity_level,
                "env_temp_c": reading.env_temp_c,
                "wind_kph": reading.wind_kph,
                "latitude": reading.latitude,
                "longitude": reading.longitude,
                "grid_x": reading.grid_x,
                "grid_y": reading.grid_y,
                "source": reading.source,
                "scenario": reading.scenario,
                "risk_score": result.assessment.risk_score,
                "risk_category": result.assessment.category.value,
                "disclaimer": DATA_DISCLAIMER,
            },
        )
        for alert in result.new_alerts:
            await bus.publish(
                Topic.ALERTS.value,
                "alert.raised",
                {
                    "id": str(alert.id),
                    "personnel_id": str(alert.personnel_id) if alert.personnel_id else None,
                    "call_sign": result.call_sign,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "title": alert.title,
                    "reason": alert.reason,
                    "recommended_action": alert.recommended_action,
                    "status": alert.status,
                    "occurrence_count": alert.occurrence_count,
                    "escalated_from": alert.escalated_from,
                    "created_at": alert.created_at.isoformat(),
                },
            )
        if result.twin_state:
            await bus.publish(Topic.DASHBOARD.value, "twin.updated", result.twin_state)
