"""Transparent rule-based health risk engine.

Design principles
-----------------
1. **Explainable by construction.** Every factor returns a normalised 0..1
   severity plus the raw values that produced it. The score is a weighted sum,
   so the contribution of each factor is exact, not estimated. The numbers
   shown in the "Why this risk?" panel are literally the numbers used here.
2. **Configurable.** Thresholds, weights and category cut-offs are injected,
   never hard-coded at the call site.
3. **Not a diagnosis.** This produces an operational triage signal from
   simulated data. It does not diagnose, and it makes no clinical claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.defaults import (
    DEFAULT_RISK_CATEGORIES,
    DEFAULT_RISK_SCALE,
    DEFAULT_RISK_THRESHOLDS,
    DEFAULT_RISK_WEIGHTS,
)
from app.models.enums import RiskCategory


@dataclass(frozen=True)
class VitalSnapshot:
    """Plain, storage-agnostic view of one reading.

    Deliberately decoupled from the ORM so the engine can be unit-tested and so
    a future hardware DataSource can feed it directly.
    """

    recorded_at: datetime
    heart_rate: float
    spo2: float
    body_temp_c: float
    respiratory_rate: float
    bp_systolic: float
    bp_diastolic: float
    altitude_m: float
    fatigue_score: float
    activity_level: str
    env_temp_c: float
    wind_kph: float
    baseline_heart_rate: float = 64.0
    baseline_spo2: float = 97.0

    @classmethod
    def from_reading(cls, reading: Any, personnel: Any | None = None) -> VitalSnapshot:
        return cls(
            recorded_at=reading.recorded_at,
            heart_rate=float(reading.heart_rate),
            spo2=float(reading.spo2),
            body_temp_c=float(reading.body_temp_c),
            respiratory_rate=float(reading.respiratory_rate),
            bp_systolic=float(reading.bp_systolic),
            bp_diastolic=float(reading.bp_diastolic),
            altitude_m=float(reading.altitude_m),
            fatigue_score=float(reading.fatigue_score),
            activity_level=str(reading.activity_level),
            env_temp_c=float(reading.env_temp_c),
            wind_kph=float(reading.wind_kph),
            baseline_heart_rate=float(getattr(personnel, "baseline_heart_rate", 64.0) or 64.0),
            baseline_spo2=float(getattr(personnel, "baseline_spo2", 97.0) or 97.0),
        )


@dataclass
class RiskFactor:
    """One explainable contributor to the overall score."""

    feature: str
    label: str
    severity: float  # 0..1 normalised severity
    weight: float  # configured weight
    contribution: float  # weight * severity (score points)
    direction: str  # "increases" | "neutral"
    value: float | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "label": self.label,
            "severity": round(self.severity, 4),
            "weight": round(self.weight, 2),
            "contribution": round(self.contribution, 3),
            "direction": self.direction,
            "value": None if self.value is None else round(self.value, 2),
            "detail": self.detail,
        }


@dataclass
class RiskAssessmentResult:
    risk_score: float
    category: RiskCategory
    factors: list[RiskFactor] = field(default_factory=list)
    config_version: int = 1
    #: Derived trend measurements, surfaced for charts and explanations.
    trends: dict[str, float] = field(default_factory=dict)
    #: Un-rescaled fraction of maximum weighted severity (0..1).
    raw_ratio: float = 0.0
    #: Calibration constant applied to reach the reported score.
    scale_ratio: float = 0.80

    @property
    def top_factors(self) -> list[RiskFactor]:
        return sorted(
            [f for f in self.factors if f.contribution > 0.01],
            key=lambda f: f.contribution,
            reverse=True,
        )

    def factors_payload(self) -> dict[str, Any]:
        return {
            "factors": [f.as_dict() for f in self.factors],
            "top_factors": [f.as_dict() for f in self.top_factors[:6]],
            "trends": {k: round(v, 3) for k, v in self.trends.items()},
            "max_possible_score": round(sum(f.weight for f in self.factors) or 1.0, 2),
        }


def _ramp(value: float, start: float, full: float) -> float:
    """Linear 0..1 ramp from ``start`` (severity 0) to ``full`` (severity 1)."""
    if full == start:
        return 1.0 if value >= full else 0.0
    if full > start:
        if value <= start:
            return 0.0
        return min(1.0, (value - start) / (full - start))
    # Descending direction (lower value = worse).
    if value >= start:
        return 0.0
    return min(1.0, (start - value) / (start - full))


class RiskEngine:
    """Computes a 0..100 risk score with per-factor attribution."""

    def __init__(
        self,
        thresholds: dict[str, Any] | None = None,
        weights: dict[str, float] | None = None,
        categories: dict[str, float] | None = None,
        scale: dict[str, float] | None = None,
        config_version: int = 1,
    ) -> None:
        self.t = thresholds or DEFAULT_RISK_THRESHOLDS
        self.w = weights or DEFAULT_RISK_WEIGHTS
        self.c = categories or DEFAULT_RISK_CATEGORIES
        self.scale_ratio = float((scale or DEFAULT_RISK_SCALE).get("score_scale_ratio", 0.80))
        if not 0.05 <= self.scale_ratio <= 1.0:
            raise ValueError("score_scale_ratio must be between 0.05 and 1.0.")
        self.config_version = config_version

    # ---------------------------------------------------------------- helpers
    def _weight(self, key: str) -> float:
        return float(self.w.get(key, 0.0))

    def categorise(self, score: float) -> RiskCategory:
        best = RiskCategory.LOW
        for name, cut in sorted(self.c.items(), key=lambda kv: kv[1]):
            if score >= float(cut):
                best = RiskCategory(name)
        return best

    def compute_trends(
        self, history: Sequence[VitalSnapshot], current: VitalSnapshot
    ) -> dict[str, float]:
        """Measure change across the configured analysis window.

        ``history`` is expected oldest-first and to include ``current`` or end
        just before it. Returns deltas (current minus window start).
        """
        window_minutes = float(self.t.get("trends", {}).get("window_minutes", 20))
        if not history:
            return {
                "spo2_delta": 0.0,
                "hr_delta": 0.0,
                "fatigue_delta": 0.0,
                "altitude_delta": 0.0,
                "rr_delta": 0.0,
                "window_minutes": 0.0,
                "samples": 0.0,
            }
        cutoff_seconds = window_minutes * 60.0
        window = [
            s
            for s in history
            if (current.recorded_at - s.recorded_at).total_seconds() <= cutoff_seconds
        ]
        if len(window) < 2:
            window = list(history[-2:]) if len(history) >= 2 else list(history)
        if not window:
            return {
                "spo2_delta": 0.0,
                "hr_delta": 0.0,
                "fatigue_delta": 0.0,
                "altitude_delta": 0.0,
                "rr_delta": 0.0,
                "window_minutes": 0.0,
                "samples": 0.0,
            }
        first = window[0]
        span_minutes = max(0.0, (current.recorded_at - first.recorded_at).total_seconds() / 60.0)
        return {
            "spo2_delta": current.spo2 - first.spo2,
            "hr_delta": current.heart_rate - first.heart_rate,
            "fatigue_delta": current.fatigue_score - first.fatigue_score,
            "altitude_delta": current.altitude_m - first.altitude_m,
            "rr_delta": current.respiratory_rate - first.respiratory_rate,
            "window_minutes": span_minutes,
            "samples": float(len(window)),
        }

    # ------------------------------------------------------------------ score
    def evaluate(
        self,
        current: VitalSnapshot,
        history: Sequence[VitalSnapshot] = (),
    ) -> RiskAssessmentResult:
        t = self.t
        trends = self.compute_trends(history, current)
        tr = t.get("trends", {})
        factors: list[RiskFactor] = []

        def add(
            feature: str,
            label: str,
            weight_key: str,
            severity: float,
            value: float | None,
            detail: str,
        ) -> None:
            weight = self._weight(weight_key)
            sev = max(0.0, min(1.0, severity))
            factors.append(
                RiskFactor(
                    feature=feature,
                    label=label,
                    severity=sev,
                    weight=weight,
                    contribution=weight * sev,
                    direction="increases" if sev > 0 else "neutral",
                    value=value,
                    detail=detail,
                )
            )

        # --- SpO2 (absolute) ---
        sp = t["spo2"]
        sev_spo2 = _ramp(current.spo2, sp["warn_below"], sp["critical_below"])
        if current.spo2 < sp["normal_min"] and sev_spo2 == 0.0:
            sev_spo2 = 0.25  # below normal band but above the warning bound
        add(
            "spo2",
            "Blood oxygen saturation",
            "spo2",
            sev_spo2,
            current.spo2,
            f"SpO₂ {current.spo2:.1f}% against a warning bound of "
            f"{sp['warn_below']:.0f}% and a critical bound of "
            f"{sp['critical_below']:.0f}%.",
        )

        # --- SpO2 trend ---
        drop = -min(0.0, trends["spo2_delta"])
        add(
            "spo2_trend",
            "SpO₂ downward trend",
            "spo2_trend",
            _ramp(drop, tr.get("spo2_drop_warn", 2.5), tr.get("spo2_drop_critical", 5.0)),
            trends["spo2_delta"],
            f"SpO₂ changed {trends['spo2_delta']:+.1f} points over the last "
            f"{trends['window_minutes']:.0f} min ({int(trends['samples'])} samples).",
        )

        # --- Heart rate (absolute, both directions) ---
        hr = t["heart_rate"]
        sev_hr_high = _ramp(current.heart_rate, hr["warn_above"], hr["critical_above"])
        sev_hr_low = _ramp(current.heart_rate, hr["warn_below"], hr["critical_below"])
        sev_hr = max(sev_hr_high, sev_hr_low)
        if sev_hr == 0.0 and current.heart_rate > hr["normal_max"]:
            sev_hr = 0.2
        add(
            "heart_rate",
            "Heart rate",
            "heart_rate",
            sev_hr,
            current.heart_rate,
            f"Heart rate {current.heart_rate:.0f} bpm versus a personal baseline of "
            f"{current.baseline_heart_rate:.0f} bpm "
            f"({current.heart_rate - current.baseline_heart_rate:+.0f}).",
        )

        # --- Heart rate trend ---
        add(
            "heart_rate_trend",
            "Heart rate rising",
            "heart_rate_trend",
            _ramp(
                max(0.0, trends["hr_delta"]),
                tr.get("hr_rise_warn", 12.0),
                tr.get("hr_rise_critical", 25.0),
            ),
            trends["hr_delta"],
            f"Heart rate changed {trends['hr_delta']:+.0f} bpm over "
            f"{trends['window_minutes']:.0f} min.",
        )

        # --- Respiratory rate ---
        rr = t["respiratory_rate"]
        sev_rr = max(
            _ramp(current.respiratory_rate, rr["warn_above"], rr["critical_above"]),
            _ramp(current.respiratory_rate, rr["warn_below"], rr["critical_below"]),
        )
        add(
            "respiratory_rate",
            "Respiratory rate",
            "respiratory_rate",
            sev_rr,
            current.respiratory_rate,
            f"Respiratory rate {current.respiratory_rate:.0f} breaths/min "
            f"(normal upper bound {rr['normal_max']:.0f}).",
        )

        # --- Body temperature (hypo/hyper) ---
        bt = t["body_temp_c"]
        sev_bt = max(
            _ramp(current.body_temp_c, bt["warn_below"], bt["critical_below"]),
            _ramp(current.body_temp_c, bt["warn_above"], bt["critical_above"]),
        )
        add(
            "body_temp",
            "Core body temperature",
            "body_temp",
            sev_bt,
            current.body_temp_c,
            f"Body temperature {current.body_temp_c:.1f} °C against a normal band of "
            f"{bt['normal_min']:.1f}–{bt['normal_max']:.1f} °C.",
        )

        # --- Fatigue ---
        fs = t["fatigue_score"]
        add(
            "fatigue",
            "Accumulated fatigue",
            "fatigue",
            _ramp(current.fatigue_score, fs["warn_above"], fs["critical_above"]),
            current.fatigue_score,
            f"Fatigue index {current.fatigue_score:.0f}/100 "
            f"(warning above {fs['warn_above']:.0f}).",
        )
        add(
            "fatigue_trend",
            "Fatigue accumulating",
            "fatigue_trend",
            _ramp(
                max(0.0, trends["fatigue_delta"]),
                tr.get("fatigue_rise_warn", 10.0),
                tr.get("fatigue_rise_warn", 10.0) * 2.5,
            ),
            trends["fatigue_delta"],
            f"Fatigue changed {trends['fatigue_delta']:+.0f} points over "
            f"{trends['window_minutes']:.0f} min.",
        )

        # --- Altitude exposure ---
        al = t["altitude_m"]
        add(
            "altitude",
            "Altitude exposure",
            "altitude",
            _ramp(current.altitude_m, al["warn_above"], al["critical_above"]),
            current.altitude_m,
            f"Operating at {current.altitude_m:.0f} m "
            f"(elevated exposure above {al['warn_above']:.0f} m).",
        )
        add(
            "altitude_gain",
            "Rapid altitude gain",
            "altitude_gain",
            _ramp(
                max(0.0, trends["altitude_delta"]),
                tr.get("altitude_gain_warn", 250.0),
                tr.get("altitude_gain_critical", 500.0),
            ),
            trends["altitude_delta"],
            f"Ascended {max(0.0, trends['altitude_delta']):.0f} m in "
            f"{trends['window_minutes']:.0f} min, limiting acclimatisation time.",
        )

        # --- Environment (cold + wind combined) ---
        et, wk = t["env_temp_c"], t["wind_kph"]
        sev_env = max(
            _ramp(current.env_temp_c, et["warn_below"], et["critical_below"]),
            _ramp(current.wind_kph, wk["warn_above"], wk["critical_above"]),
        )
        add(
            "environment",
            "Environmental exposure",
            "environment",
            sev_env,
            current.env_temp_c,
            f"Ambient {current.env_temp_c:.0f} °C with {current.wind_kph:.0f} kph wind "
            f"— cold-stress and wind-chill exposure.",
        )

        # --- Blood pressure ---
        bp = t["bp_systolic"]
        sev_bp = max(
            _ramp(current.bp_systolic, bp["warn_above"], bp["critical_above"]),
            _ramp(current.bp_systolic, bp["warn_below"], bp["critical_below"]),
        )
        add(
            "blood_pressure",
            "Blood pressure",
            "blood_pressure",
            sev_bp,
            current.bp_systolic,
            f"Blood pressure {current.bp_systolic:.0f}/{current.bp_diastolic:.0f} mmHg.",
        )

        # --- Multi-system deterioration ---
        # Several independent indicators degrading at once is materially worse
        # than any single one, so it gets its own explicit factor.
        significant = [
            f
            for f in factors
            if f.severity >= 0.34 and f.feature not in ("altitude", "environment")
        ]
        multi_sev = 0.0
        if len(significant) >= 2:
            multi_sev = min(1.0, (len(significant) - 1) / 3.0)
        add(
            "multi_system",
            "Multiple indicators deteriorating",
            "multi_system",
            multi_sev,
            float(len(significant)),
            (
                f"{len(significant)} independent indicators are simultaneously "
                f"outside their reference bands: "
                + ", ".join(f.label for f in significant[:4])
                + "."
            )
            if significant
            else "No simultaneous multi-indicator deterioration detected.",
        )

        total_weight = sum(f.weight for f in factors) or 1.0
        raw = sum(f.contribution for f in factors)
        # Fraction of the maximum possible weighted severity, then rescaled
        # onto the realistically achievable band (see DEFAULT_RISK_SCALE).
        raw_ratio = raw / total_weight
        score = max(0.0, min(100.0, (raw_ratio / self.scale_ratio) * 100.0))
        return RiskAssessmentResult(
            risk_score=round(score, 2),
            category=self.categorise(score),
            factors=factors,
            config_version=self.config_version,
            trends=trends,
            raw_ratio=round(raw_ratio, 4),
            scale_ratio=self.scale_ratio,
        )


def recommended_action(category: RiskCategory, top_features: list[str]) -> str:
    """Operational recommendation. Advisory only — a human decides."""
    if category is RiskCategory.CRITICAL:
        base = (
            "Initiate immediate descent and prepare casualty evacuation. "
            "Escalate to the medical officer now and begin supplemental oxygen "
            "if available."
        )
    elif category is RiskCategory.HIGH:
        base = (
            "Halt ascent, rest the individual and re-assess within 15 minutes. "
            "Notify the medical officer and plan a descent option."
        )
    elif category is RiskCategory.MODERATE:
        base = (
            "Reduce exertion, increase monitoring frequency and hold current "
            "altitude until indicators stabilise."
        )
    else:
        base = "Continue routine monitoring. No intervention indicated."
    hints = {
        "spo2": "Prioritise oxygenation and check equipment seal.",
        "spo2_trend": "The downward SpO₂ trend is the leading indicator here.",
        "altitude": "Altitude exposure is a primary driver — descent reduces it fastest.",
        "altitude_gain": "Slow the ascent profile to allow acclimatisation.",
        "environment": "Address cold and wind exposure: shelter and insulation.",
        "fatigue": "Fatigue is a major contributor — enforce a rest period.",
        "body_temp": "Manage thermal state actively (warming or cooling as indicated).",
    }
    extra = [hints[f] for f in top_features[:2] if f in hints]
    return " ".join([base, *extra])
