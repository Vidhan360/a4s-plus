"""Synthetic labelled dataset builder.

SYNTHETIC TRAINING DATA — RESEARCH / DEMO ONLY.

No real medical dataset is used or available for this prototype. This module
generates labelled time-series by running the *same* physiological simulator
the live platform uses, across a population of randomised personnel profiles
and all five scenarios.

Labelling
---------
The label for a window ending at time ``t`` is the **risk category the
transparent rule engine assigns at ``t + horizon``**. The learning task is
therefore explicitly: *"given the last N minutes of vitals, anticipate the risk
state the rule engine will report H minutes from now."*

This framing is stated plainly because it bounds what the model can claim: the
LSTM learns to forecast a known deterministic function of future physiological
state, not to predict clinically adjudicated outcomes. Reported metrics measure
exactly that task on held-out synthetic subjects and nothing more.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from app.models.enums import Scenario
from app.services.risk_engine import RiskEngine, VitalSnapshot
from app.simulation.environment import EnvironmentModel
from app.simulation.vitals import PersonProfile, VitalsSimulator
from ml.features import (
    FEATURE_NAMES,
    RISK_CLASSES,
    build_feature_matrix,
    make_windows,
)

#: Scenario sampling weights. NORMAL and RECOVERY are over-represented in real
#: operations, but a purely NORMAL-heavy set would leave the elevated classes
#: too sparse to learn, so the mix is deliberately balanced toward informative
#: trajectories. This choice is a modelling decision, documented in docs/ml.md.
SCENARIO_WEIGHTS: dict[Scenario, float] = {
    Scenario.NORMAL: 0.24,
    Scenario.GRADUAL_DETERIORATION: 0.24,
    Scenario.ACUTE_EVENT: 0.20,
    Scenario.ALTITUDE_STRESS: 0.22,
    Scenario.RECOVERY: 0.10,
}


@dataclass
class DatasetBundle:
    x_train: np.ndarray
    y_train: np.ndarray
    x_val: np.ndarray
    y_val: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    meta: dict[str, Any]

    def describe(self) -> str:
        def dist(y: np.ndarray) -> str:
            counts = np.bincount(y, minlength=len(RISK_CLASSES))
            total = max(1, counts.sum())
            return "  ".join(
                f"{RISK_CLASSES[i]}={counts[i]} ({100 * counts[i] / total:.1f}%)"
                for i in range(len(RISK_CLASSES))
            )

        return (
            f"train {self.x_train.shape} | {dist(self.y_train)}\n"
            f"val   {self.x_val.shape} | {dist(self.y_val)}\n"
            f"test  {self.x_test.shape} | {dist(self.y_test)}"
        )


#: Fraction of subjects drawn from a poorly-acclimatised, high-start-altitude
#: cohort. Without this the CRITICAL class is essentially absent from the
#: dataset and the model cannot learn it at all. This is a deliberate sampling
#: decision to cover the label space, not an assertion about real populations.
VULNERABLE_FRACTION = 0.3


def random_profile(rng: np.random.Generator, index: int) -> PersonProfile:
    """A randomised but plausible synthetic subject."""
    vulnerable = bool(rng.random() < VULNERABLE_FRACTION)
    if vulnerable:
        acclimatisation = float(np.clip(rng.normal(0.24, 0.1), 0.05, 0.45))
        start_altitude = float(rng.uniform(5000.0, 5900.0))
        fitness = float(np.clip(rng.normal(0.42, 0.13), 0.15, 0.75))
    else:
        acclimatisation = float(np.clip(rng.normal(0.65, 0.16), 0.3, 0.95))
        start_altitude = float(rng.uniform(3800.0, 5000.0))
        fitness = float(np.clip(rng.normal(0.66, 0.14), 0.3, 0.98))
    return PersonProfile(
        personnel_id=uuid.uuid4(),
        call_sign=f"SYN-{index:04d}",
        age=int(rng.integers(21, 46)),
        baseline_heart_rate=float(rng.normal(64.0, 6.0)),
        baseline_spo2=float(np.clip(rng.normal(96.8, 0.9), 93.0, 99.0)),
        acclimatisation=acclimatisation,
        fitness=fitness,
        start_altitude_m=start_altitude,
    )


def generate_series(
    profile: PersonProfile,
    scenario: Scenario,
    steps: int,
    step_seconds: float,
    seed: int,
    index: int,
    engine: RiskEngine,
    trend_window: int = 20,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate one subject and label every timestep with its risk class."""
    sim = VitalsSimulator(profile, scenario, seed=seed, index=index)
    env_model = EnvironmentModel(seed=seed + index * 17)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    samples = []
    for i in range(steps):
        env = env_model.step(i * step_seconds)
        sim.step(step_seconds, env)
        samples.append(sim.sample(start + timedelta(seconds=i * step_seconds), env))

    snapshots = [
        VitalSnapshot(
            recorded_at=s.recorded_at,
            heart_rate=s.heart_rate,
            spo2=s.spo2,
            body_temp_c=s.body_temp_c,
            respiratory_rate=s.respiratory_rate,
            bp_systolic=s.bp_systolic,
            bp_diastolic=s.bp_diastolic,
            altitude_m=s.environment.altitude_m,
            fatigue_score=s.fatigue_score,
            activity_level=s.activity_level.value,
            env_temp_c=s.environment.env_temp_c,
            wind_kph=s.environment.wind_kph,
            baseline_heart_rate=profile.baseline_heart_rate,
            baseline_spo2=profile.baseline_spo2,
        )
        for s in samples
    ]

    labels = np.zeros(len(snapshots), dtype=np.int64)
    for i, snap in enumerate(snapshots):
        history = snapshots[max(0, i - trend_window) : i + 1]
        result = engine.evaluate(snap, history)
        labels[i] = RISK_CLASSES.index(result.category.value)

    return build_feature_matrix(samples), labels


