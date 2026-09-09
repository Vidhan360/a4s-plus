"""Prediction service and the pluggable model interface.

    PredictionService
        └── ModelInterface (ABC)
              ├── RuleBaselineModel      transparent weighted contributions
              ├── LSTMModel              PyTorch, occlusion-sensitivity attribution
              └── GradientBoostingModel  sklearn, permutation importance

Honesty rules enforced in code
------------------------------
* Every prediction carries ``model_name``, ``model_version``,
  ``explanation_method`` and ``data_provenance``.
* ``explanation_method`` names the technique that *actually* produced the
  numbers. SHAP is never claimed, because SHAP is not used.
* Trained models are only used when a real artifact exists in the registry. If
  the requested model is unavailable the service says so explicitly and falls
  back to the rule baseline with ``fallback_reason`` set — it never presents
  the baseline as the trained model.
* ``metrics`` come from the artifact's recorded evaluation run, never from
  literals in this file.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import numpy as np

from app.core.defaults import DEFAULT_PREDICTION
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.enums import ExplanationMethod, RiskCategory
from app.services.risk_engine import RiskEngine, VitalSnapshot, recommended_action
from ml.features import (
    ELEVATED_CLASSES,
    FEATURE_LABELS,
    FEATURE_NAMES,
    RISK_CLASSES,
    StandardScaler,
    build_feature_matrix,
    latest_window,
)

logger = get_logger(__name__)

PROVENANCE = "SYNTHETIC_SIMULATION"


@dataclass
class FeatureContribution:
    feature: str
    label: str
    value: float
    contribution: float
    direction: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "label": self.label,
            "value": round(self.value, 3),
            "contribution": round(self.contribution, 5),
            "direction": self.direction,
        }


@dataclass
class Prediction:
    model_name: str
    model_version: str
    risk_probability: float
    predicted_category: RiskCategory
    class_probabilities: dict[str, float]
    contributions: list[FeatureContribution]
    explanation_method: ExplanationMethod
    horizon_minutes: int
    sequence_length: int
    inference_ms: float
    data_provenance: str = PROVENANCE
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    narrative: str = ""
    recommended_action: str = ""
    fallback_reason: str | None = None
    metrics: dict[str, Any] | None = None
    attention: list[float] | None = None

    def contributions_payload(self) -> dict[str, Any]:
        ranked = sorted(self.contributions, key=lambda c: -abs(c.contribution))
        return {
            "method": self.explanation_method.value,
            "method_description": EXPLANATION_DESCRIPTIONS[self.explanation_method],
            "contributions": [c.as_dict() for c in ranked],
            "top_contributions": [c.as_dict() for c in ranked[:6]],
            "narrative": self.narrative,
            "class_probabilities": {k: round(v, 5) for k, v in self.class_probabilities.items()},
            "attention": self.attention,
            "fallback_reason": self.fallback_reason,
        }


EXPLANATION_DESCRIPTIONS: dict[ExplanationMethod, str] = {
    ExplanationMethod.TRANSPARENT_WEIGHTS: (
        "Exact weighted contributions from the rule engine. Each value is the "
        "configured weight multiplied by the measured factor severity, so the "
        "listed contributions sum precisely to the reported score. No "
        "approximation is involved."
    ),
    ExplanationMethod.OCCLUSION_SENSITIVITY: (
        "Occlusion sensitivity: each input channel is independently replaced "
        "across the whole window by its training-set mean and the model is "
        "re-run. The contribution is the resulting change in the elevated-risk "
        "log-odds, measured in logit units — the logit is used rather than the "
        "raw probability because probability saturates near 0 and 1, which "
        "would flatten every attribution to zero exactly when risk is highest. "
        "Model-faithful and computed at inference time. This is not SHAP."
    ),
    ExplanationMethod.IMPURITY_IMPORTANCE: (
        "Permutation importance measured on the held-out split by shuffling "
        "each channel and recording the accuracy drop. Global to the model, "
        "not specific to this individual prediction."
    ),
}


class ModelInterface(ABC):
    """Contract every prediction model implements."""

    name: str = "abstract"
    explanation_method: ExplanationMethod = ExplanationMethod.TRANSPARENT_WEIGHTS

    @property
    @abstractmethod
    def version(self) -> str: ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether this model can serve predictions right now."""

    @property
    def sequence_length(self) -> int:
        return int(DEFAULT_PREDICTION["sequence_length"])

    @property
    def horizon_minutes(self) -> int:
        return int(DEFAULT_PREDICTION["horizon_minutes"])

    @property
    def metrics(self) -> dict[str, Any] | None:
        return None

    @abstractmethod
    def predict(
        self,
        readings: Sequence[Any],
        snapshots: Sequence[VitalSnapshot],
    ) -> Prediction: ...

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "available": self.is_available,
            "explanation_method": self.explanation_method.value,
            "sequence_length": self.sequence_length,
            "horizon_minutes": self.horizon_minutes,
            "data_provenance": PROVENANCE,
            "metrics": self.metrics,
        }


