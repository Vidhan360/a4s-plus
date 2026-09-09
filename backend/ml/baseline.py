"""Comparison models: transparent rule baseline and gradient boosting.

Both consume the identical windowed features as the LSTM so the comparison in
the UI is apples-to-apples.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ml.features import FEATURE_NAMES


def flatten_windows(x: np.ndarray) -> np.ndarray:
    """Reduce ``(N, T, F)`` windows to tabular summary features.

    Tree ensembles cannot consume raw sequences, so each channel is summarised
    by its last value, mean, min, max and net change across the window. This
    preserves both level and trend information.
    """
    if x.size == 0:
        return np.zeros((0, len(FEATURE_NAMES) * 5), dtype=np.float32)
    last = x[:, -1, :]
    mean = x.mean(axis=1)
    minimum = x.min(axis=1)
    maximum = x.max(axis=1)
    change = x[:, -1, :] - x[:, 0, :]
    return np.concatenate([last, mean, minimum, maximum, change], axis=1).astype(np.float32)


def flattened_feature_names() -> list[str]:
    return [
        f"{name}__{stat}"
        for stat in ("last", "mean", "min", "max", "change")
        for name in FEATURE_NAMES
    ]


def train_gradient_boosting(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    seed: int = 20260909,
) -> tuple[Any, dict[str, Any]]:
    """Fit a HistGradientBoostingClassifier on the flattened windows."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(
        max_iter=220,
        learning_rate=0.08,
        max_depth=7,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.15,
        random_state=seed,
    )
    model.fit(flatten_windows(x_train), y_train)
    info = {
        "estimator": "sklearn.ensemble.HistGradientBoostingClassifier",
        "n_iter": int(getattr(model, "n_iter_", 0)),
        "max_iter": 220,
        "learning_rate": 0.08,
        "max_depth": 7,
        "feature_names": flattened_feature_names(),
        "n_features": int(flatten_windows(x_train).shape[1]),
    }
    return model, info


def permutation_importance_gb(
    model: Any,
    x: np.ndarray,
    y: np.ndarray,
    seed: int = 0,
    max_samples: int = 3000,
) -> dict[str, float]:
    """Permutation importance aggregated back to the base feature channels.

    Genuinely computed by shuffling each channel's five summary columns
    together and measuring the accuracy drop. Not an impurity heuristic and not
    presented as SHAP.
    """
    rng = np.random.default_rng(seed)
    if x.shape[0] > max_samples:
        idx = rng.choice(x.shape[0], max_samples, replace=False)
        x, y = x[idx], y[idx]
    flat = flatten_windows(x)
    baseline = float((model.predict(flat) == y).mean())
    n_feat = len(FEATURE_NAMES)
    out: dict[str, float] = {}
    for f, name in enumerate(FEATURE_NAMES):
        perturbed = flat.copy()
        cols = [stat * n_feat + f for stat in range(5)]
        order = rng.permutation(perturbed.shape[0])
        perturbed[:, cols] = perturbed[order][:, cols]
        out[name] = round(baseline - float((model.predict(perturbed) == y).mean()), 5)
    return out
