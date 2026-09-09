"""PyTorch LSTM risk-forecasting model and its explainability method."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from ml.features import ELEVATED_CLASSES, FEATURE_NAMES, N_FEATURES, RISK_CLASSES


@dataclass
class LSTMConfig:
    input_size: int = N_FEATURES
    hidden_size: int = 96
    num_layers: int = 2
    dropout: float = 0.25
    num_classes: int = len(RISK_CLASSES)
    bidirectional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_size": self.input_size,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "num_classes": self.num_classes,
            "bidirectional": self.bidirectional,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LSTMConfig:
        return cls(**{k: v for k, v in payload.items() if k in cls.__annotations__})


class AltitudeRiskLSTM(nn.Module):
    """LSTM classifier over a window of vital-sign features.

    Architecture
    ------------
    ``LSTM(input=16, hidden=96, layers=2, dropout=0.25)`` → attention-weighted
    temporal pooling → ``LayerNorm`` → ``Linear(96→64)`` → ``GELU`` →
    ``Dropout`` → ``Linear(64→4)`` logits over
    ``(LOW, MODERATE, HIGH, CRITICAL)``.

    Attention pooling (rather than taking only the last hidden state) lets the
    model weight the timesteps that matter — useful when deterioration begins
    partway through the window — and the attention weights are additionally
    surfaced as a secondary, genuinely-computed explanation signal.
    """

    def __init__(self, config: LSTMConfig | None = None) -> None:
        super().__init__()
        self.config = config or LSTMConfig()
        c = self.config
        self.lstm = nn.LSTM(
            input_size=c.input_size,
            hidden_size=c.hidden_size,
            num_layers=c.num_layers,
            batch_first=True,
            dropout=c.dropout if c.num_layers > 1 else 0.0,
            bidirectional=c.bidirectional,
        )
        out_dim = c.hidden_size * (2 if c.bidirectional else 1)
        self.attention = nn.Linear(out_dim, 1)
        self.norm = nn.LayerNorm(out_dim)
        self.head = nn.Sequential(
            nn.Linear(out_dim, 64),
            nn.GELU(),
            nn.Dropout(c.dropout),
            nn.Linear(64, c.num_classes),
        )

    def forward(
        self, x: torch.Tensor, return_attention: bool = False
    ) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor]:
        seq, _ = self.lstm(x)  # (B, T, H)
        weights = torch.softmax(self.attention(seq), dim=1)  # (B, T, 1)
        pooled = (seq * weights).sum(dim=1)  # (B, H)
        logits = self.head(self.norm(pooled))
        if return_attention:
            return logits, weights.squeeze(-1)
        return logits


def elevated_probability(probs: np.ndarray) -> float:
    """P(HIGH) + P(CRITICAL) — the headline risk probability."""
    return float(sum(probs[i] for i in ELEVATED_CLASSES))


@torch.no_grad()
def predict_proba(
    model: AltitudeRiskLSTM, window: np.ndarray, device: str = "cpu"
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(class_probabilities, attention_weights)`` for one window."""
    model.eval()
    x = torch.from_numpy(window.astype(np.float32)).unsqueeze(0).to(device)
    logits, attention = model(x, return_attention=True)
    probs = torch.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
    return probs, attention.squeeze(0).cpu().numpy()


@torch.no_grad()
def occlusion_attributions(
    model: AltitudeRiskLSTM,
    window: np.ndarray,
    baseline: np.ndarray,
    device: str = "cpu",
) -> dict[str, float]:
    """Per-feature attribution by occlusion sensitivity, measured in logit space.

    For each input channel independently, the channel is replaced across the
    whole window by its dataset-mean value (which is exactly ``0`` in scaled
    space) and the model is re-run. The attribution is the resulting change in
    the **elevated-risk logit**::

        s(x)            = logit( P(HIGH) + P(CRITICAL) )
        attribution_f   = s(original) - s(channel f neutralised)

    A positive value means the channel's actual values were pushing the
    prediction toward elevated risk.

    Why the logit and not the probability
    -------------------------------------
    When the model is confident (``P_elevated`` near 0 or 1) the probability
    saturates, and occluding any single channel moves it by a negligible
    amount — every attribution collapses toward zero and the explanation
    becomes useless precisely when the risk is highest. The logit is monotonic
    in the probability but unbounded, so it retains resolution under
    saturation. Attributions are therefore reported in logit units (nats).

    This is a real, model-faithful perturbation method computed at inference
    time. It is **not** SHAP and is never labelled as SHAP. Cost is
    ``N_FEATURES + 1`` forward passes, negligible at this model size.
    """
    model.eval()
    probs, _ = predict_proba(model, window, device)
    reference = _elevated_logit(probs)

    batch = np.repeat(window[None, :, :], N_FEATURES, axis=0).astype(np.float32)
    for f in range(N_FEATURES):
        batch[f, :, f] = baseline[f]
    x = torch.from_numpy(batch).to(device)
    occluded = torch.softmax(model(x), dim=-1).cpu().numpy()

    return {
        name: float(reference - _elevated_logit(occluded[f]))
        for f, name in enumerate(FEATURE_NAMES)
    }


#: Clamp keeps the logit finite when softmax output is exactly 0.0 or 1.0.
_LOGIT_EPS = 1e-6


def _elevated_logit(probs: np.ndarray) -> float:
    """Log-odds of the elevated-risk (HIGH or CRITICAL) outcome."""
    p = float(np.clip(elevated_probability(probs), _LOGIT_EPS, 1.0 - _LOGIT_EPS))
    return float(np.log(p / (1.0 - p)))
