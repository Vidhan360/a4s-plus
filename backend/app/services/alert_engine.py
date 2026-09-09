"""Reusable alert engine with deduplication, cooldown and escalation.

The engine is deliberately source-agnostic: health thresholds, trend
deterioration, risk escalation, model predictions, environmental conditions,
route hazards, UAV events and security events all submit the same
:class:`AlertCandidate` shape.

Suppression model
-----------------
* **Deduplication** — a candidate's ``dedup_key`` identifies "the same problem".
  While an alert with that key is OPEN, a repeat does not create a new row; it
  increments ``occurrence_count`` and refreshes ``last_triggered_at``.
* **Cooldown** — after an alert is resolved, the same key is suppressed for a
  severity-dependent cooldown window, so a flapping signal cannot spam the
  operator.
* **Escalation** — if a repeat arrives at a strictly higher severity, the open
  alert is escalated in place (severity raised, ``escalated_from`` recorded)
  rather than duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.defaults import DEFAULT_ALERT_RULES
from app.core.logging import get_logger
from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    RiskCategory,
)
from app.models.personnel import HealthAlert
from app.services.risk_engine import RiskAssessmentResult, recommended_action

logger = get_logger(__name__)


@dataclass
class AlertCandidate:
    """A proposed alert, before dedup/cooldown/escalation are applied."""

    alert_type: AlertType
    severity: AlertSeverity
    title: str
    reason: str
    dedup_key: str
    recommended_action: str = ""
    personnel_id: UUID | None = None
    triggering_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertOutcome:
    """What the engine actually did with a candidate."""

    action: str  # "created" | "escalated" | "deduplicated" | "suppressed"
    alert: HealthAlert | None
    reason: str = ""

    @property
    def is_new(self) -> bool:
        return self.action in ("created", "escalated")


SEVERITY_FOR_CATEGORY: dict[RiskCategory, AlertSeverity] = {
    RiskCategory.LOW: AlertSeverity.INFO,
    RiskCategory.MODERATE: AlertSeverity.WARNING,
    RiskCategory.HIGH: AlertSeverity.HIGH,
    RiskCategory.CRITICAL: AlertSeverity.CRITICAL,
}


class AlertEngine:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = {**DEFAULT_ALERT_RULES, **(rules or {})}

    def cooldown_for(self, severity: AlertSeverity) -> timedelta:
        seconds = self.rules.get("cooldown_seconds", {}).get(severity.value, 600)
        return timedelta(seconds=int(seconds))

    # ------------------------------------------------------------- submission
    async def submit(
        self, session: AsyncSession, candidate: AlertCandidate, now: datetime | None = None
    ) -> AlertOutcome:
        """Apply dedup/cooldown/escalation and persist when appropriate."""
        now = now or datetime.now(timezone.utc)

        existing = (
            await session.execute(
                select(HealthAlert)
                .where(
                    HealthAlert.dedup_key == candidate.dedup_key,
                    HealthAlert.status.in_(
                        [AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]
                    ),
                )
                .order_by(HealthAlert.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if existing is not None:
            current_rank = AlertSeverity(existing.severity).rank
            if (
                self.rules.get("escalation_enabled", True)
                and candidate.severity.rank > current_rank
            ):
                existing.escalated_from = existing.severity
                existing.severity = candidate.severity.value
                existing.title = candidate.title
                existing.reason = candidate.reason
                existing.recommended_action = candidate.recommended_action
                existing.triggering_data = candidate.triggering_data
                existing.occurrence_count += 1
                existing.last_triggered_at = now
                # Escalation re-opens an acknowledged alert: the situation
                # materially worsened, so it needs attention again.
                existing.status = AlertStatus.OPEN.value
                existing.acknowledged_at = None
                existing.acknowledged_by_id = None
                await session.flush()
                return AlertOutcome(
                    "escalated",
                    existing,
                    f"Escalated from {existing.escalated_from} to {candidate.severity.value}.",
                )
            existing.occurrence_count += 1
            existing.last_triggered_at = now
            await session.flush()
            return AlertOutcome(
                "deduplicated",
                existing,
                f"An open alert for this condition already exists "
                f"(occurrence {existing.occurrence_count}).",
            )

        # Cooldown against recently resolved/suppressed alerts.
        cooldown = self.cooldown_for(candidate.severity)
        recent = (
            await session.execute(
                select(HealthAlert)
                .where(
                    HealthAlert.dedup_key == candidate.dedup_key,
                    HealthAlert.last_triggered_at >= now - cooldown,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent is not None:
            return AlertOutcome(
                "suppressed",
                None,
                f"Within the {int(cooldown.total_seconds())}s cooldown window for "
                f"{candidate.severity.value} alerts on this condition.",
            )

        # Cap open alerts per person so one deteriorating individual cannot
        # flood the operator's queue.
        if candidate.personnel_id is not None:
            open_count = (
                await session.execute(
                    select(func.count())
                    .select_from(HealthAlert)
                    .where(
                        HealthAlert.personnel_id == candidate.personnel_id,
                        HealthAlert.status == AlertStatus.OPEN.value,
                    )
                )
            ).scalar_one()
            limit = int(self.rules.get("max_open_alerts_per_person", 8))
            if open_count >= limit and candidate.severity is not AlertSeverity.CRITICAL:
                return AlertOutcome(
                    "suppressed",
                    None,
                    f"This individual already has {open_count} open alerts "
                    f"(limit {limit}). Only CRITICAL alerts bypass this cap.",
                )

        alert = HealthAlert(
            personnel_id=candidate.personnel_id,
            alert_type=candidate.alert_type.value,
            severity=candidate.severity.value,
            title=candidate.title,
            reason=candidate.reason,
            recommended_action=candidate.recommended_action,
            triggering_data=candidate.triggering_data,
            status=AlertStatus.OPEN.value,
            dedup_key=candidate.dedup_key,
            occurrence_count=1,
            last_triggered_at=now,
            created_at=now,
        )
        session.add(alert)
        await session.flush()
        return AlertOutcome("created", alert, "New alert raised.")

    # ----------------------------------------------------------- health rules
    def evaluate_health(
        self,
        personnel_id: UUID,
        call_sign: str,
        assessment: RiskAssessmentResult,
        thresholds: dict[str, Any],
        reading: Any,
    ) -> list[AlertCandidate]:
        """Derive alert candidates from a risk assessment and its reading."""
        candidates: list[AlertCandidate] = []
        top = [f.feature for f in assessment.top_factors]

        # --- Risk escalation ---
        alert_categories = set(self.rules.get("risk_alert_categories", []))
        if assessment.category.value in alert_categories:
            severity = SEVERITY_FOR_CATEGORY[assessment.category]
            drivers = ", ".join(f.label for f in assessment.top_factors[:3])
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.RISK_ESCALATION,
                    severity=severity,
                    title=f"{call_sign}: {assessment.category.value} health risk",
                    reason=(
                        f"Composite risk score {assessment.risk_score:.1f}/100 "
                        f"({assessment.category.value}). Leading contributors: "
                        f"{drivers or 'none identified'}."
                    ),
                    dedup_key=f"health:risk:{personnel_id}:{assessment.category.value}",
                    recommended_action=recommended_action(assessment.category, top),
                    personnel_id=personnel_id,
                    triggering_data={
                        "risk_score": assessment.risk_score,
                        "category": assessment.category.value,
                        "top_factors": [f.as_dict() for f in assessment.top_factors[:5]],
                    },
                )
            )

        # --- Hard vital thresholds (independent of the composite score) ---
        spo2_limits = thresholds.get("spo2", {})
        spo2 = float(getattr(reading, "spo2", 100.0))
        if spo2 < float(spo2_limits.get("critical_below", 85.0)):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.VITAL_THRESHOLD,
                    severity=AlertSeverity.CRITICAL,
                    title=f"{call_sign}: critical oxygen saturation",
                    reason=(
                        f"SpO₂ {spo2:.1f}% is below the configured critical bound "
                        f"of {spo2_limits.get('critical_below')}%."
                    ),
                    dedup_key=f"health:spo2:critical:{personnel_id}",
                    recommended_action=(
                        "Administer supplemental oxygen if available and begin "
                        "immediate descent. Escalate to the medical officer now."
                    ),
                    personnel_id=personnel_id,
                    triggering_data={"spo2": spo2, "bound": spo2_limits.get("critical_below")},
                )
            )
        elif spo2 < float(spo2_limits.get("warn_below", 90.0)):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.VITAL_THRESHOLD,
                    severity=AlertSeverity.HIGH,
                    title=f"{call_sign}: low oxygen saturation",
                    reason=(
                        f"SpO₂ {spo2:.1f}% is below the configured warning bound "
                        f"of {spo2_limits.get('warn_below')}%."
                    ),
                    dedup_key=f"health:spo2:warn:{personnel_id}",
                    recommended_action=("Halt ascent, rest and re-assess within 15 minutes."),
                    personnel_id=personnel_id,
                    triggering_data={"spo2": spo2, "bound": spo2_limits.get("warn_below")},
                )
            )

        hr_limits = thresholds.get("heart_rate", {})
        hr = float(getattr(reading, "heart_rate", 0.0))
        if hr > float(hr_limits.get("critical_above", 135.0)):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.VITAL_THRESHOLD,
                    severity=AlertSeverity.CRITICAL,
                    title=f"{call_sign}: critical tachycardia",
                    reason=(
                        f"Heart rate {hr:.0f} bpm exceeds the configured critical "
                        f"bound of {hr_limits.get('critical_above')} bpm."
                    ),
                    dedup_key=f"health:hr:critical:{personnel_id}",
                    recommended_action=(
                        "Stop all exertion immediately and escalate to the medical officer."
                    ),
                    personnel_id=personnel_id,
                    triggering_data={"heart_rate": hr},
                )
            )

        temp_limits = thresholds.get("body_temp_c", {})
        temp = float(getattr(reading, "body_temp_c", 37.0))
        if temp < float(temp_limits.get("critical_below", 35.0)):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.VITAL_THRESHOLD,
                    severity=AlertSeverity.CRITICAL,
                    title=f"{call_sign}: core temperature critically low",
                    reason=(
                        f"Core temperature {temp:.1f} °C is below the configured "
                        f"critical bound of {temp_limits.get('critical_below')} °C."
                    ),
                    dedup_key=f"health:temp:critical:{personnel_id}",
                    recommended_action=(
                        "Begin active rewarming and shelter immediately; treat as "
                        "a hypothermia emergency."
                    ),
                    personnel_id=personnel_id,
                    triggering_data={"body_temp_c": temp},
                )
            )

        # --- Trend deterioration (fires before an absolute bound is breached) ---
        trends = assessment.trends
        trend_cfg = thresholds.get("trends", {})
        spo2_drop = -min(0.0, trends.get("spo2_delta", 0.0))
        if spo2_drop >= float(trend_cfg.get("spo2_drop_critical", 5.0)):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.TREND_DETERIORATION,
                    severity=AlertSeverity.HIGH,
                    title=f"{call_sign}: rapid SpO₂ decline",
                    reason=(
                        f"SpO₂ fell {spo2_drop:.1f} points over the last "
                        f"{trends.get('window_minutes', 0):.0f} minutes, exceeding "
                        f"the configured critical rate of "
                        f"{trend_cfg.get('spo2_drop_critical')} points."
                    ),
                    dedup_key=f"health:trend:spo2:{personnel_id}",
                    recommended_action=(
                        "Investigate now — a fast decline can reach a critical "
                        "level before the next scheduled check."
                    ),
                    personnel_id=personnel_id,
                    triggering_data={
                        "spo2_delta": trends.get("spo2_delta"),
                        "window_minutes": trends.get("window_minutes"),
                    },
                )
            )

        altitude_gain = trends.get("altitude_delta", 0.0)
        if altitude_gain >= float(trend_cfg.get("altitude_gain_critical", 500.0)):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.ENVIRONMENTAL,
                    severity=AlertSeverity.WARNING,
                    title=f"{call_sign}: rapid altitude gain",
                    reason=(
                        f"Ascended {altitude_gain:.0f} m in "
                        f"{trends.get('window_minutes', 0):.0f} minutes, which "
                        "exceeds the configured acclimatisation rate."
                    ),
                    dedup_key=f"health:trend:altitude:{personnel_id}",
                    recommended_action=(
                        "Slow the ascent profile and hold altitude to acclimatise."
                    ),
                    personnel_id=personnel_id,
                    triggering_data={"altitude_delta": altitude_gain},
                )
            )
        return candidates

    def evaluate_prediction(
        self, personnel_id: UUID, call_sign: str, prediction: Any
    ) -> list[AlertCandidate]:
        """Raise a predictive alert when a model forecasts elevated risk."""
        threshold = float(self.rules.get("prediction_probability_threshold", 0.65))
        probability = float(getattr(prediction, "risk_probability", 0.0))
        if probability < threshold:
            return []
        # A prediction from a fallback model must not masquerade as a model
        # forecast, but it is still actionable, so it is labelled explicitly.
        fallback = getattr(prediction, "fallback_reason", None)
        model_label = (
            f"{prediction.model_name} {prediction.model_version}"
            if not fallback
            else f"{prediction.model_name} (fallback)"
        )
        severity = AlertSeverity.CRITICAL if probability >= 0.85 else AlertSeverity.HIGH
        drivers = ", ".join(
            c.label
            for c in sorted(
                getattr(prediction, "contributions", []),
                key=lambda c: -abs(c.contribution),
            )[:3]
        )
        return [
            AlertCandidate(
                alert_type=AlertType.PREDICTED_RISK,
                severity=severity,
                title=f"{call_sign}: elevated risk predicted in {prediction.horizon_minutes} min",
                reason=(
                    f"{model_label} forecasts a {probability:.0%} probability of "
                    f"{prediction.predicted_category.value} risk within "
                    f"{prediction.horizon_minutes} minutes. Principal drivers: "
                    f"{drivers or 'not attributable to a single channel'}. "
                    "Prediction is based on simulated data and is not a "
                    "clinical diagnosis."
                ),
                dedup_key=f"health:prediction:{personnel_id}",
                recommended_action=getattr(prediction, "recommended_action", ""),
                personnel_id=personnel_id,
                triggering_data={
                    "model_name": prediction.model_name,
                    "model_version": prediction.model_version,
                    "risk_probability": round(probability, 4),
                    "predicted_category": prediction.predicted_category.value,
                    "horizon_minutes": prediction.horizon_minutes,
                    "explanation_method": prediction.explanation_method.value,
                    "data_provenance": prediction.data_provenance,
                    "fallback_reason": fallback,
                },
            )
        ]

    def from_drone_event(self, event: Any, drone_call_sign: str) -> list[AlertCandidate]:
        """Promote significant UAV events into operator alerts."""
        severity_map = {
            "INFO": AlertSeverity.INFO,
            "WARNING": AlertSeverity.WARNING,
            "HIGH": AlertSeverity.HIGH,
            "CRITICAL": AlertSeverity.CRITICAL,
        }
        severity = severity_map.get(str(event.severity), AlertSeverity.INFO)
        if severity.rank < AlertSeverity.HIGH.rank:
            return []
        return [
            AlertCandidate(
                alert_type=AlertType.UAV_EVENT,
                severity=severity,
                title=f"UAV {drone_call_sign}: {event.event_type.value.replace('_', ' ').lower()}",
                reason=event.message,
                dedup_key=f"uav:{event.drone_id}:{event.event_type.value}",
                recommended_action=(
                    "Verify the unit's telemetry, treat spoofed position data as "
                    "untrusted and consider recovering the aircraft."
                ),
                triggering_data={"simulated": True, **event.payload},
            )
        ]

    def from_route_hazard(
        self, route_name: str, calculation: Any, route_id: UUID
    ) -> list[AlertCandidate]:
        """Warn when a planned route retains significant hazard exposure."""
        if calculation.max_cell_risk < 55.0:
            return []
        severity = AlertSeverity.HIGH if calculation.max_cell_risk >= 75 else AlertSeverity.WARNING
        return [
            AlertCandidate(
                alert_type=AlertType.ROUTE_HAZARD,
                severity=severity,
                title=f"Route {route_name}: residual hazard exposure",
                reason=(
                    f"The planned route crosses a cell with a composite hazard "
                    f"score of {calculation.max_cell_risk:.0f}/100 "
                    f"(mean {calculation.risk_score:.0f}/100). Peak layer values: "
                    + ", ".join(f"{k} {v:.2f}" for k, v in calculation.peak_hazards.items())
                    + "."
                ),
                dedup_key=f"route:hazard:{route_id}",
                recommended_action=(
                    "Review the hazard overlay and consider an alternative "
                    "corridor or a different departure window."
                ),
                triggering_data={
                    "max_cell_risk": calculation.max_cell_risk,
                    "risk_score": calculation.risk_score,
                    "peak_hazards": calculation.peak_hazards,
                },
            )
        ]

    async def auto_resolve_stale(self, session: AsyncSession, now: datetime | None = None) -> int:
        """Resolve open alerts that have not re-fired for the configured period."""
        minutes = int(self.rules.get("auto_resolve_after_minutes", 120))
        if minutes <= 0:
            return 0
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=minutes)
        result = await session.execute(
            update(HealthAlert)
            .where(
                and_(
                    HealthAlert.status.in_(
                        [AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]
                    ),
                    HealthAlert.last_triggered_at < cutoff,
                )
            )
            .values(
                status=AlertStatus.RESOLVED.value,
                resolved_at=now,
                resolution_note=(
                    f"Auto-resolved: the triggering condition has not recurred "
                    f"for {minutes} minutes."
                ),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)
