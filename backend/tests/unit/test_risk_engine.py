"""Rule-based risk engine: monotonicity, additivity and transparency.

The engine reports a 0..100 score. It is deliberately *additive*: the reported
score is the weighted severity fraction (``raw_ratio``) divided by a single
published calibration constant. These tests pin that property down, because the
"WHY THIS RISK?" explanation in the UI claims the factors fully explain the
score, and that claim has to stay true.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.defaults import (
    DEFAULT_RISK_CATEGORIES,
    DEFAULT_RISK_SCALE,
    DEFAULT_RISK_THRESHOLDS,
    DEFAULT_RISK_WEIGHTS,
)
from app.models.enums import ActivityLevel, RiskCategory
from app.services.risk_engine import RiskEngine, VitalSnapshot, recommended_action

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


def snapshot(minute: int = 0, **overrides: float | str) -> VitalSnapshot:
    base: dict[str, object] = {
        "recorded_at": T0 + timedelta(minutes=minute),
        "heart_rate": 72.0,
        "spo2": 97.0,
        "body_temp_c": 36.8,
        "respiratory_rate": 14.0,
        "bp_systolic": 118.0,
        "bp_diastolic": 76.0,
        "altitude_m": 3800.0,
        "fatigue_score": 10.0,
        "activity_level": ActivityLevel.RESTING.value,
        "env_temp_c": -8.0,
        "wind_kph": 12.0,
        "baseline_heart_rate": 70.0,
        "baseline_spo2": 97.0,
    }
    base.update(overrides)
    return VitalSnapshot(**base)  # type: ignore[arg-type]


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine(
        DEFAULT_RISK_THRESHOLDS,
        DEFAULT_RISK_WEIGHTS,
        DEFAULT_RISK_CATEGORIES,
        DEFAULT_RISK_SCALE,
    )


def test_healthy_snapshot_is_low_risk(engine: RiskEngine) -> None:
    result = engine.evaluate(snapshot())
    assert result.category == RiskCategory.LOW
    assert result.risk_score < 10.0


def test_hypoxia_is_reported_as_the_dominant_factor(engine: RiskEngine) -> None:
    result = engine.evaluate(snapshot(spo2=76.0))
    assert result.top_factors[0].feature == "spo2"
    # A single deranged vital raises the score but, by design, does not on its
    # own push a resting soldier into CRITICAL - multi-system involvement does.
    assert result.risk_score > engine.evaluate(snapshot()).risk_score


def test_multi_system_derangement_reaches_critical(engine: RiskEngine) -> None:
    result = engine.evaluate(
        snapshot(
            spo2=74.0,
            heart_rate=168.0,
            respiratory_rate=34.0,
            body_temp_c=34.4,
            fatigue_score=92.0,
            altitude_m=6200.0,
            bp_systolic=178.0,
            env_temp_c=-38.0,
            wind_kph=70.0,
        )
    )
    assert result.category == RiskCategory.CRITICAL
    assert {f.feature for f in result.top_factors} >= {"spo2", "heart_rate"}


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("spo2", (98.0, 92.0, 88.0, 84.0, 78.0, 70.0)),
        ("heart_rate", (70.0, 100.0, 120.0, 150.0, 185.0)),
        ("respiratory_rate", (14.0, 20.0, 26.0, 34.0, 42.0)),
        ("fatigue_score", (0.0, 25.0, 50.0, 75.0, 100.0)),
        ("altitude_m", (3000.0, 4000.0, 5000.0, 6000.0, 7500.0)),
    ],
)
def test_score_is_monotonic_in_each_vital(
    engine: RiskEngine, field: str, values: tuple[float, ...]
) -> None:
    scores = [engine.evaluate(snapshot(**{field: v})).risk_score for v in values]
    assert scores == sorted(scores), f"{field}: {scores}"
    assert scores[-1] > scores[0]


def test_reported_score_is_exactly_the_weighted_factor_sum(engine: RiskEngine) -> None:
    result = engine.evaluate(snapshot(spo2=85.0, heart_rate=140.0, fatigue_score=70.0))
    total_weight = sum(f.weight for f in result.factors)
    contributed = sum(f.contribution for f in result.factors)
    assert result.raw_ratio == pytest.approx(contributed / total_weight, abs=5e-5)
    assert result.risk_score == pytest.approx(
        min(100.0, result.raw_ratio / result.scale_ratio * 100.0), abs=0.02
    )


def test_score_stays_within_bounds_at_the_extremes(engine: RiskEngine) -> None:
    worst = engine.evaluate(
        snapshot(
            spo2=55.0,
            heart_rate=210.0,
            respiratory_rate=48.0,
            body_temp_c=32.0,
            bp_systolic=205.0,
            bp_diastolic=125.0,
            fatigue_score=100.0,
            altitude_m=8200.0,
            env_temp_c=-45.0,
            wind_kph=95.0,
        )
    )
    assert 0.0 <= worst.risk_score <= 100.0
    assert worst.category == RiskCategory.CRITICAL
    best = engine.evaluate(snapshot(spo2=99.0, heart_rate=58.0, fatigue_score=0.0))
    assert best.risk_score >= 0.0


def test_category_boundaries_follow_configured_cut_offs(engine: RiskEngine) -> None:
    assert engine.categorise(0.0) == RiskCategory.LOW
    assert engine.categorise(39.99) == RiskCategory.LOW
    assert engine.categorise(40.0) == RiskCategory.MODERATE
    assert engine.categorise(64.99) == RiskCategory.MODERATE
    assert engine.categorise(65.0) == RiskCategory.HIGH
    assert engine.categorise(84.99) == RiskCategory.HIGH
    assert engine.categorise(85.0) == RiskCategory.CRITICAL
    assert engine.categorise(100.0) == RiskCategory.CRITICAL


def test_custom_cut_offs_are_honoured() -> None:
    engine = RiskEngine(categories={"LOW": 0.0, "MODERATE": 10.0, "HIGH": 20.0, "CRITICAL": 30.0})
    assert engine.categorise(25.0) == RiskCategory.HIGH


def test_recommended_action_is_specific_to_the_dominant_factor(engine: RiskEngine) -> None:
    result = engine.evaluate(snapshot(spo2=74.0, heart_rate=160.0, respiratory_rate=33.0))
    action = recommended_action(result.category, [f.feature for f in result.top_factors])
    assert action and len(action) > 20
    low_action = recommended_action(RiskCategory.LOW, ["spo2"])
    assert low_action != action


def test_falling_saturation_trend_raises_the_score(engine: RiskEngine) -> None:
    history = [snapshot(0, spo2=95.0), snapshot(5, spo2=92.0), snapshot(10, spo2=89.0)]
    falling = engine.evaluate(snapshot(15, spo2=86.0), history)
    steady = engine.evaluate(
        snapshot(15, spo2=86.0), [snapshot(i * 5, spo2=86.0) for i in range(3)]
    )
    assert falling.risk_score >= steady.risk_score
    assert falling.trends["spo2_delta"] < 0


def test_trends_are_empty_without_history(engine: RiskEngine) -> None:
    result = engine.evaluate(snapshot())
    assert result.trends["samples"] == 0


def test_invalid_calibration_constant_is_rejected() -> None:
    with pytest.raises(ValueError):
        RiskEngine(scale={"score_scale_ratio": 0.0})
    with pytest.raises(ValueError):
        RiskEngine(scale={"score_scale_ratio": 2.0})


def test_engine_is_deterministic(engine: RiskEngine) -> None:
    args = {"spo2": 88.0, "heart_rate": 132.0, "fatigue_score": 55.0}
    first = engine.evaluate(snapshot(**args))
    second = engine.evaluate(snapshot(**args))
    assert first.risk_score == second.risk_score
    assert [f.as_dict() for f in first.factors] == [f.as_dict() for f in second.factors]
