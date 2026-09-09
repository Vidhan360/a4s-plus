"""Procedural synthetic terrain generation.

The terrain is entirely synthetic: value-noise fractional Brownian motion
shaped into ridges and valleys, with hazard layers derived from the resulting
geometry (slope, curvature, elevation band). No real geographic, satellite or
military data is used anywhere.

Hazard derivation is intentionally physically motivated so the map "reads"
correctly to a viewer:

* avalanche risk peaks on steep, snow-loaded mid-elevation slopes;
* crevasse risk peaks on low-slope glacier/icefall flats where ice flows and
  tensile stress opens fissures;
* weather risk grows with elevation and exposure (ridge-ness).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.models.enums import TerrainType

GENERATOR_VERSION = "1.0.0"


@dataclass
class TerrainGrid:
    """Generated terrain as dense numpy layers."""

    width: int
    height: int
    seed: int
    cell_size_m: float
    elevation: np.ndarray  # metres
    slope: np.ndarray  # 0..1 normalised
    avalanche: np.ndarray  # 0..1
    crevasse: np.ndarray  # 0..1
    weather: np.ndarray  # 0..1
    difficulty: np.ndarray  # 0..1
    blocked: np.ndarray  # bool
    terrain_type: np.ndarray  # int codes into TYPE_ORDER
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def min_elevation(self) -> float:
        return float(self.elevation.min())

    @property
    def max_elevation(self) -> float:
        return float(self.elevation.max())


TYPE_ORDER: tuple[str, ...] = (
    TerrainType.VALLEY.value,
    TerrainType.SNOWFIELD.value,
    TerrainType.GLACIER.value,
    TerrainType.SLOPE.value,
    TerrainType.ICEFALL.value,
    TerrainType.ROCK.value,
    TerrainType.RIDGE.value,
)


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _value_noise(rng: np.random.Generator, height: int, width: int, frequency: int) -> np.ndarray:
    """Bilinearly interpolated value noise on a ``frequency``-cell lattice."""
    gh, gw = max(2, frequency + 1), max(2, frequency + 1)
    lattice = rng.random((gh, gw))

    ys = np.linspace(0, gh - 1, height)
    xs = np.linspace(0, gw - 1, width)
    y0 = np.floor(ys).astype(int).clip(0, gh - 2)
    x0 = np.floor(xs).astype(int).clip(0, gw - 2)
    ty = _smoothstep(ys - y0)[:, None]
    tx = _smoothstep(xs - x0)[None, :]

    v00 = lattice[np.ix_(y0, x0)]
    v01 = lattice[np.ix_(y0, x0 + 1)]
    v10 = lattice[np.ix_(y0 + 1, x0)]
    v11 = lattice[np.ix_(y0 + 1, x0 + 1)]
    top = v00 * (1 - tx) + v01 * tx
    bottom = v10 * (1 - tx) + v11 * tx
    return top * (1 - ty) + bottom * ty


def _fbm(
    rng: np.random.Generator,
    height: int,
    width: int,
    octaves: int = 5,
    base_frequency: int = 3,
    persistence: float = 0.5,
) -> np.ndarray:
    total = np.zeros((height, width))
    amplitude, norm, freq = 1.0, 0.0, base_frequency
    for _ in range(octaves):
        total += amplitude * _value_noise(rng, height, width, freq)
        norm += amplitude
        amplitude *= persistence
        freq *= 2
    return total / max(norm, 1e-9)


def _normalise(a: np.ndarray) -> np.ndarray:
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-9:
        return np.zeros_like(a)
    return (a - lo) / (hi - lo)


def _gradient_magnitude(elevation: np.ndarray, cell_size_m: float) -> np.ndarray:
    gy, gx = np.gradient(elevation, cell_size_m)
    return np.sqrt(gx**2 + gy**2)


def _box_blur(a: np.ndarray, radius: int = 1) -> np.ndarray:
    """Small separable mean filter (avoids a SciPy dependency)."""
    if radius <= 0:
        return a
    padded = np.pad(a, radius, mode="edge")
    out = np.zeros_like(a, dtype=float)
    size = 2 * radius + 1
    for dy in range(size):
        for dx in range(size):
            out += padded[dy : dy + a.shape[0], dx : dx + a.shape[1]]
    return out / (size * size)


def generate_terrain(
    width: int = 64,
    height: int = 64,
    seed: int = 20260909,
    cell_size_m: float = 250.0,
    min_elevation_m: float = 3600.0,
    max_elevation_m: float = 6800.0,
) -> TerrainGrid:
    """Generate a deterministic synthetic high-altitude terrain grid.

    The same ``seed`` always produces the identical grid, which is what makes
    demos and the A* regression tests reproducible.
    """
    if not (8 <= width <= 400 and 8 <= height <= 400):
        raise ValueError("Terrain dimensions must be between 8 and 400 cells.")
    rng = np.random.default_rng(seed)

    # --- Base elevation: ridged fBm produces credible ridge/valley structure.
    base = _fbm(rng, height, width, octaves=6, base_frequency=3, persistence=0.52)
    ridged = 1.0 - np.abs(2.0 * _fbm(rng, height, width, octaves=4, base_frequency=2) - 1.0)
    field_ = _normalise(0.6 * base + 0.4 * ridged**1.4)

    # A gentle valley corridor keeps a traversable low-elevation route so the
    # planner always has a meaningful "safer" alternative to compare.
    yy = np.mgrid[0:height, 0:width][0]
    corridor_centre = (
        height * 0.5 + height * 0.18 * np.sin(np.linspace(0, 2.2 * np.pi, width))[None, :]
    )
    corridor = np.exp(-(((yy - corridor_centre) / (height * 0.11)) ** 2))
    field_ = np.clip(field_ * (1.0 - 0.45 * corridor), 0.0, 1.0)
    field_ = _normalise(_box_blur(field_, 1))

    elevation = min_elevation_m + field_ * (max_elevation_m - min_elevation_m)

    # --- Geometry-derived quantities.
    grad = _gradient_magnitude(elevation, cell_size_m)
    slope = _normalise(grad)
    smoothed = _box_blur(elevation, 2)
    curvature = _normalise(elevation - smoothed)  # >0.5 convex (ridge), <0.5 concave
    elev_norm = _normalise(elevation)

    # --- Avalanche: steep, mid-to-high snow-loaded slopes.
    slab = np.exp(-(((slope - 0.62) / 0.24) ** 2))
    loading = np.clip((elev_norm - 0.25) / 0.55, 0.0, 1.0)
    aval_noise = _fbm(rng, height, width, octaves=3, base_frequency=5)
    avalanche = np.clip(0.86 * slab * loading * (0.55 + 0.75 * aval_noise) + 0.03, 0.0, 1.0)

    # --- Crevasse: glaciated low-slope flats where ice flows.
    flat = np.exp(-((slope / 0.26) ** 2))
    glacial = np.clip((elev_norm - 0.18) / 0.5, 0.0, 1.0) * (1.0 - 0.55 * curvature)
    crev_noise = _fbm(rng, height, width, octaves=4, base_frequency=7)
    crevasse = np.clip(0.9 * flat * glacial * (0.35 + 0.95 * crev_noise) + 0.02, 0.0, 1.0)

    # --- Weather: elevation plus exposure, with drifting fronts.
    front = _fbm(rng, height, width, octaves=3, base_frequency=2)
    weather = np.clip(0.5 * elev_norm + 0.3 * curvature + 0.42 * front - 0.12, 0.0, 1.0)

    # --- Traversal difficulty.
    difficulty = np.clip(
        0.55 * slope + 0.22 * elev_norm + 0.23 * np.maximum(avalanche, crevasse),
        0.0,
        1.0,
    )

    # --- Blocked cells: genuinely impassable extreme terrain (sheer faces).
    blocked = (slope > 0.93) | (
        elevation > min_elevation_m + 0.965 * (max_elevation_m - min_elevation_m)
    )

    # --- Terrain classification.
    codes = np.full((height, width), TYPE_ORDER.index(TerrainType.SLOPE.value), dtype=np.int16)
    codes[(elev_norm < 0.22)] = TYPE_ORDER.index(TerrainType.VALLEY.value)
    codes[(elev_norm >= 0.22) & (slope < 0.3)] = TYPE_ORDER.index(TerrainType.SNOWFIELD.value)
    codes[(crevasse > 0.45) & (slope < 0.4)] = TYPE_ORDER.index(TerrainType.GLACIER.value)
    codes[(crevasse > 0.68)] = TYPE_ORDER.index(TerrainType.ICEFALL.value)
    codes[(slope > 0.72)] = TYPE_ORDER.index(TerrainType.ROCK.value)
    codes[(curvature > 0.78) & (elev_norm > 0.55)] = TYPE_ORDER.index(TerrainType.RIDGE.value)

    # Never block the four corners: guarantees usable start/goal candidates.
    for cy, cx in ((0, 0), (0, width - 1), (height - 1, 0), (height - 1, width - 1)):
        blocked[cy, cx] = False

    return TerrainGrid(
        width=width,
        height=height,
        seed=seed,
        cell_size_m=cell_size_m,
        elevation=elevation,
        slope=slope,
        avalanche=avalanche,
        crevasse=crevasse,
        weather=weather,
        difficulty=difficulty,
        blocked=blocked,
        terrain_type=codes,
        meta={
            "generator_version": GENERATOR_VERSION,
            "is_synthetic": True,
            "blocked_cells": int(blocked.sum()),
            "mean_avalanche": round(float(avalanche.mean()), 4),
            "mean_crevasse": round(float(crevasse.mean()), 4),
            "mean_weather": round(float(weather.mean()), 4),
        },
    )


def type_name(code: int) -> str:
    return TYPE_ORDER[int(code) % len(TYPE_ORDER)]
