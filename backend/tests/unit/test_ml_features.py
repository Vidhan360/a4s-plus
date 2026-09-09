"""Feature engineering: shape, ordering, delta channels and windowing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ml.features import (
    BASE_FEATURES,
    DELTA_FEATURES,
    FEATURE_LABELS,
    FEATURE_NAMES,
    N_FEATURES,
    RISK_CLASSES,
    StandardScaler,
    build_feature_matrix,
    latest_window,
    make_windows,
    row_from_reading,
)

T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)


def reading(i: int, **overrides: float) -> dict[str, float | datetime]:
    row: dict[str, float | datetime] = {
        "recorded_at": T0 + timedelta(minutes=i),
        "heart_rate": 80.0 + i,
        "spo2": 95.0 - i * 0.5,
        "body_temp_c": 36.8,
        "respiratory_rate": 15.0,
        "bp_systolic": 120.0,
        "bp_diastolic": 78.0,
        "altitude_m": 4200.0 + i * 10,
        "fatigue_score": 20.0 + i,
        "env_temp_c": -10.0,
        "wind_kph": 20.0,
        "activity_level": "MODERATE",
    }
    row.update(overrides)
    return row


def test_feature_vector_is_16_channels_in_a_stable_order() -> None:
    assert N_FEATURES == 16
    assert FEATURE_NAMES == BASE_FEATURES + DELTA_FEATURES
    assert len(set(FEATURE_NAMES)) == N_FEATURES
    assert FEATURE_NAMES[0] == "heart_rate"


def test_every_feature_has_a_human_readable_label() -> None:
    for name in FEATURE_NAMES:
        assert FEATURE_LABELS.get(name), name


def test_risk_classes_are_the_four_documented_bands() -> None:
    assert RISK_CLASSES == ("LOW", "MODERATE", "HIGH", "CRITICAL")


def test_matrix_shape_matches_reading_count() -> None:
    matrix = build_feature_matrix([reading(i) for i in range(10)])
    assert matrix.shape == (10, N_FEATURES)
    assert matrix.dtype == np.float32


def test_empty_input_yields_an_empty_matrix_not_an_error() -> None:
    assert build_feature_matrix([]).shape == (0, N_FEATURES)


def test_delta_channels_are_true_first_differences() -> None:
    readings = [reading(i) for i in range(5)]
    matrix = build_feature_matrix(readings)
    hr_idx = BASE_FEATURES.index("heart_rate")
    d_hr_idx = len(BASE_FEATURES) + DELTA_FEATURES.index("d_heart_rate")
    assert matrix[0, d_hr_idx] == 0.0  # no history for the first row
    for t in range(1, 5):
        assert matrix[t, d_hr_idx] == pytest.approx(
            matrix[t, hr_idx] - matrix[t - 1, hr_idx], abs=1e-4
        )


def test_falling_saturation_produces_negative_deltas() -> None:
    matrix = build_feature_matrix([reading(i) for i in range(6)])
    d_spo2 = len(BASE_FEATURES) + DELTA_FEATURES.index("d_spo2")
    assert (matrix[1:, d_spo2] < 0).all()


def test_row_from_reading_accepts_dicts_and_objects() -> None:
    row = row_from_reading(reading(0))
    assert set(BASE_FEATURES) <= set(row)

    class Fake:
        heart_rate = 90.0
        spo2 = 93.0
        body_temp_c = 37.0
        respiratory_rate = 16.0
        bp_systolic = 130.0
        bp_diastolic = 80.0
        altitude_m = 5000.0
        fatigue_score = 30.0
        env_temp_c = -15.0
        wind_kph = 25.0
        activity_level = "HEAVY"

    obj_row = row_from_reading(Fake())
    assert obj_row["heart_rate"] == 90.0
    assert obj_row["exertion"] > 0


def test_missing_fields_fall_back_without_raising() -> None:
    row = row_from_reading({"heart_rate": 70.0})
    assert row["heart_rate"] == 70.0
    assert all(np.isfinite(v) for v in row.values())


# ------------------------------------------------------------------ windows
def test_windows_pair_a_history_with_a_future_label() -> None:
    matrix = build_feature_matrix([reading(i) for i in range(40)])
    labels = np.arange(40, dtype=np.int64) % 4
    x, y = make_windows(matrix, labels, sequence_length=8, horizon=4)
    assert x.shape == (40 - 8 + 1 - 4, 8, N_FEATURES)
    assert y.shape[0] == x.shape[0]
    # The first window covers rows 0..7 and is labelled with row 7+4 = 11.
    assert np.array_equal(x[0], matrix[0:8])
    assert y[0] == labels[11]


def test_too_short_a_series_yields_no_windows_rather_than_padding() -> None:
    matrix = build_feature_matrix([reading(i) for i in range(5)])
    x, y = make_windows(matrix, np.zeros(5, dtype=np.int64), sequence_length=8, horizon=4)
    assert x.shape[0] == 0 and y.shape[0] == 0


def test_latest_window_returns_none_when_history_is_insufficient() -> None:
    matrix = build_feature_matrix([reading(i) for i in range(5)])
    assert latest_window(matrix, 24) is None


def test_latest_window_takes_the_most_recent_rows() -> None:
    matrix = build_feature_matrix([reading(i) for i in range(30)])
    window = latest_window(matrix, 24)
    assert window is not None
    assert window.shape == (24, N_FEATURES)
    assert np.array_equal(window, matrix[-24:])


# ------------------------------------------------------------------ scaling
def test_scaler_standardises_each_channel() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(50, 12, size=(200, 24, N_FEATURES)).astype(np.float32)
    scaler = StandardScaler().fit(x)
    scaled = scaler.transform(x)
    flat = scaled.reshape(-1, N_FEATURES)
    assert np.allclose(flat.mean(axis=0), 0.0, atol=1e-4)
    assert np.allclose(flat.std(axis=0), 1.0, atol=1e-3)


def test_scaler_survives_zero_variance_channels() -> None:
    x = np.ones((10, 4, N_FEATURES), dtype=np.float32)
    scaled = StandardScaler().fit_transform(x)
    assert np.isfinite(scaled).all()


def test_scaler_round_trips_through_json_safe_dict() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=(50, 6, N_FEATURES)).astype(np.float32)
    original = StandardScaler().fit(x)
    restored = StandardScaler.from_dict(original.to_dict())
    assert np.allclose(original.transform(x), restored.transform(x))
