"""Analytics over persisted simulated history.

Everything reported here is computed from rows actually in the database, or
read from ML artifact metadata produced by a real training run. Nothing is
hard-coded or estimated.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RiskCategory
from app.repositories import alerts as alert_repo
from app.repositories import personnel as personnel_repo
from app.services.dashboard_service import DISCLAIMER
from app.services.risk_engine import VitalSnapshot

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
COMPARISON_FILE = ARTIFACT_ROOT / "last_comparison.json"

#: Vitals correlated against the rule-engine risk score.
CORRELATION_CHANNELS: tuple[tuple[str, str], ...] = (
    ("spo2", "SpO₂ (%)"),
    ("heart_rate", "Heart rate (bpm)"),
    ("respiratory_rate", "Respiratory rate (/min)"),
    ("body_temp_c", "Body temperature (°C)"),
    ("fatigue_score", "Fatigue index"),
    ("altitude_m", "Altitude (m)"),
    ("wind_kph", "Wind speed (kph)"),
)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0.0 or dy == 0.0:
        return None
    return num / (dx * dy)


def _bucket(moment: datetime, minutes: int) -> datetime:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    seconds = minutes * 60
    epoch = int(aware.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=timezone.utc)


def load_model_comparison() -> tuple[list[dict[str, Any]], str]:
    """Read measured metrics from the last training run, if present."""
    if not COMPARISON_FILE.exists():
        return [], (
            "No trained model artifacts found. Run "
            "`python -m ml.train` inside backend/ to produce measured metrics."
        )
    try:
        data = json.loads(COMPARISON_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"Model comparison file could not be read: {exc}"
    results = data.get("results", {})
    dataset = data.get("dataset", {})
    rows: list[dict[str, Any]] = []
    for name, metrics in results.items():
        if not isinstance(metrics, dict):
            continue
        elevated = metrics.get("elevated_risk_binary", {}) or {}
        rows.append(
            {
                "model": name,
                "n_samples": metrics.get("n_samples"),
                "accuracy": metrics.get("accuracy"),
                "macro_f1": metrics.get("macro_f1"),
                "weighted_f1": metrics.get("weighted_f1"),
                "macro_precision": metrics.get("macro_precision"),
                "macro_recall": metrics.get("macro_recall"),
                "elevated_f1": elevated.get("f1"),
                "elevated_precision": elevated.get("precision"),
                "elevated_recall": elevated.get("recall"),
                "elevated_roc_auc": elevated.get("roc_auc"),
                "brier_score_elevated": metrics.get("brier_score_elevated"),
                "per_class": metrics.get("per_class", {}),
                "confusion_matrix": metrics.get("confusion_matrix"),
                "confusion_matrix_labels": metrics.get("confusion_matrix_labels"),
                "note": metrics.get("note", ""),
            }
        )
    rows.sort(key=lambda r: -(r.get("macro_f1") or 0.0))
    source = (
        "Measured during the last `python -m ml.train` run"
        f" ({data.get('generated_at', 'unknown time')}) on a held-out, "
        f"subject-disjoint synthetic test split "
        f"({dataset.get('n_subjects', '?')} simulated subjects, "
        f"sequence length {dataset.get('sequence_length', '?')}, "
        f"{dataset.get('horizon_minutes', '?')}-minute horizon). "
        "Metrics describe performance on SIMULATED data only and do not imply "
        "clinical accuracy."
    )
    return rows, source


class AnalyticsService:
    async def overview(
        self,
        session: AsyncSession,
        *,
        hours: int = 24,
        bucket_minutes: int = 30,
        personnel_id: Any | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)

        readings = await personnel_repo.readings_between(session, personnel_id, since, limit=20000)
        people = {p.id: p for p in await personnel_repo.all_active_personnel(session)}

        # --- risk timeline, recomputed with the same engine the API uses -----
        from app.services.config_service import config_service

        engine = await config_service.risk_engine(session)
        by_person: dict[Any, list[VitalSnapshot]] = defaultdict(list)
        timeline_acc: dict[datetime, list[float]] = defaultdict(list)
        distribution: Counter[str] = Counter()
        factor_totals: dict[str, float] = defaultdict(float)
        factor_counts: dict[str, int] = defaultdict(int)
        factor_labels: dict[str, str] = {}
        per_person_scores: dict[Any, list[float]] = defaultdict(list)
        channel_series: dict[str, list[float]] = defaultdict(list)
        risk_series: list[float] = []

        for reading in readings:
            person = people.get(reading.personnel_id)
            snapshot = VitalSnapshot.from_reading(reading, person)
            history = by_person[reading.personnel_id]
            result = engine.evaluate(snapshot, history[-30:])
            history.append(snapshot)
            timeline_acc[_bucket(reading.recorded_at, bucket_minutes)].append(result.risk_score)
            distribution[result.category.value] += 1
            per_person_scores[reading.personnel_id].append(result.risk_score)
            risk_series.append(result.risk_score)
            for key, _label in CORRELATION_CHANNELS:
                channel_series[key].append(float(getattr(reading, key)))
            for factor in result.factors:
                if factor.contribution > 0:
                    factor_totals[factor.feature] += factor.contribution
                    factor_counts[factor.feature] += 1
                    factor_labels[factor.feature] = factor.label

        risk_timeline = [
            {
                "bucket": bucket.isoformat(),
                "mean_risk": round(sum(values) / len(values), 2),
                "max_risk": round(max(values), 2),
                "samples": len(values),
            }
            for bucket, values in sorted(timeline_acc.items())
        ]

        full_distribution = {c.value: distribution.get(c.value, 0) for c in RiskCategory}

        top_factors = sorted(
            (
                {
                    "key": key,
                    "label": factor_labels.get(key, key),
                    "total_contribution": round(total, 2),
                    "mean_contribution": round(total / max(1, factor_counts[key]), 3),
                    "occurrences": factor_counts[key],
                }
                for key, total in factor_totals.items()
            ),
            key=lambda row: -float(row["total_contribution"]),  # type: ignore[arg-type]
        )[:10]

        correlations = []
        for key, label in CORRELATION_CHANNELS:
            r = _pearson(channel_series[key], risk_series)
            correlations.append(
                {
                    "channel": key,
                    "label": label,
                    "pearson_r": None if r is None else round(r, 4),
                    "samples": len(channel_series[key]),
                    "note": (
                        "Insufficient samples"
                        if r is None
                        else "Correlated with rule-engine risk score over the window."
                    ),
                }
            )

        # --- alerts ---------------------------------------------------------
        alert_rows = await alert_repo.since(session, hours=hours)
        alert_buckets: dict[datetime, Counter[str]] = defaultdict(Counter)
        ack_deltas: list[float] = []
        for alert in alert_rows:
            alert_buckets[_bucket(alert.created_at, bucket_minutes)][alert.severity] += 1
            if alert.acknowledged_at is not None:
                created = (
                    alert.created_at
                    if alert.created_at.tzinfo
                    else alert.created_at.replace(tzinfo=timezone.utc)
                )
                acked = (
                    alert.acknowledged_at
                    if alert.acknowledged_at.tzinfo
                    else alert.acknowledged_at.replace(tzinfo=timezone.utc)
                )
                ack_deltas.append((acked - created).total_seconds())

        alert_timeline = [
            {"bucket": bucket.isoformat(), "total": sum(counts.values()), **dict(counts)}
            for bucket, counts in sorted(alert_buckets.items())
        ]
        mtta = round(sum(ack_deltas) / len(ack_deltas), 1) if ack_deltas else None

        per_person = sorted(
            (
                {
                    "personnel_id": str(pid),
                    "call_sign": people[pid].call_sign if pid in people else str(pid),
                    "samples": len(scores),
                    "mean_risk": round(sum(scores) / len(scores), 2),
                    "peak_risk": round(max(scores), 2),
                    "latest_risk": round(scores[-1], 2),
                    "scenario": (people[pid].sim_scenario if pid in people else None),
                }
                for pid, scores in per_person_scores.items()
                if scores
            ),
            key=lambda row: -float(row["peak_risk"]),  # type: ignore[arg-type]
        )

        comparison, source = load_model_comparison()

        return {
            "window_hours": hours,
            "generated_at": now,
            "readings": len(readings),
            "risk_timeline": risk_timeline,
            "risk_distribution": full_distribution,
            "alert_timeline": alert_timeline,
            "alerts_by_type": await alert_repo.counts_by_type(session, hours=hours),
            "mean_time_to_acknowledge_seconds": mtta,
            "top_risk_factors": top_factors,
            "vitals_correlation": correlations,
            "model_comparison": comparison,
            "model_metrics_source": source,
            "per_person": per_person,
            "disclaimer": DISCLAIMER,
        }


analytics_service = AnalyticsService()
