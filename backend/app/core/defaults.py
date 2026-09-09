"""Default system configuration.

Everything the risk engine, alert engine and route planner treat as a
"threshold" lives here and is persisted into ``system_configurations`` at seed
time, so an operator can retune the platform without a code change.

IMPORTANT — these values are engineering defaults chosen to make a simulation
behave plausibly. They are NOT clinical thresholds, they are not derived from a
validated medical study, and they must not be used for medical decisions.
"""

from __future__ import annotations

from typing import Any

CONFIG_RISK_THRESHOLDS = "risk.thresholds"
CONFIG_RISK_WEIGHTS = "risk.weights"
CONFIG_RISK_CATEGORIES = "risk.categories"
CONFIG_RISK_SCALE = "risk.scale"
CONFIG_ALERT_RULES = "alert.rules"
CONFIG_ROUTE_COSTS = "route.costs"
CONFIG_SIMULATION = "simulation.defaults"
CONFIG_PREDICTION = "prediction.defaults"

#: Per-vital reference bands. ``warn``/``critical`` are directional bounds.
DEFAULT_RISK_THRESHOLDS: dict[str, Any] = {
    "spo2": {"normal_min": 92.0, "warn_below": 90.0, "critical_below": 85.0},
    "heart_rate": {
        "normal_max": 100.0,
        "warn_above": 115.0,
        "critical_above": 135.0,
        "warn_below": 45.0,
        "critical_below": 38.0,
    },
    "respiratory_rate": {
        "normal_max": 20.0,
        "warn_above": 24.0,
        "critical_above": 30.0,
        "warn_below": 9.0,
        "critical_below": 7.0,
    },
    "body_temp_c": {
        "normal_min": 36.0,
        "normal_max": 37.5,
        "warn_below": 35.5,
        "critical_below": 35.0,
        "warn_above": 38.0,
        "critical_above": 39.0,
    },
    "fatigue_score": {"warn_above": 60.0, "critical_above": 80.0},
    "altitude_m": {"warn_above": 5000.0, "critical_above": 6000.0},
    "env_temp_c": {"warn_below": -20.0, "critical_below": -30.0},
    "wind_kph": {"warn_above": 45.0, "critical_above": 70.0},
    "bp_systolic": {
        "warn_above": 150.0,
        "critical_above": 170.0,
        "warn_below": 95.0,
        "critical_below": 85.0,
    },
    # Trend thresholds evaluated over the analysis window.
    "trends": {
        "window_minutes": 20,
        "spo2_drop_warn": 2.5,
        "spo2_drop_critical": 5.0,
        "hr_rise_warn": 12.0,
        "hr_rise_critical": 25.0,
        "fatigue_rise_warn": 10.0,
        "altitude_gain_warn": 250.0,
        "altitude_gain_critical": 500.0,
    },
}

#: Relative contribution weights for the rule-based risk score. Each factor
#: produces a 0..1 severity which is multiplied by its weight; the weighted sum
#: is normalised to a 0..100 score. Weights are transparent and configurable,
#: and the exact same numbers are surfaced in the "Why this risk?" panel.
DEFAULT_RISK_WEIGHTS: dict[str, float] = {
    "spo2": 26.0,
    "spo2_trend": 12.0,
    "heart_rate": 14.0,
    "heart_rate_trend": 8.0,
    "respiratory_rate": 9.0,
    "body_temp": 8.0,
    "fatigue": 9.0,
    "fatigue_trend": 4.0,
    "altitude": 7.0,
    "altitude_gain": 5.0,
    "environment": 6.0,
    "blood_pressure": 5.0,
    "multi_system": 8.0,
}

#: Score calibration.
#
# The raw engine output is ``sum(weight * severity) / sum(weight)``, i.e. the
# fraction of the maximum possible weighted severity. That fraction can never
# realistically approach 1.0, because it requires *every* factor to be maxed
# simultaneously — including mutually unlikely ones (a person cannot be both
# resting with zero fatigue and in extreme exertional distress). Measured over
# 24 000 simulated deteriorating samples the observed ceiling was ~0.77.
#
# ``score_scale_ratio`` therefore maps the realistically achievable band
# ``[0, 0.80]`` onto the reported ``0-100`` score, clamped at 100. It is a
# single, monotonic, documented rescale: per-factor contributions stay exactly
# proportional and remain fully additive in the explanation panel.
DEFAULT_RISK_SCALE: dict[str, float] = {"score_scale_ratio": 0.80}