def _category_from_probability(probability: float) -> RiskCategory:
    if probability >= 0.85:
        return RiskCategory.CRITICAL
    if probability >= 0.6:
        return RiskCategory.HIGH
    if probability >= 0.32:
        return RiskCategory.MODERATE
    return RiskCategory.LOW


class RuleBaselineModel(ModelInterface):
    """Transparent, always-available baseline built on the rule risk engine.

    Forecasts by extrapolating the measured trend of the leading indicators
    over the analysis window and re-scoring the extrapolated state. Fully
    deterministic and fully explainable; no training involved.
    """

    name = "rule_baseline"
    explanation_method = ExplanationMethod.TRANSPARENT_WEIGHTS

    def __init__(self, engine: RiskEngine | None = None) -> None:
        self.engine = engine or RiskEngine()

    @property
    def version(self) -> str:
        return f"rules-v{self.engine.config_version}"

    @property
    def is_available(self) -> bool:
        return True

    @property
    def metrics(self) -> dict[str, Any] | None:
        import json

        from ml.registry import artifact_root

        path = artifact_root() / "last_comparison.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (ValueError, OSError):
            return None
        return payload.get("results", {}).get("rule_baseline")

    def predict(self, readings: Sequence[Any], snapshots: Sequence[VitalSnapshot]) -> Prediction:
        started = time.perf_counter()
        if not snapshots:
            raise ValueError("At least one reading is required to predict.")
        current = snapshots[-1]
        horizon = self.horizon_minutes

        present = self.engine.evaluate(current, snapshots)
        trends = present.trends
        span = max(1.0, trends.get("window_minutes", 1.0))
        scale = horizon / span

        # Extrapolate the measured trends forward, damped to avoid absurd
        # linear runaway over the horizon.
        damping = 0.6
        projected = VitalSnapshot(
            recorded_at=current.recorded_at + timedelta(minutes=horizon),
            heart_rate=float(
                np.clip(current.heart_rate + trends["hr_delta"] * scale * damping, 30, 220)
            ),
            spo2=float(np.clip(current.spo2 + trends["spo2_delta"] * scale * damping, 45, 100)),
            body_temp_c=current.body_temp_c,
            respiratory_rate=float(
                np.clip(current.respiratory_rate + trends["rr_delta"] * scale * damping, 5, 50)
            ),
            bp_systolic=current.bp_systolic,
            bp_diastolic=current.bp_diastolic,
            altitude_m=float(
                np.clip(
                    current.altitude_m + trends["altitude_delta"] * scale * damping,
                    2500,
                    8000,
                )
            ),
            fatigue_score=float(
                np.clip(current.fatigue_score + trends["fatigue_delta"] * scale * damping, 0, 100)
            ),
            activity_level=current.activity_level,
            env_temp_c=current.env_temp_c,
            wind_kph=current.wind_kph,
            baseline_heart_rate=current.baseline_heart_rate,
            baseline_spo2=current.baseline_spo2,
        )
        future = self.engine.evaluate(projected, [*snapshots, projected])
        probability = float(np.clip(future.risk_score / 100.0, 0.0, 1.0))

        contributions = [
            FeatureContribution(
                feature=f.feature,
                label=f.label,
                value=float(f.value or 0.0),
                # Normalised to a 0..1 share of the projected score.
                contribution=f.contribution / 100.0,
                direction=f.direction,
            )
            for f in future.factors
            if f.contribution > 0.0
        ]
        top = [f.feature for f in future.top_factors]
        narrative = (
            f"Projecting the measured {span:.0f}-minute trend forward by "
            f"{horizon} minutes (damped by {damping:.0%} to avoid linear "
            f"runaway) moves the rule score from {present.risk_score:.1f} "
            f"({present.category.value}) to {future.risk_score:.1f} "
            f"({future.category.value}). The dominant projected drivers are "
            + (", ".join(f.label for f in future.top_factors[:3]) or "none")
            + "."
        )
        trajectory = self._trajectory(current, projected, horizon)

        return Prediction(
            model_name=self.name,
            model_version=self.version,
            risk_probability=probability,
            predicted_category=future.category,
            class_probabilities=self._pseudo_class_probs(future.category, probability),
            contributions=contributions,
            explanation_method=self.explanation_method,
            horizon_minutes=horizon,
            sequence_length=len(snapshots),
            inference_ms=round((time.perf_counter() - started) * 1000, 3),
            trajectory=trajectory,
            narrative=narrative,
            recommended_action=recommended_action(future.category, top),
            metrics=self.metrics,
        )

    @staticmethod
    def _pseudo_class_probs(category: RiskCategory, probability: float) -> dict[str, float]:
        """Deterministic one-hot-ish distribution.

        The rule model is not probabilistic; this exposes its categorical
        output in the same shape as the trained models purely so the UI can
        render them uniformly. It is derived from the score, not sampled, and
        is labelled as deterministic in the API response.
        """
        probs = dict.fromkeys(RISK_CLASSES, 0.0)
        probs[category.value] = round(max(0.5, probability), 4)
        remainder = 1.0 - probs[category.value]
        others = [c for c in RISK_CLASSES if c != category.value]
        for c in others:
            probs[c] = round(remainder / len(others), 4)
        return probs

    @staticmethod
    def _trajectory(
        current: VitalSnapshot, projected: VitalSnapshot, horizon: int
    ) -> list[dict[str, Any]]:
        steps = 6
        out = []
        for i in range(1, steps + 1):
            f = i / steps
            out.append(
                {
                    "minutes_ahead": round(horizon * f),
                    "timestamp": (current.recorded_at + timedelta(minutes=horizon * f)).isoformat(),
                    "spo2": round(current.spo2 + (projected.spo2 - current.spo2) * f, 2),
                    "heart_rate": round(
                        current.heart_rate + (projected.heart_rate - current.heart_rate) * f,
                        1,
                    ),
                    "respiratory_rate": round(
                        current.respiratory_rate
                        + (projected.respiratory_rate - current.respiratory_rate) * f,
                        1,
                    ),
                    "fatigue_score": round(
                        current.fatigue_score
                        + (projected.fatigue_score - current.fatigue_score) * f,
                        1,
                    ),
                    "is_predicted": True,
                }
            )
        return out


