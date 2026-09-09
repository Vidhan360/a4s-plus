"""Synthetic environment model: temperature, wind and weather fronts.

Deterministic given a seed. Drives the ambient conditions that the
physiological model reacts to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class EnvironmentState:
    sim_seconds: float
    base_temp_c: float
    wind_kph: float
    front_intensity: float  # 0..1 storm-front strength
    visibility_km: float

    def temp_at_altitude(self, altitude_m: float) -> float:
        """Apply an environmental lapse rate (~6.5 °C per 1000 m)."""
        return self.base_temp_c - (altitude_m - 4000.0) * 0.0065

    def as_dict(self) -> dict[str, float]:
        return {
            "base_temp_c": round(self.base_temp_c, 2),
            "wind_kph": round(self.wind_kph, 2),
            "front_intensity": round(self.front_intensity, 3),
            "visibility_km": round(self.visibility_km, 2),
        }


class EnvironmentModel:
    """Diurnal cycle plus slow-moving synthetic weather fronts."""

    def __init__(self, seed: int = 20260909) -> None:
        self.rng = np.random.default_rng(seed ^ 0x5EED)
        self._front_phase = float(self.rng.random() * math.tau)
        self._front_speed = 1.0 / (5400.0 + self.rng.random() * 5400.0)
        self._wind_noise = 0.0

    def step(self, sim_seconds: float) -> EnvironmentState:
        # Diurnal temperature: coldest ~04:00, warmest ~14:00.
        day_fraction = (sim_seconds % 86400.0) / 86400.0
        diurnal = -math.cos((day_fraction - 0.17) * math.tau)
        base_temp = -17.0 + 8.5 * diurnal

        front = 0.5 + 0.5 * math.sin(self._front_phase + sim_seconds * self._front_speed * math.tau)
        front = float(np.clip(front**1.6, 0.0, 1.0))

        # Wind: front-driven with a mean-reverting stochastic component.
        self._wind_noise = 0.82 * self._wind_noise + 0.18 * float(self.rng.normal(0, 9.0))
        wind = float(np.clip(14.0 + 58.0 * front + self._wind_noise, 0.0, 130.0))
        base_temp -= 6.5 * front

        visibility = float(np.clip(22.0 - 20.0 * front + self.rng.normal(0, 1.2), 0.15, 30.0))
        return EnvironmentState(
            sim_seconds=sim_seconds,
            base_temp_c=base_temp,
            wind_kph=wind,
            front_intensity=front,
            visibility_km=visibility,
        )
