"""Terrain generator: determinism, bounds and layer sanity.

Reproducibility matters here for two reasons: the demo must look the same every
time it is shown, and the A* optimality regression test needs a fixed map.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.algorithms.terrain_gen import (
    GENERATOR_VERSION,
    TYPE_ORDER,
    generate_terrain,
    type_name,
)

LAYERS = ("slope", "avalanche", "crevasse", "weather", "difficulty")


def test_same_seed_reproduces_every_layer_bit_for_bit() -> None:
    a = generate_terrain(48, 48, seed=4242)
    b = generate_terrain(48, 48, seed=4242)
    assert np.array_equal(a.elevation, b.elevation)
    for layer in LAYERS:
        assert np.array_equal(getattr(a, layer), getattr(b, layer)), layer
    assert np.array_equal(a.blocked, b.blocked)
    assert np.array_equal(a.terrain_type, b.terrain_type)


def test_different_seeds_produce_different_terrain() -> None:
    a = generate_terrain(48, 48, seed=1)
    b = generate_terrain(48, 48, seed=2)
    assert not np.array_equal(a.elevation, b.elevation)


def test_elevation_respects_requested_envelope() -> None:
    grid = generate_terrain(64, 64, seed=7, min_elevation_m=4000.0, max_elevation_m=6000.0)
    assert grid.min_elevation == pytest.approx(4000.0, abs=1.0)
    assert grid.max_elevation == pytest.approx(6000.0, abs=1.0)
    assert grid.elevation.shape == (64, 64)


@pytest.mark.parametrize("layer", LAYERS)
def test_hazard_layers_are_normalised(layer: str) -> None:
    grid = generate_terrain(40, 40, seed=11)
    values = getattr(grid, layer)
    assert values.min() >= 0.0
    assert values.max() <= 1.0
    assert np.isfinite(values).all()


def test_terrain_type_codes_are_all_valid() -> None:
    grid = generate_terrain(64, 64, seed=13)
    codes = np.unique(grid.terrain_type)
    assert codes.min() >= 0
    assert codes.max() < len(TYPE_ORDER)
    for code in codes:
        assert type_name(int(code)) in TYPE_ORDER


def test_map_is_not_mostly_blocked() -> None:
    """A map that is >40% impassable would make routing demos meaningless."""
    grid = generate_terrain(64, 64, seed=20260909)
    blocked_fraction = float(grid.blocked.mean())
    assert 0.0 <= blocked_fraction < 0.40


def test_non_square_dimensions_are_supported() -> None:
    grid = generate_terrain(80, 32, seed=5)
    assert grid.elevation.shape == (32, 80)
    assert grid.width == 80 and grid.height == 32


@pytest.mark.parametrize("size", [(4, 64), (64, 4), (500, 64)])
def test_out_of_range_dimensions_are_rejected(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        generate_terrain(size[0], size[1], seed=1)


def test_generator_records_its_version_for_provenance() -> None:
    grid = generate_terrain(32, 32, seed=3)
    assert grid.meta.get("generator_version") == GENERATOR_VERSION
    assert GENERATOR_VERSION.count(".") == 2