class LSTMModel(ModelInterface):
    """PyTorch LSTM loaded from a versioned registry artifact."""

    name = "lstm"
    explanation_method = ExplanationMethod.OCCLUSION_SENSITIVITY

    def __init__(self, version: str | None = None) -> None:
        self._version = version
        self._model: Any | None = None
        self._scaler: StandardScaler | None = None
        self._artifact: Any | None = None
        self._load_error: str | None = None
        self._load()

    def _load(self) -> None:
        from ml.registry import load_artifact

        artifact = load_artifact("lstm", self._version)
        if artifact is None:
            self._load_error = (
                "No trained LSTM artifact found in the model registry. "
                "Train one with: python -m ml.train --model lstm"
            )
            return
        try:
            import torch

            from ml.model import AltitudeRiskLSTM, LSTMConfig

            meta = artifact.metadata
            feature_names = list(meta.get("feature_names", []))
            if feature_names and feature_names != list(FEATURE_NAMES):
                self._load_error = (
                    "The stored artifact's feature order does not match the "
                    "current feature pipeline. Retrain the model."
                )
                return
            model = AltitudeRiskLSTM(LSTMConfig.from_dict(meta.get("config", {})))
            state = torch.load(artifact.weights_path, map_location="cpu", weights_only=True)
            model.load_state_dict(state)
            model.eval()
            self._model = model
            self._scaler = StandardScaler.from_dict(meta["scaler"])
            self._artifact = artifact
            self._version = artifact.version
            logger.info(
                "lstm_model_loaded",
                extra={"version": artifact.version, "params": meta.get("n_parameters")},
            )
        except Exception as exc:
            self._load_error = f"Failed to load the LSTM artifact: {exc}"
            logger.warning("lstm_load_failed", extra={"error": str(exc)})

    @property
    def version(self) -> str:
        return self._version or "unavailable"

    @property
    def is_available(self) -> bool:
        return self._model is not None and self._scaler is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def sequence_length(self) -> int:
        if self._artifact:
            return int(self._artifact.metadata.get("sequence_length", 24))
        return int(DEFAULT_PREDICTION["sequence_length"])

    @property
    def horizon_minutes(self) -> int:
        if self._artifact:
            return int(self._artifact.metadata.get("horizon_minutes", 30))
        return int(DEFAULT_PREDICTION["horizon_minutes"])

    @property
    def metrics(self) -> dict[str, Any] | None:
        if not self._artifact:
            return None
        return (self._artifact.metadata.get("metrics") or {}).get("test")

    @property
    def artifact_metadata(self) -> dict[str, Any] | None:
        return self._artifact.metadata if self._artifact else None

    def predict(self, readings: Sequence[Any], snapshots: Sequence[VitalSnapshot]) -> Prediction:
        if not self.is_available:
            raise RuntimeError(self._load_error or "LSTM model is unavailable.")
        started = time.perf_counter()
        seq_len = self.sequence_length
        matrix = build_feature_matrix(readings)
        window = latest_window(matrix, seq_len)
        if window is None:
            raise ValueError(
                f"The LSTM requires at least {seq_len} readings; {matrix.shape[0]} are available."
            )

        assert self._scaler is not None
        assert self._model is not None
        scaled = self._scaler.transform(window).astype(np.float32)

        from ml.model import elevated_probability, occlusion_attributions, predict_proba

        probs, attention = predict_proba(self._model, scaled)
        probability = elevated_probability(probs)
        predicted_index = int(np.argmax(probs))
        category = RiskCategory(RISK_CLASSES[predicted_index])

        # Baseline in scaled space is the channel mean, i.e. exactly zero.
        attributions = occlusion_attributions(
            self._model, scaled, np.zeros(len(FEATURE_NAMES), dtype=np.float32)
        )
        raw_values = window[-1]
        contributions = [
            FeatureContribution(
                feature=name,
                label=FEATURE_LABELS.get(name, name),
                value=float(raw_values[i]),
                contribution=float(attributions[name]),
                direction=(
                    "increases"
                    if attributions[name] > 1e-4
                    else "decreases"
                    if attributions[name] < -1e-4
                    else "neutral"
                ),
            )
            for i, name in enumerate(FEATURE_NAMES)
        ]
        ranked = sorted(contributions, key=lambda c: -c.contribution)
        drivers = [c.label for c in ranked[:3] if c.contribution > 1e-4]
        narrative = (
            f"The LSTM read the last {seq_len} readings and forecasts a "
            f"{probability:.0%} probability of elevated risk (HIGH or CRITICAL) "
            f"{self.horizon_minutes} minutes ahead, with "
            f"{category.value} the single most likely category. Occlusion "
            f"testing shows the prediction is driven mainly by "
            + (", ".join(drivers) if drivers else "no single dominant channel")
            + "."
        )
        trajectory = self._trajectory(snapshots, probs)

        return Prediction(
            model_name=self.name,
            model_version=self.version,
            risk_probability=float(probability),
            predicted_category=category,
            class_probabilities={
                RISK_CLASSES[i]: float(probs[i]) for i in range(len(RISK_CLASSES))
            },
            contributions=contributions,
            explanation_method=self.explanation_method,
            horizon_minutes=self.horizon_minutes,
            sequence_length=seq_len,
            inference_ms=round((time.perf_counter() - started) * 1000, 3),
            trajectory=trajectory,
            narrative=narrative,
            recommended_action=recommended_action(category, [c.feature for c in ranked[:3]]),
            metrics=self.metrics,
            attention=[round(float(a), 5) for a in attention],
        )

    def _trajectory(
        self, snapshots: Sequence[VitalSnapshot], probs: np.ndarray
    ) -> list[dict[str, Any]]:
        """Interpolate the observed trend toward the predicted risk state.

        The model classifies a future category; it does not regress individual
        future vitals. This trajectory is therefore an *illustrative* forward
        projection of the observed trend, weighted by the predicted class
        distribution, and it is flagged ``is_predicted`` so the UI renders it
        distinctly from measured history.
        """
        if not snapshots:
            return []
        current = snapshots[-1]
        window = snapshots[-min(len(snapshots), 20) :]
        span = max(
            1.0,
            (current.recorded_at - window[0].recorded_at).total_seconds() / 60.0,
        )
        severity = float(sum(probs[i] for i in ELEVATED_CLASSES))
        # Blend the observed slope with the model's severity expectation.
        spo2_slope = (current.spo2 - window[0].spo2) / span
        hr_slope = (current.heart_rate - window[0].heart_rate) / span
        spo2_slope = spo2_slope * 0.5 - severity * 0.06
        hr_slope = hr_slope * 0.5 + severity * 0.30

        out = []
        for i in range(1, 7):
            minutes = self.horizon_minutes * i / 6
            out.append(
                {
                    "minutes_ahead": round(minutes),
                    "timestamp": (current.recorded_at + timedelta(minutes=minutes)).isoformat(),
                    "spo2": round(float(np.clip(current.spo2 + spo2_slope * minutes, 50, 100)), 2),
                    "heart_rate": round(
                        float(np.clip(current.heart_rate + hr_slope * minutes, 35, 210)), 1
                    ),
                    "respiratory_rate": round(
                        float(np.clip(current.respiratory_rate + severity * 0.12 * minutes, 6, 48)),
                        1,
                    ),
                    "fatigue_score": round(
                        float(np.clip(current.fatigue_score + severity * 0.18 * minutes, 0, 100)),
                        1,
                    ),
                    "is_predicted": True,
                }
            )
        return out