#: Score -> category cut-offs (inclusive lower bound), calibrated against the
#: measured score distribution of the simulated population so that all four
#: bands are actually reachable and each carries a distinct operational meaning.
DEFAULT_RISK_CATEGORIES: dict[str, float] = {
    "LOW": 0.0,
    "MODERATE": 40.0,
    "HIGH": 65.0,
    "CRITICAL": 85.0,
}

DEFAULT_ALERT_RULES: dict[str, Any] = {
    # Minimum seconds between two alerts sharing a dedup key.
    "cooldown_seconds": {
        "INFO": 900,
        "WARNING": 600,
        "HIGH": 300,
        "CRITICAL": 120,
    },
    # An open alert re-firing at a higher severity escalates in place.
    "escalation_enabled": True,
    # Risk categories that raise a risk-escalation alert.
    "risk_alert_categories": ["HIGH", "CRITICAL"],
    # Predicted probability above which a predictive alert is raised.
    "prediction_probability_threshold": 0.65,
    "auto_resolve_after_minutes": 120,
    "max_open_alerts_per_person": 8,
}

DEFAULT_ROUTE_COSTS: dict[str, Any] = {
    # Base movement cost per cell (distance term multiplier).
    "base_cost": 1.0,
    # Additional cost per metre of ascent / descent.
    "ascent_cost_per_m": 0.030,
    "descent_cost_per_m": 0.012,
    # Hazard weights: multiplied by the cell's 0..1 hazard value.
    "avalanche_weight": 26.0,
    "crevasse_weight": 30.0,
    "weather_weight": 14.0,
    "difficulty_weight": 9.0,
    # Cells above these hazard values are treated as impassable when the
    # corresponding layer is enabled.
    "avalanche_block_above": 0.85,
    "crevasse_block_above": 0.85,
    # Baseline walking speed and how much terrain difficulty slows it.
    "base_speed_kph": 3.2,
    "difficulty_speed_penalty": 0.55,
    "ascent_minutes_per_100m": 9.0,
}

DEFAULT_SIMULATION: dict[str, Any] = {
    "tick_seconds": 2.0,
    "sim_seconds_per_tick": 60,
    "default_seed": 20260909,
    "default_scenario": "NORMAL",
    "speeds": [1, 2, 5, 10],
    "prediction_every_n_ticks": 3,
    "drone_count": 8,
    "max_readings_per_person": 5000,
}

DEFAULT_PREDICTION: dict[str, Any] = {
    "active_model": "lstm",
    "horizon_minutes": 30,
    "sequence_length": 24,
    "min_readings_for_model": 24,
}

ALL_DEFAULTS: dict[str, tuple[Any, str]] = {
    CONFIG_RISK_THRESHOLDS: (
        DEFAULT_RISK_THRESHOLDS,
        "Per-vital reference bands used by the rule-based risk engine "
        "(engineering defaults, not clinical thresholds)",
    ),
    CONFIG_RISK_WEIGHTS: (
        DEFAULT_RISK_WEIGHTS,
        "Transparent contribution weights for the rule-based risk score",
    ),
    CONFIG_RISK_CATEGORIES: (
        DEFAULT_RISK_CATEGORIES,
        "Risk score cut-offs mapping a 0-100 score to a risk category",
    ),
    CONFIG_RISK_SCALE: (
        DEFAULT_RISK_SCALE,
        "Calibration mapping the achievable weighted-severity band onto 0-100",
    ),
    CONFIG_ALERT_RULES: (
        DEFAULT_ALERT_RULES,
        "Alert engine cooldown, deduplication and escalation rules",
    ),
    CONFIG_ROUTE_COSTS: (
        DEFAULT_ROUTE_COSTS,
        "A* cost model: hazard weights, blocking thresholds and speed model",
    ),
    CONFIG_SIMULATION: (DEFAULT_SIMULATION, "Simulation engine defaults"),
    CONFIG_PREDICTION: (DEFAULT_PREDICTION, "Prediction service defaults"),
}

#: Shown wherever data provenance matters. Referenced by API responses and UI.
DATA_DISCLAIMER = (
    "SIMULATED DATA — NOT REAL SENSOR DATA. Generated by the A4S+ simulation "
    "engine for research and demonstration only. Not clinically validated and "
    "not a medical device."
)
