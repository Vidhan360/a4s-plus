"""Physiological simulation model for personnel vitals.

What this is
------------
A deterministic, scenario-driven generator of *plausible-looking* time-series
vital signs. It couples altitude, exertion, cold exposure and fatigue to
heart rate, SpO₂, respiratory rate, temperature and blood pressure using simple
monotonic relationships and a first-order lag, so trajectories look and behave
like continuous physiological signals rather than random noise.

What this is NOT
----------------
This is **not** a validated physiological model, not derived from clinical
data, and not usable for any medical purpose. It exists to exercise the
platform's detection → prediction → alerting pipeline with realistic-shaped
data. Every value it produces is stamped ``source=SIMULATION``.

Determinism
-----------
Each person gets an independent RNG seeded from ``(run_seed, personnel_index)``
so a run is exactly reproducible and adding a person does not perturb others.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import numpy as np

from app.datasources.base import EnvironmentSample, VitalSample
from app.models.enums import ActivityLevel, DataSourceKind, Scenario
from app.simulation.environment import EnvironmentState


#: Rough altitude -> inspired-oxygen scaling, normalised to sea level.
def _oxygen_availability(altitude_m: float) -> float:
    return float(math.exp(-altitude_m / 8400.0))


ACTIVITY_EXERTION: dict[ActivityLevel, float] = {
    ActivityLevel.RESTING: 0.05,
    ActivityLevel.LIGHT: 0.25,
    ActivityLevel.MODERATE: 0.5,
    ActivityLevel.HEAVY: 0.75,
    ActivityLevel.EXTREME: 0.95,
}


@dataclass
class PersonProfile:
    """Static per-person characteristics used by the model."""

    personnel_id: UUID
    call_sign: str
    age: int
    baseline_heart_rate: float
    baseline_spo2: float
    #: 0..1; higher = better acclimatised, resists hypoxia more.
    acclimatisation: float = 0.6
    #: 0..1; higher = fitter, lower HR response to exertion.
    fitness: float = 0.6
    start_altitude_m: float = 4200.0
    grid_x: int = 10
    grid_y: int = 10


@dataclass
class PersonState:
    """Mutable per-person simulation state."""

    altitude_m: float
    fatigue: float = 12.0
    spo2: float = 96.0
    heart_rate: float = 70.0
    respiratory_rate: float = 14.0
    body_temp_c: float = 36.8
    bp_systolic: float = 120.0
    bp_diastolic: float = 78.0
    activity: ActivityLevel = ActivityLevel.LIGHT
    scenario: Scenario = Scenario.NORMAL
    #: Progress through the scenario, 0..1, advances with simulated time.
    phase: float = 0.0
    grid_x: float = 10.0
    grid_y: float = 10.0
    #: Latent "physiological stress" driver, 0..1.
    stress: float = 0.0
    acute_triggered: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class VitalsSimulator:
    """Advances one person's physiological state and emits samples."""

    #: Simulated seconds for a scenario to run its full course.
    SCENARIO_DURATION_S: dict[Scenario, float] = {
        Scenario.NORMAL: 7200.0,
        Scenario.GRADUAL_DETERIORATION: 5400.0,
        Scenario.ACUTE_EVENT: 2400.0,
        Scenario.ALTITUDE_STRESS: 4200.0,
        Scenario.RECOVERY: 3600.0,
    }

    def __init__(
        self,
        profile: PersonProfile,
        scenario: Scenario = Scenario.NORMAL,
        seed: int = 0,
        index: int = 0,
    ) -> None:
        self.profile = profile
        self.rng = np.random.default_rng((seed * 7919 + index * 104729) & 0xFFFFFFFF)
        self.scenario = scenario
        self.state = PersonState(
            altitude_m=profile.start_altitude_m,
            spo2=profile.baseline_spo2 - 1.0,
            heart_rate=profile.baseline_heart_rate + 4.0,
            scenario=scenario,
            grid_x=float(profile.grid_x),
            grid_y=float(profile.grid_y),
        )
        # Independent slow drifts so people never move in lockstep.
        self._drift_phase = float(self.rng.random() * math.tau)
        self._recovery_from = 0.55 + 0.35 * float(self.rng.random())

    # ------------------------------------------------------------------ setup
    def set_scenario(self, scenario: Scenario, reset_phase: bool = True) -> None:
        self.scenario = scenario
        self.state.scenario = scenario
        if reset_phase:
            self.state.phase = 0.0
            self.state.acute_triggered = False
        if scenario is Scenario.RECOVERY:
            # Recovery starts from an already-degraded state to be meaningful.
            self.state.stress = max(self.state.stress, self._recovery_from)
            self.state.fatigue = max(self.state.fatigue, 62.0)

    # ------------------------------------------------------------------- step
    def step(self, dt_seconds: float, env: EnvironmentState) -> None:
        """Advance the physiological state by ``dt_seconds`` simulated seconds."""
        s = self.state
        p = self.profile
        duration = self.SCENARIO_DURATION_S[self.scenario]
        s.phase = min(1.0, s.phase + dt_seconds / duration)

        target_stress, target_activity, altitude_rate = self._scenario_drivers(dt_seconds)
        s.activity = target_activity

        # --- Altitude changes ---
        s.altitude_m = float(np.clip(s.altitude_m + altitude_rate * dt_seconds, 3300.0, 7000.0))

        # --- Latent stress moves toward the scenario target with a lag ---
        tau = 420.0  # seconds
        alpha = 1.0 - math.exp(-dt_seconds / tau)
        s.stress += (target_stress - s.stress) * alpha
        s.stress = float(np.clip(s.stress + self.rng.normal(0, 0.004), 0.0, 1.0))

        exertion = ACTIVITY_EXERTION[s.activity]
        env_temp = env.temp_at_altitude(s.altitude_m)
        # Wind chill increases effective cold load.
        cold_load = float(np.clip((-env_temp + 0.14 * env.wind_kph - 5.0) / 40.0, 0.0, 1.0))

        # --- Fatigue: accumulates with exertion/altitude/cold, recovers at rest
        hypoxia = 1.0 - _oxygen_availability(s.altitude_m) / _oxygen_availability(3000.0)
        hypoxia = float(np.clip(hypoxia, 0.0, 1.0))
        fatigue_gain = (
            (0.85 * exertion + 0.5 * hypoxia + 0.35 * cold_load + 0.5 * s.stress)
            * (1.25 - 0.45 * p.fitness)
            * (dt_seconds / 60.0)
            * 0.55
        )
        fatigue_recovery = (
            (0.42 if s.activity is ActivityLevel.RESTING else 0.06)
            * (dt_seconds / 60.0)
            * (0.7 + 0.6 * p.fitness)
        )
        if self.scenario is Scenario.RECOVERY:
            fatigue_recovery *= 3.4
        s.fatigue = float(np.clip(s.fatigue + fatigue_gain - fatigue_recovery, 0.0, 100.0))

        # --- SpO2: driven by altitude hypoxia, acclimatisation and stress ---
        spo2_target = (
            p.baseline_spo2
            - 20.0 * hypoxia * (1.35 - 0.55 * p.acclimatisation)
            - 11.0 * s.stress
            - 0.035 * s.fatigue
            + 1.2 * (1.0 - exertion) * 0.0
        )
        spo2_target = float(np.clip(spo2_target, 55.0, 100.0))
        s.spo2 = self._lag(s.spo2, spo2_target, dt_seconds, 260.0, 0.10)
        s.spo2 = float(np.clip(s.spo2, 50.0, 100.0))

        # --- Heart rate: baseline + exertion + hypoxic/cold/stress drive ---
        hr_target = (
            p.baseline_heart_rate
            + 62.0 * exertion * (1.2 - 0.4 * p.fitness)
            + 30.0 * hypoxia
            + 42.0 * s.stress
            + 0.16 * s.fatigue
            + 7.0 * cold_load
            # Compensatory tachycardia when saturation drops.
            + max(0.0, (92.0 - s.spo2)) * 1.5
        )
        hr_target = float(np.clip(hr_target, 40.0, 205.0))
        s.heart_rate = self._lag(s.heart_rate, hr_target, dt_seconds, 95.0, 0.55)

        # --- Respiratory rate ---
        rr_target = (
            12.0
            + 15.0 * exertion
            + 9.0 * hypoxia
            + 13.0 * s.stress
            + max(0.0, (92.0 - s.spo2)) * 0.55
        )
        s.respiratory_rate = self._lag(
            s.respiratory_rate, float(np.clip(rr_target, 6.0, 46.0)), dt_seconds, 110.0, 0.22
        )

        # --- Core temperature: cold exposure vs exertional heat ---
        temp_target = (
            37.0 - 1.9 * cold_load * (1.0 - 0.45 * exertion) + 0.55 * exertion - 0.35 * s.stress
        )
        s.body_temp_c = self._lag(
            s.body_temp_c, float(np.clip(temp_target, 33.0, 40.0)), dt_seconds, 900.0, 0.035
        )

        # --- Blood pressure ---
        sys_target = 118.0 + 26.0 * s.stress + 14.0 * cold_load + 11.0 * exertion + 0.1 * s.fatigue
        s.bp_systolic = self._lag(
            s.bp_systolic, float(np.clip(sys_target, 85.0, 190.0)), dt_seconds, 240.0, 1.1
        )
        s.bp_diastolic = float(np.clip(s.bp_systolic * 0.63 + self.rng.normal(0, 1.4), 50.0, 120.0))

        # --- Slow patrol movement across the grid ---
        self._drift_phase += dt_seconds / 900.0
        s.grid_x = float(
            np.clip(s.grid_x + math.cos(self._drift_phase) * dt_seconds / 620.0, 0, 63)
        )
        s.grid_y = float(
            np.clip(s.grid_y + math.sin(self._drift_phase * 0.8) * dt_seconds / 700.0, 0, 63)
        )

    def _lag(self, current: float, target: float, dt: float, tau: float, noise: float) -> float:
        alpha = 1.0 - math.exp(-dt / tau)
        return float(current + (target - current) * alpha + self.rng.normal(0, noise))

    def _scenario_drivers(self, dt_seconds: float) -> tuple[float, ActivityLevel, float]:
        """Return ``(target_stress, activity_level, altitude_change_m_per_s)``."""
        s = self.state
        phase = s.phase
        jitter = float(self.rng.normal(0, 0.015))

        if self.scenario is Scenario.NORMAL:
            # Mild, bounded variation around a healthy operating point.
            return (
                float(np.clip(0.06 + 0.05 * math.sin(phase * math.tau) + jitter, 0.0, 0.3)),
                ActivityLevel.LIGHT if phase % 0.5 < 0.35 else ActivityLevel.MODERATE,
                0.02 * math.sin(phase * math.tau * 2),
            )

        if self.scenario is Scenario.GRADUAL_DETERIORATION:
            # Smooth monotonic ramp: the case predictive models should catch
            # well before any single threshold is breached.
            return (
                float(np.clip(0.05 + 0.82 * phase**1.35 + jitter, 0.0, 1.0)),
                ActivityLevel.MODERATE if phase < 0.7 else ActivityLevel.LIGHT,
                0.055,
            )

        if self.scenario is Scenario.ACUTE_EVENT:
            # Stable, then a sharp step change partway through.
            if phase < 0.42:
                return (
                    float(np.clip(0.1 + jitter, 0.0, 1.0)),
                    ActivityLevel.MODERATE,
                    0.03,
                )
            if not s.acute_triggered:
                s.acute_triggered = True
                s.meta["acute_onset_phase"] = round(phase, 3)
                # Immediate partial jump so onset is genuinely abrupt.
                s.stress = max(s.stress, 0.55)
            return (
                float(np.clip(0.88 + jitter, 0.0, 1.0)),
                ActivityLevel.RESTING,
                -0.02,
            )

        if self.scenario is Scenario.ALTITUDE_STRESS:
            # Sustained ascent: hypoxia rises through altitude, not illness.
            ascent = 0.34 if phase < 0.78 else 0.02
            return (
                float(np.clip(0.05 + 0.55 * phase**1.2 + jitter, 0.0, 1.0)),
                ActivityLevel.HEAVY if phase < 0.78 else ActivityLevel.LIGHT,
                ascent,
            )

        # RECOVERY: descent, rest and steady improvement.
        return (
            float(np.clip(self._recovery_from * (1.0 - phase) ** 1.5 + jitter, 0.0, 1.0)),
            ActivityLevel.RESTING,
            -0.30 if phase < 0.7 else -0.04,
        )

    # ------------------------------------------------------------------ emit
    def sample(
        self,
        recorded_at: datetime,
        env: EnvironmentState,
        origin_lat: float = 35.42,
        origin_lon: float = 77.11,
        cell_size_m: float = 250.0,
        run_id: UUID | None = None,
        weather_risk: float = 0.0,
    ) -> VitalSample:
        s = self.state
        # Grid -> plausible lat/lon so a real geospatial provider can slot in.
        lat = origin_lat + (s.grid_y * cell_size_m) / 111_320.0
        lon = origin_lon + (s.grid_x * cell_size_m) / (
            111_320.0 * max(0.2, math.cos(math.radians(origin_lat)))
        )
        return VitalSample(
            personnel_id=self.profile.personnel_id,
            recorded_at=recorded_at,
            heart_rate=s.heart_rate,
            spo2=s.spo2,
            body_temp_c=s.body_temp_c,
            respiratory_rate=s.respiratory_rate,
            bp_systolic=s.bp_systolic,
            bp_diastolic=s.bp_diastolic,
            fatigue_score=s.fatigue,
            activity_level=s.activity,
            environment=EnvironmentSample(
                env_temp_c=env.temp_at_altitude(s.altitude_m),
                wind_kph=env.wind_kph,
                altitude_m=s.altitude_m,
                latitude=lat,
                longitude=lon,
                grid_x=round(s.grid_x),
                grid_y=round(s.grid_y),
                weather_risk=weather_risk,
            ),
            source=DataSourceKind.SIMULATION,
            scenario=self.scenario.value,
            simulation_run_id=run_id,
            meta={"phase": round(s.phase, 4), "stress": round(s.stress, 4)},
        )


def simulate_series(
    profile: PersonProfile,
    scenario: Scenario,
    steps: int,
    step_seconds: float = 60.0,
    seed: int = 0,
    index: int = 0,
    start_at: datetime | None = None,
    env_model: Any | None = None,
) -> list[VitalSample]:
    """Generate a complete standalone series.

    Used by the ML dataset builder and by tests. Runs the identical model the
    live simulation uses, so training data and runtime data share a generator.
    """
    from app.simulation.environment import EnvironmentModel

    sim = VitalsSimulator(profile, scenario, seed=seed, index=index)
    env_model = env_model or EnvironmentModel(seed=seed + index)
    start = start_at or datetime.now().astimezone()
    out: list[VitalSample] = []
    for i in range(steps):
        sim_seconds = i * step_seconds
        env = env_model.step(sim_seconds)
        sim.step(step_seconds, env)
        out.append(sim.sample(start + timedelta(seconds=sim_seconds), env))
    return out