class GradientBoostingModel(ModelInterface):
    """scikit-learn HistGradientBoosting comparison model."""

    name = "gradient_boosting"
    explanation_method = ExplanationMethod.IMPURITY_IMPORTANCE

    def __init__(self, version: str | None = None) -> None:
        self._version = version
        self._estimator: Any | None = None
        self._scaler: StandardScaler | None = None
        self._artifact: Any | None = None
        self._load_error: str | None = None
        self._load()

    def _load(self) -> None:
        from ml.registry import load_artifact

        artifact = load_artifact("gradient_boosting", self._version)
        if artifact is None:
            self._load_error = (
                "No trained gradient-boosting artifact found. Train one with: "
                "python -m ml.train --model gb"
            )
            return
        try:
            import joblib

            self._estimator = joblib.load(artifact.estimator_path)
            self._scaler = StandardScaler.from_dict(artifact.metadata["scaler"])
            self._artifact = artifact
            self._version = artifact.version
        except Exception as exc:
            self._load_error = f"Failed to load the gradient-boosting artifact: {exc}"

    @property
    def version(self) -> str:
        return self._version or "unavailable"

    @property
    def is_available(self) -> bool:
        return self._estimator is not None and self._scaler is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def sequence_length(self) -> int:
        if self._artifact:
            return int(self._artifact.metadata.get("sequence_length", 24))
        return int(DEFAULT_PREDICTION["sequence_length"])

    @property
    def horizon_minutes(self) -> int:
        if self._artifact:
            return int(self._artifact.metadata.get("horizon_minutes", 30))
        return int(DEFAULT_PREDICTION["horizon_minutes"])

    @property
    def metrics(self) -> dict[str, Any] | None:
        if not self._artifact:
            return None
        return (self._artifact.metadata.get("metrics") or {}).get("test")

    def predict(self, readings: Sequence[Any], snapshots: Sequence[VitalSnapshot]) -> Prediction:
        if not self.is_available:
            raise RuntimeError(self._load_error or "Gradient boosting is unavailable.")
        started = time.perf_counter()
        from ml.baseline import flatten_windows

        seq_len = self.sequence_length
        matrix = build_feature_matrix(readings)
        window = latest_window(matrix, seq_len)
        if window is None:
            raise ValueError(
                f"This model requires at least {seq_len} readings; {matrix.shape[0]} are available."
            )
        assert self._scaler is not None
        assert self._estimator is not None
        scaled = self._scaler.transform(window).astype(np.float32)[None, :, :]
        probs = self._estimator.predict_proba(flatten_windows(scaled))[0]
        # Some splits may lack a class entirely; realign to the full class set.
        full = np.zeros(len(RISK_CLASSES))
        for i, cls in enumerate(getattr(self._estimator, "classes_", range(len(probs)))):
            if int(cls) < len(full):
                full[int(cls)] = probs[i]
        if full.sum() > 0:
            full = full / full.sum()

        probability = float(sum(full[i] for i in ELEVATED_CLASSES))
        category = RiskCategory(RISK_CLASSES[int(np.argmax(full))])
        importance = (
            (self._artifact.metadata.get("permutation_importance") or {}) if self._artifact else {}
        )
        raw_values = window[-1]
        contributions = [
            FeatureContribution(
                feature=name,
                label=FEATURE_LABELS.get(name, name),
                value=float(raw_values[i]),
                contribution=float(importance.get(name, 0.0)),
                direction="increases" if importance.get(name, 0.0) > 0 else "neutral",
            )
            for i, name in enumerate(FEATURE_NAMES)
        ]
        return Prediction(
            model_name=self.name,
            model_version=self.version,
            risk_probability=probability,
            predicted_category=category,
            class_probabilities={RISK_CLASSES[i]: float(full[i]) for i in range(len(RISK_CLASSES))},
            contributions=contributions,
            explanation_method=self.explanation_method,
            horizon_minutes=self.horizon_minutes,
            sequence_length=seq_len,
            inference_ms=round((time.perf_counter() - started) * 1000, 3),
            narrative=(
                f"The gradient-boosting comparison model forecasts a "
                f"{probability:.0%} probability of elevated risk "
                f"{self.horizon_minutes} minutes ahead. Its explanation is "
                "global permutation importance, so it describes what the model "
                "relies on overall rather than this specific case."
            ),
            recommended_action=recommended_action(category, []),
            metrics=self.metrics,
        )


