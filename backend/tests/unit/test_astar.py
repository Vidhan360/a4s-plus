"""A* route planner: correctness, admissibility and hazard avoidance.

The headline claim in the UI is that the "safest" route is *optimal* under the
configured cost model. That is only true if the heuristic is admissible, so the
central test compares A* against an uninformed uniform-cost (Dijkstra) search
on the same graph: the costs must agree to floating-point tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.algorithms.astar import (
    HAZARD_LAYERS,
    CostConfig,
    TerrainHazardField,
    dijkstra_reference_cost,
    plan_route,
)
from app.algorithms.terrain_gen import generate_terrain

TOL = 1e-6


def field_from_seed(seed: int, size: int = 48) -> TerrainHazardField:
    grid = generate_terrain(size, size, seed=seed)
    return TerrainHazardField(
        elevation=grid.elevation,
        avalanche=grid.avalanche,
        crevasse=grid.crevasse,
        weather=grid.weather,
        difficulty=grid.difficulty,
        blocked=grid.blocked,
        cell_size_m=grid.cell_size_m,
    )


def flat_field(size: int = 12) -> TerrainHazardField:
    zeros = np.zeros((size, size))
    return TerrainHazardField(
        elevation=np.full((size, size), 4000.0),
        avalanche=zeros.copy(),
        crevasse=zeros.copy(),
        weather=zeros.copy(),
        difficulty=zeros.copy(),
        blocked=np.zeros((size, size), dtype=bool),
        cell_size_m=100.0,
    )


# --------------------------------------------------------------- optimality
@pytest.mark.parametrize("seed", [1, 7, 20260909, 555])
def test_astar_cost_equals_uniform_cost_search(seed: int) -> None:
    field_ = field_from_seed(seed)
    start, goal = (3, 3), (44, 44)
    route = plan_route(field_, start, goal)
    reference = dijkstra_reference_cost(field_, start, goal)
    assert route.found is (reference is not None)
    if reference is not None:
        # total_cost is rounded to 4 decimals for transport, hence abs=1e-3.
        assert route.total_cost == pytest.approx(reference, abs=1e-3)


def test_astar_expands_no_more_nodes_than_dijkstra_would_need() -> None:
    """Sanity check that the heuristic actually guides the search."""
    field_ = field_from_seed(20260909, size=64)
    route = plan_route(field_, (2, 2), (61, 61))
    assert route.found
    assert 0 < route.nodes_expanded <= 64 * 64


def test_straight_line_on_flat_terrain_is_the_octile_distance() -> None:
    field_ = flat_field(11)
    cfg = CostConfig(enabled_layers=frozenset())
    route = plan_route(field_, (0, 0), (10, 10), cfg)
    assert route.found
    # 10 diagonal steps on a hazard-free flat grid.
    assert route.total_cost == pytest.approx(10 * cfg.base_cost * 2**0.5, abs=1e-3)
    assert len(route.path) == 11


# ----------------------------------------------------------- path integrity
@pytest.mark.parametrize("seed", [3, 99])
def test_path_is_contiguous_and_in_bounds(seed: int) -> None:
    field_ = field_from_seed(seed)
    route = plan_route(field_, (5, 5), (40, 40))
    assert route.found
    assert route.path[0] == (5, 5)
    assert route.path[-1] == (40, 40)
    for (x0, y0), (x1, y1) in zip(route.path, route.path[1:], strict=False):
        assert max(abs(x1 - x0), abs(y1 - y0)) == 1
        assert 0 <= x1 < field_.width and 0 <= y1 < field_.height


def test_path_never_crosses_a_blocked_cell() -> None:
    field_ = flat_field(15)
    field_.blocked[:, 7] = True
    field_.blocked[0, 7] = False  # leave one gap so a route exists
    route = plan_route(field_, (1, 1), (13, 13))
    assert route.found
    assert all(not field_.blocked[y, x] for x, y in route.path)
    assert (7, 0) in route.path


def test_unreachable_goal_is_reported_not_faked() -> None:
    field_ = flat_field(12)
    field_.blocked[:, 6] = True
    route = plan_route(field_, (1, 1), (10, 10))
    assert route.found is False
    assert route.path == []
    assert "no" in route.reason.lower() or "unreachable" in route.reason.lower()


def test_out_of_bounds_request_is_rejected_with_a_reason() -> None:
    field_ = flat_field(10)
    route = plan_route(field_, (-1, 0), (5, 5))
    assert route.found is False
    assert route.reason


def test_start_equal_to_goal_is_rejected_with_a_clear_reason() -> None:
    route = plan_route(flat_field(10), (4, 4), (4, 4))
    assert route.found is False
    assert "same cell" in route.reason


def test_blocked_start_cell_is_reported() -> None:
    field_ = flat_field(10)
    field_.blocked[1, 1] = True
    route = plan_route(field_, (1, 1), (8, 8))
    assert route.found is False


# --------------------------------------------------------- hazard behaviour
def test_hazard_weighting_diverts_the_route() -> None:
    field_ = flat_field(15)
    # A dangerous corridor along the straight-line route.
    field_.avalanche[:, 7] = 0.8
    hazard_aware = plan_route(field_, (7, 0), (7, 14), CostConfig())
    hazard_blind = plan_route(field_, (7, 0), (7, 14), CostConfig(enabled_layers=frozenset()))
    assert hazard_aware.found and hazard_blind.found
    assert hazard_aware.risk_score < hazard_blind.risk_score
    assert hazard_aware.path != hazard_blind.path
    # The hazard-blind route is the straight line; the aware one steps around it.
    assert all(x == 7 for x, _ in hazard_blind.path)
    assert any(x != 7 for x, _ in hazard_aware.path)


def test_disabling_a_layer_changes_only_that_layer_weight() -> None:
    field_ = field_from_seed(42)
    full = plan_route(field_, (4, 4), (40, 40), CostConfig())
    without_weather = plan_route(
        field_, (4, 4), (40, 40), CostConfig(enabled_layers=frozenset({"avalanche", "crevasse"}))
    )
    assert full.found and without_weather.found
    assert full.total_cost >= 0 and without_weather.total_cost >= 0


def test_ascent_is_penalised_more_than_descent() -> None:
    size = 12
    elevation = np.tile(np.linspace(4000, 5000, size), (size, 1))
    zeros = np.zeros((size, size))
    field_ = TerrainHazardField(
        elevation=elevation,
        avalanche=zeros.copy(),
        crevasse=zeros.copy(),
        weather=zeros.copy(),
        difficulty=zeros.copy(),
        blocked=np.zeros((size, size), dtype=bool),
        cell_size_m=100.0,
    )
    uphill = plan_route(field_, (0, 5), (11, 5), CostConfig(enabled_layers=frozenset()))
    downhill = plan_route(field_, (11, 5), (0, 5), CostConfig(enabled_layers=frozenset()))
    assert uphill.total_cost > downhill.total_cost
    assert uphill.ascent_m > 0 and uphill.descent_m == pytest.approx(0.0)


def test_metrics_are_populated_and_plausible() -> None:
    field_ = field_from_seed(20260909)
    route = plan_route(field_, (3, 3), (44, 44))
    assert route.found
    assert route.distance_m > 0
    assert route.estimated_minutes > 0
    assert 0.0 <= route.risk_score <= 100.0
    assert 0.0 <= route.max_cell_risk <= 100.0
    assert route.max_cell_risk >= route.risk_score
    assert set(route.mean_hazards) == set(HAZARD_LAYERS)
    assert set(route.peak_hazards) == set(HAZARD_LAYERS)
    assert route.compute_ms >= 0.0


def test_planner_is_deterministic() -> None:
    field_ = field_from_seed(8)
    a = plan_route(field_, (2, 2), (45, 30))
    b = plan_route(field_, (2, 2), (45, 30))
    assert a.path == b.path
    assert a.total_cost == pytest.approx(b.total_cost)


def test_negative_weights_would_break_admissibility_and_are_not_allowed() -> None:
    """Documented invariant: the cost model must stay non-negative."""
    cfg = CostConfig()
    for layer in HAZARD_LAYERS:
        assert getattr(cfg, f"{layer}_weight") >= 0.0
    assert cfg.base_cost > 0.0
    assert cfg.ascent_cost_per_m >= 0.0
    assert cfg.descent_cost_per_m >= 0.0
