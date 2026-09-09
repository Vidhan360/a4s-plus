"""The PyTorch LSTM itself: shapes, determinism, learning and explainability.

These tests exercise the real network (no mocks). One of them trains the model
for a handful of epochs on a tiny synthetic task and asserts the loss actually
decreases — that is the cheapest honest way to prove the training loop works.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from ml.features import N_FEATURES, RISK_CLASSES, StandardScaler
from ml.model import (
    AltitudeRiskLSTM,
    LSTMConfig,
    elevated_probability,
    occlusion_attributions,
    predict_proba,
)


@pytest.fixture
def model() -> AltitudeRiskLSTM:
    torch.manual_seed(0)
    return AltitudeRiskLSTM(LSTMConfig())


def test_default_config_matches_the_feature_contract(model: AltitudeRiskLSTM) -> None:
    assert model.config.input_size == N_FEATURES
    assert model.config.num_classes == len(RISK_CLASSES)


def test_config_round_trips(model: AltitudeRiskLSTM) -> None:
    restored = LSTMConfig.from_dict(model.config.as_dict())
    assert restored.as_dict() == model.config.as_dict()


def test_forward_pass_shapes(model: AltitudeRiskLSTM) -> None:
    x = torch.randn(5, 24, N_FEATURES)
    logits = model(x)
    assert logits.shape == (5, len(RISK_CLASSES))
    logits, attention = model(x, return_attention=True)
    assert attention.shape == (5, 24)


def test_attention_weights_are_a_probability_distribution_over_time(
    model: AltitudeRiskLSTM,
) -> None:
    x = torch.randn(3, 24, N_FEATURES)
    _, attention = model(x, return_attention=True)
    assert torch.all(attention >= 0)
    assert torch.allclose(attention.sum(dim=1), torch.ones(3), atol=1e-5)


def test_parameter_count_is_reported_and_non_trivial(model: AltitudeRiskLSTM) -> None:
    total = sum(p.numel() for p in model.parameters())
    assert total > 100_000


def test_predict_proba_returns_a_normalised_distribution(model: AltitudeRiskLSTM) -> None:
    window = np.random.default_rng(0).normal(size=(24, N_FEATURES)).astype(np.float32)
    probs, attention = predict_proba(model, window)
    assert probs.shape == (len(RISK_CLASSES),)
    assert probs.sum() == pytest.approx(1.0, abs=1e-5)
    assert (probs >= 0).all()
    assert attention.shape == (24,)


def test_inference_is_deterministic_in_eval_mode(model: AltitudeRiskLSTM) -> None:
    window = np.random.default_rng(1).normal(size=(24, N_FEATURES)).astype(np.float32)
    first, _ = predict_proba(model, window)
    second, _ = predict_proba(model, window)
    assert np.array_equal(first, second)


def test_elevated_probability_is_the_sum_of_high_and_critical() -> None:
    probs = np.array([0.5, 0.2, 0.2, 0.1])
    assert elevated_probability(probs) == pytest.approx(0.3)


def test_variable_window_lengths_are_accepted(model: AltitudeRiskLSTM) -> None:
    for length in (8, 24, 48):
        probs, attention = predict_proba(model, np.zeros((length, N_FEATURES), dtype=np.float32))
        assert probs.sum() == pytest.approx(1.0, abs=1e-5)
        assert attention.shape == (length,)


# ------------------------------------------------------------ explainability
def test_occlusion_attributions_cover_every_channel(model: AltitudeRiskLSTM) -> None:
    window = np.random.default_rng(2).normal(size=(24, N_FEATURES)).astype(np.float32)
    attributions = occlusion_attributions(model, window, np.zeros(N_FEATURES, dtype=np.float32))
    assert len(attributions) == N_FEATURES
    assert all(np.isfinite(v) for v in attributions.values())


def test_neutral_window_has_zero_attribution(model: AltitudeRiskLSTM) -> None:
    """Occluding a channel that already equals the baseline must change nothing."""
    window = np.zeros((24, N_FEATURES), dtype=np.float32)
    attributions = occlusion_attributions(model, window, np.zeros(N_FEATURES, dtype=np.float32))
    assert all(abs(v) < 1e-4 for v in attributions.values())


def test_attribution_grows_with_the_size_of_the_perturbation(
    model: AltitudeRiskLSTM,
) -> None:
    baseline = np.zeros(N_FEATURES, dtype=np.float32)
    small = np.zeros((24, N_FEATURES), dtype=np.float32)
    small[:, 1] = 0.5
    large = np.zeros((24, N_FEATURES), dtype=np.float32)
    large[:, 1] = 3.0
    a_small = abs(occlusion_attributions(model, small, baseline)["spo2"])
    a_large = abs(occlusion_attributions(model, large, baseline)["spo2"])
    assert a_large > a_small


# ------------------------------------------------------------------ training
def test_the_model_can_actually_learn_a_separable_task() -> None:
    """End-to-end gradient check: loss must fall and accuracy must beat chance.

    The task is deliberately easy (channel 1 encodes the class) so the test is
    fast and stable, but nothing about it is faked: a real optimiser runs real
    backward passes through the real network.
    """
    torch.manual_seed(7)
    rng = np.random.default_rng(7)
    n, seq = 512, 16
    y = rng.integers(0, len(RISK_CLASSES), size=n)
    x = rng.normal(0.0, 0.3, size=(n, seq, N_FEATURES))
    x[:, :, 1] += y[:, None] * 1.5  # class signal on the spo2 channel
    scaler = StandardScaler().fit(x.astype(np.float32))
    xs = torch.from_numpy(scaler.transform(x).astype(np.float32))
    ys = torch.from_numpy(y.astype(np.int64))

    model = AltitudeRiskLSTM(LSTMConfig(hidden_size=32, num_layers=1, dropout=0.0))
    optimiser = torch.optim.Adam(model.parameters(), lr=5e-3)
    loss_fn = torch.nn.CrossEntropyLoss()

    model.train()
    first_loss = None
    last_loss = None
    for _epoch in range(25):
        optimiser.zero_grad()
        loss = loss_fn(model(xs), ys)
        loss.backward()
        optimiser.step()
        last_loss = float(loss.item())
        if first_loss is None:
            first_loss = last_loss

    assert first_loss is not None and last_loss is not None
    assert last_loss < first_loss * 0.75, (first_loss, last_loss)

    model.eval()
    with torch.no_grad():
        accuracy = float((model(xs).argmax(dim=-1) == ys).float().mean())
    assert accuracy > 0.60, accuracy


def test_state_dict_round_trips_through_disk(tmp_path, model: AltitudeRiskLSTM) -> None:
    path = tmp_path / "model.pt"
    torch.save(model.state_dict(), path)
    restored = AltitudeRiskLSTM(LSTMConfig())
    restored.load_state_dict(torch.load(path, weights_only=True))
    window = np.random.default_rng(3).normal(size=(24, N_FEATURES)).astype(np.float32)
    assert np.allclose(predict_proba(model, window)[0], predict_proba(restored, window)[0])