class PredictionService:
    """Chooses a model, runs inference and normalises the result."""

    def __init__(self, risk_engine: RiskEngine | None = None) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self._models: dict[str, ModelInterface] = {}
        self.reload()

    def reload(self) -> None:
        """(Re)load every model. Called at startup and after training."""
        self._models = {
            "rule_baseline": RuleBaselineModel(self.risk_engine),
            "lstm": LSTMModel(),
            "gradient_boosting": GradientBoostingModel(),
        }

    @property
    def models(self) -> dict[str, ModelInterface]:
        return self._models

    def available_models(self) -> list[str]:
        return [name for name, m in self._models.items() if m.is_available]

    def get(self, name: str | None) -> ModelInterface:
        if not name:
            name = "rule_baseline"
        model = self._models.get(name)
        if model is None:
            raise NotFoundError(
                f"Unknown model {name!r}. Available models: {', '.join(sorted(self._models))}."
            )
        return model

    def describe_all(self) -> list[dict[str, Any]]:
        out = []
        for model in self._models.values():
            payload = model.describe()
            error = getattr(model, "load_error", None)
            if error:
                payload["unavailable_reason"] = error
            out.append(payload)
        return out

    def predict(
        self,
        readings: Sequence[Any],
        snapshots: Sequence[VitalSnapshot],
        model_name: str | None = None,
    ) -> Prediction:
        """Run inference, degrading transparently when a model cannot serve."""
        requested = model_name or "rule_baseline"
        model = self.get(requested)
        if model.is_available:
            try:
                return model.predict(readings, snapshots)
            except (ValueError, RuntimeError) as exc:
                reason = str(exc)
                logger.info(
                    "prediction_fallback",
                    extra={"requested": requested, "reason": reason},
                )
        else:
            reason = getattr(model, "load_error", None) or (
                f"Model {requested!r} is not available."
            )

        if requested == "rule_baseline":
            raise RuntimeError(reason)

        baseline = self.get("rule_baseline")
        prediction = baseline.predict(readings, snapshots)
        prediction.fallback_reason = (
            f"{requested} could not serve this prediction ({reason}). "
            "The transparent rule baseline was used instead; this result is "
            f"NOT from the {requested} model."
        )
        return prediction

    def compare(
        self, readings: Sequence[Any], snapshots: Sequence[VitalSnapshot]
    ) -> list[dict[str, Any]]:
        """Run every available model on the same input for side-by-side view."""
        out = []
        for name, model in self._models.items():
            entry: dict[str, Any] = {
                "model_name": name,
                "model_version": model.version,
                "available": model.is_available,
                "explanation_method": model.explanation_method.value,
                "metrics": model.metrics,
                "data_provenance": PROVENANCE,
            }
            if not model.is_available:
                entry["unavailable_reason"] = getattr(model, "load_error", None)
                out.append(entry)
                continue
            try:
                prediction = model.predict(readings, snapshots)
                entry |= {
                    "risk_probability": round(prediction.risk_probability, 5),
                    "predicted_category": prediction.predicted_category.value,
                    "class_probabilities": {
                        k: round(v, 5) for k, v in prediction.class_probabilities.items()
                    },
                    "inference_ms": prediction.inference_ms,
                    "horizon_minutes": prediction.horizon_minutes,
                    "top_contributions": [
                        c.as_dict()
                        for c in sorted(
                            prediction.contributions, key=lambda c: -abs(c.contribution)
                        )[:5]
                    ],
                    "narrative": prediction.narrative,
                }
            except (ValueError, RuntimeError) as exc:
                entry["error"] = str(exc)
            out.append(entry)
        return out


_service: PredictionService | None = None


def get_prediction_service() -> PredictionService:
    global _service
    if _service is None:
        _service = PredictionService()
    return _service


def reset_prediction_service() -> None:
    global _service
    _service = None
