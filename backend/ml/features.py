"""Feature engineering and sequence windowing.

The exact same code path is used for training and for live inference, which is
what prevents train/serve skew: :func:`build_feature_matrix` is called by the
dataset builder and by ``PredictionService`` on live readings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Raw per-timestep channels, in a fixed order that the trained model depends
#: on. The order is persisted with the model artifact and validated on load.
BASE_FEATURES: tuple[str, ...] = (
    "heart_rate",
    "spo2",
    "body_temp_c",
    "respiratory_rate",
    "bp_systolic",
    "bp_diastolic",
    "altitude_m",
    "fatigue_score",
    "env_temp_c",
    "wind_kph",
    "exertion",
)

#: First-difference channels appended after the raw block. Giving the network
#: explicit deltas materially helps it pick up deterioration *trends* rather
#: than only absolute levels.
DELTA_FEATURES: tuple[str, ...] = (
    "d_heart_rate",
    "d_spo2",
    "d_respiratory_rate",
    "d_altitude_m",
    "d_fatigue_score",
)

FEATURE_NAMES: tuple[str, ...] = BASE_FEATURES + DELTA_FEATURES
N_FEATURES: int = len(FEATURE_NAMES)

#: Human-readable labels used by the explainability panel.
FEATURE_LABELS: dict[str, str] = {
    "heart_rate": "Heart rate",
    "spo2": "Blood oxygen saturation",
    "body_temp_c": "Core body temperature",
    "respiratory_rate": "Respiratory rate",
    "bp_systolic": "Systolic blood pressure",
    "bp_diastolic": "Diastolic blood pressure",
    "altitude_m": "Altitude exposure",
    "fatigue_score": "Accumulated fatigue",
    "env_temp_c": "Ambient temperature",
    "wind_kph": "Wind speed",
    "exertion": "Activity / exertion level",
    "d_heart_rate": "Heart rate trend",
    "d_spo2": "SpO₂ trend",
    "d_respiratory_rate": "Respiratory rate trend",
    "d_altitude_m": "Altitude change rate",
    "d_fatigue_score": "Fatigue accumulation rate",
}

ACTIVITY_TO_EXERTION: dict[str, float] = {
    "RESTING": 0.05,
    "LIGHT": 0.25,
    "MODERATE": 0.5,
    "HEAVY": 0.75,
    "EXTREME": 0.95,
}

RISK_CLASSES: tuple[str, ...] = ("LOW", "MODERATE", "HIGH", "CRITICAL")
#: Classes considered "elevated risk"; their summed probability is the headline
#: ``risk_probability`` reported by the API.
ELEVATED_CLASSES: tuple[int, ...] = (2, 3)


@dataclass
class StandardScaler:
    """Per-channel z-score scaler, persisted alongside the model."""

    mean: np.ndarray = field(default_factory=lambda: np.zeros(N_FEATURES))
    std: np.ndarray = field(default_factory=lambda: np.ones(N_FEATURES))

    def fit(self, x: np.ndarray) -> StandardScaler:
        flat = x.reshape(-1, x.shape[-1])
        self.mean = flat.mean(axis=0)
        std = flat.std(axis=0)
        # Guard against zero-variance channels.
        self.std = np.where(std < 1e-6, 1.0, std)
        return self

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def fit_transform(self, x: np.ndarray) -> np.ndarray:
        return self.fit(x).transform(x)

    def to_dict(self) -> dict[str, list[float]]:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StandardScaler:
        return cls(
            mean=np.asarray(payload["mean"], dtype=np.float64),
            std=np.asarray(payload["std"], dtype=np.float64),
        )


def row_from_reading(reading: Any) -> dict[str, float]:
    """Normalise an ORM row, a ``VitalSample`` or a dict into a flat mapping."""
    if isinstance(reading, dict):
        get = reading.get
        env = reading.get("environment") or {}
        env_get = env.get if isinstance(env, dict) else (lambda k, d=None: d)

        def pick(name: str, default: float = 0.0) -> float:
            v = get(name, None)
            if v is None:
                v = env_get(name, None)
            return float(default if v is None else v)

        activity = str(get("activity_level", "LIGHT"))
        return {
            "heart_rate": pick("heart_rate", 70.0),
            "spo2": pick("spo2", 96.0),
            "body_temp_c": pick("body_temp_c", 36.8),
            "respiratory_rate": pick("respiratory_rate", 14.0),
            "bp_systolic": pick("bp_systolic", 120.0),
            "bp_diastolic": pick("bp_diastolic", 78.0),
            "altitude_m": pick("altitude_m", 4200.0),
            "fatigue_score": pick("fatigue_score", 10.0),
            "env_temp_c": pick("env_temp_c", -10.0),
            "wind_kph": pick("wind_kph", 10.0),
            "exertion": ACTIVITY_TO_EXERTION.get(activity, 0.25),
        }

    env = getattr(reading, "environment", None)

    def attr(name: str, default: float) -> float:
        v = getattr(reading, name, None)
        if v is None and env is not None:
            v = getattr(env, name, None)
        return float(default if v is None else v)

    activity = getattr(reading, "activity_level", "LIGHT")
    activity = getattr(activity, "value", activity)
    return {
        "heart_rate": attr("heart_rate", 70.0),
        "spo2": attr("spo2", 96.0),
        "body_temp_c": attr("body_temp_c", 36.8),
        "respiratory_rate": attr("respiratory_rate", 14.0),
        "bp_systolic": attr("bp_systolic", 120.0),
        "bp_diastolic": attr("bp_diastolic", 78.0),
        "altitude_m": attr("altitude_m", 4200.0),
        "fatigue_score": attr("fatigue_score", 10.0),
        "env_temp_c": attr("env_temp_c", -10.0),
        "wind_kph": attr("wind_kph", 10.0),
        "exertion": ACTIVITY_TO_EXERTION.get(str(activity), 0.25),
    }


def build_feature_matrix(readings: Sequence[Any]) -> np.ndarray:
    """Convert an ordered (oldest-first) reading sequence into ``(T, F)``.

    Delta channels are first differences, with the first row's deltas set to
    zero so the matrix length always equals ``len(readings)``.
    """
    if not readings:
        return np.zeros((0, N_FEATURES), dtype=np.float32)
    rows = [row_from_reading(r) for r in readings]
    base = np.array([[row[name] for name in BASE_FEATURES] for row in rows], dtype=np.float32)
    delta_sources = ("heart_rate", "spo2", "respiratory_rate", "altitude_m", "fatigue_score")
    idx = [BASE_FEATURES.index(n) for n in delta_sources]
    deltas = np.zeros((base.shape[0], len(idx)), dtype=np.float32)
    if base.shape[0] > 1:
        deltas[1:] = base[1:, idx] - base[:-1, idx]
    return np.concatenate([base, deltas], axis=1)


def make_windows(
    matrix: np.ndarray,
    labels: np.ndarray | None,
    sequence_length: int,
    horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Slice a series into supervised ``(window, future_label)`` pairs.

    A window ending at index ``t`` is paired with the label at ``t + horizon``,
    so the model is trained to *anticipate* rather than to describe the present.
    """
    t = matrix.shape[0]
    if t < sequence_length + horizon:
        return (
            np.zeros((0, sequence_length, matrix.shape[1]), dtype=np.float32),
            np.zeros((0,), dtype=np.int64),
        )
    xs, ys = [], []
    for end in range(sequence_length - 1, t - horizon):
        xs.append(matrix[end - sequence_length + 1 : end + 1])
        if labels is not None:
            ys.append(labels[end + horizon])
    x = np.stack(xs).astype(np.float32)
    y = (
        np.asarray(ys, dtype=np.int64)
        if labels is not None
        else np.zeros((len(xs),), dtype=np.int64)
    )
    return x, y


def latest_window(matrix: np.ndarray, sequence_length: int) -> np.ndarray | None:
    """Take the most recent ``sequence_length`` timesteps for inference.

    Returns ``None`` when there is not enough history, so callers must decide
    explicitly rather than silently padding and producing a misleading result.
    """
    if matrix.shape[0] < sequence_length:
        return None
    return matrix[-sequence_length:].astype(np.float32)