def build_dataset(
    n_subjects: int = 480,
    steps: int = 190,
    step_seconds: float = 60.0,
    sequence_length: int = 24,
    horizon: int = 30,
    seed: int = 20260909,
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
) -> DatasetBundle:
    """Build train/val/test windows, split **by subject**.

    Splitting by subject rather than by window is essential: adjacent windows
    from one subject overlap heavily, so a random window split would leak
    almost-identical rows across splits and inflate every metric.
    """
    rng = np.random.default_rng(seed)
    engine = RiskEngine()

    scenarios = list(SCENARIO_WEIGHTS)
    probs = np.array([SCENARIO_WEIGHTS[s] for s in scenarios], dtype=float)
    probs /= probs.sum()

    subjects: list[tuple[np.ndarray, np.ndarray, str]] = []
    for i in range(n_subjects):
        profile = random_profile(rng, i)
        scenario = scenarios[int(rng.choice(len(scenarios), p=probs))]
        matrix, labels = generate_series(profile, scenario, steps, step_seconds, seed, i, engine)
        subjects.append((matrix, labels, scenario.value))

    n_test = max(1, int(n_subjects * test_fraction))
    n_val = max(1, int(n_subjects * val_fraction))
    order = rng.permutation(n_subjects)
    test_ids = set(order[:n_test].tolist())
    val_ids = set(order[n_test : n_test + n_val].tolist())

    buckets: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {"train": [], "val": [], "test": []}
    scenario_counts: dict[str, int] = {}
    for i, (matrix, labels, scenario_name) in enumerate(subjects):
        x, y = make_windows(matrix, labels, sequence_length, horizon)
        if x.shape[0] == 0:
            continue
        split: str = "test" if i in test_ids else "val" if i in val_ids else "train"
        buckets[split].append((x, y))
        scenario_counts[scenario_name] = scenario_counts.get(scenario_name, 0) + 1

    def stack(name: str) -> tuple[np.ndarray, np.ndarray]:
        if not buckets[name]:
            return (
                np.zeros((0, sequence_length, len(FEATURE_NAMES)), dtype=np.float32),
                np.zeros((0,), dtype=np.int64),
            )
        xs = np.concatenate([b[0] for b in buckets[name]], axis=0)
        ys = np.concatenate([b[1] for b in buckets[name]], axis=0)
        return xs, ys

    x_train, y_train = stack("train")
    x_val, y_val = stack("val")
    x_test, y_test = stack("test")

    return DatasetBundle(
        x_train=x_train,
        y_train=y_train,
        x_val=x_val,
        y_val=y_val,
        x_test=x_test,
        y_test=y_test,
        meta={
            "provenance": "SYNTHETIC_SIMULATION",
            "disclaimer": (
                "Synthetic training data — research/demo only. Not real "
                "patient data and not clinically validated."
            ),
            "label_definition": (
                "Rule-engine risk category evaluated at t + horizon "
                f"({horizon} simulated minutes ahead)."
            ),
            "n_subjects": n_subjects,
            "steps_per_subject": steps,
            "step_seconds": step_seconds,
            "sequence_length": sequence_length,
            "horizon_minutes": int(horizon * step_seconds / 60),
            "horizon_steps": horizon,
            "seed": seed,
            "feature_names": list(FEATURE_NAMES),
            "classes": list(RISK_CLASSES),
            "split_strategy": "grouped_by_subject",
            "scenario_counts": scenario_counts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
