"""A* safe-route planning over a weighted synthetic terrain grid.

Cost model
----------
Traversing from cell ``a`` to neighbour ``b`` costs::

    step_distance * (base_cost + difficulty_weight * difficulty(b)
                              + avalanche_weight  * avalanche(b)
                              + crevasse_weight   * crevasse(b)
                              + weather_weight    * weather(b))
    + ascent_cost_per_m  * max(0, dz)
    + descent_cost_per_m * max(0, -dz)

Hazard terms are only included for layers the caller has enabled, which is what
makes the hazard toggles in the UI meaningful rather than cosmetic: turning a
layer off genuinely removes it from the objective function and can change the
path.

Admissibility
-------------
The heuristic is octile distance scaled by ``base_cost`` only (the minimum
achievable per-unit-distance cost). Because every hazard weight is
non-negative, the heuristic never overestimates the true remaining cost, so A*
remains admissible and the search returns a cost-optimal path for the given
cost configuration. ``test_astar.py`` asserts this against Dijkstra.
"""

from __future__ import annotations

import heapq
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.defaults import DEFAULT_ROUTE_COSTS

#: 8-connected movement.
NEIGHBOURS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (-1, 0),
    (0, 1),
    (0, -1),
    (1, 1),
    (1, -1),
    (-1, 1),
    (-1, -1),
)

HAZARD_LAYERS: tuple[str, ...] = ("avalanche", "crevasse", "weather", "difficulty")


@dataclass(frozen=True)
class CostConfig:
    """Configurable A* cost model. ``enabled_layers`` drives the UI toggles."""

    base_cost: float = 1.0
    ascent_cost_per_m: float = 0.03
    descent_cost_per_m: float = 0.012
    avalanche_weight: float = 26.0
    crevasse_weight: float = 30.0
    weather_weight: float = 14.0
    difficulty_weight: float = 9.0
    avalanche_block_above: float = 0.85
    crevasse_block_above: float = 0.85
    base_speed_kph: float = 3.2
    difficulty_speed_penalty: float = 0.55
    ascent_minutes_per_100m: float = 9.0
    enabled_layers: frozenset[str] = frozenset(HAZARD_LAYERS)

    @classmethod
    def from_config(
        cls, config: dict[str, Any] | None = None, enabled_layers: Iterable[str] | None = None
    ) -> CostConfig:
        merged = {**DEFAULT_ROUTE_COSTS, **(config or {})}
        layers = (
            frozenset(name for name in enabled_layers if name in HAZARD_LAYERS)
            if enabled_layers is not None
            else frozenset(HAZARD_LAYERS)
        )
        return cls(
            base_cost=float(merged["base_cost"]),
            ascent_cost_per_m=float(merged["ascent_cost_per_m"]),
            descent_cost_per_m=float(merged["descent_cost_per_m"]),
            avalanche_weight=float(merged["avalanche_weight"]),
            crevasse_weight=float(merged["crevasse_weight"]),
            weather_weight=float(merged["weather_weight"]),
            difficulty_weight=float(merged["difficulty_weight"]),
            avalanche_block_above=float(merged["avalanche_block_above"]),
            crevasse_block_above=float(merged["crevasse_block_above"]),
            base_speed_kph=float(merged["base_speed_kph"]),
            difficulty_speed_penalty=float(merged["difficulty_speed_penalty"]),
            ascent_minutes_per_100m=float(merged["ascent_minutes_per_100m"]),
            enabled_layers=layers,
        )

    def shortest_profile(self) -> CostConfig:
        """The same model with every hazard term removed.

        This is the honest "shortest / least-distance" comparison baseline: it
        still respects impassable terrain and terrain-independent climb cost,
        but ignores hazard exposure entirely.
        """
        return CostConfig(
            base_cost=self.base_cost,
            ascent_cost_per_m=self.ascent_cost_per_m,
            descent_cost_per_m=self.descent_cost_per_m,
            avalanche_weight=0.0,
            crevasse_weight=0.0,
            weather_weight=0.0,
            difficulty_weight=0.0,
            avalanche_block_above=1.01,
            crevasse_block_above=1.01,
            base_speed_kph=self.base_speed_kph,
            difficulty_speed_penalty=self.difficulty_speed_penalty,
            ascent_minutes_per_100m=self.ascent_minutes_per_100m,
            enabled_layers=frozenset(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_cost": self.base_cost,
            "ascent_cost_per_m": self.ascent_cost_per_m,
            "descent_cost_per_m": self.descent_cost_per_m,
            "avalanche_weight": self.avalanche_weight,
            "crevasse_weight": self.crevasse_weight,
            "weather_weight": self.weather_weight,
            "difficulty_weight": self.difficulty_weight,
            "avalanche_block_above": self.avalanche_block_above,
            "crevasse_block_above": self.crevasse_block_above,
            "enabled_layers": sorted(self.enabled_layers),
        }


@dataclass
class PlannedRoute:
    """Result of one search, including measured search statistics."""

    found: bool
    path: list[tuple[int, int]] = field(default_factory=list)
    total_cost: float = 0.0
    distance_m: float = 0.0
    ascent_m: float = 0.0
    descent_m: float = 0.0
    estimated_minutes: float = 0.0
    risk_score: float = 0.0
    max_cell_risk: float = 0.0
    mean_hazards: dict[str, float] = field(default_factory=dict)
    peak_hazards: dict[str, float] = field(default_factory=dict)
    nodes_expanded: int = 0
    compute_ms: float = 0.0
    reason: str = ""


class TerrainHazardField:
    """Adapter exposing the hazard layers A* needs from any terrain source.

    Route planning depends only on this shape, never on the generator or the
    database, so a real GIS/DEM provider can be substituted without touching
    the search.
    """

    def __init__(
        self,
        elevation: np.ndarray,
        avalanche: np.ndarray,
        crevasse: np.ndarray,
        weather: np.ndarray,
        difficulty: np.ndarray,
        blocked: np.ndarray,
        cell_size_m: float = 250.0,
    ) -> None:
        self.elevation = np.asarray(elevation, dtype=float)
        self.avalanche = np.asarray(avalanche, dtype=float)
        self.crevasse = np.asarray(crevasse, dtype=float)
        self.weather = np.asarray(weather, dtype=float)
        self.difficulty = np.asarray(difficulty, dtype=float)
        self.blocked = np.asarray(blocked, dtype=bool)
        self.cell_size_m = float(cell_size_m)
        self.height, self.width = self.elevation.shape
        shapes = {
            a.shape
            for a in (
                self.elevation,
                self.avalanche,
                self.crevasse,
                self.weather,
                self.difficulty,
                self.blocked,
            )
        }
        if len(shapes) != 1:
            raise ValueError("All terrain layers must share the same shape.")

    @classmethod
    def from_grid(cls, grid: Any) -> TerrainHazardField:
        return cls(
            elevation=grid.elevation,
            avalanche=grid.avalanche,
            crevasse=grid.crevasse,
            weather=grid.weather,
            difficulty=grid.difficulty,
            blocked=grid.blocked,
            cell_size_m=grid.cell_size_m,
        )

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def layer(self, name: str) -> np.ndarray:
        return getattr(self, name)


def _is_passable(field_: TerrainHazardField, x: int, y: int, cfg: CostConfig) -> bool:
    if field_.blocked[y, x]:
        return False
    if "avalanche" in cfg.enabled_layers and field_.avalanche[y, x] > cfg.avalanche_block_above:
        return False
    if "crevasse" in cfg.enabled_layers and field_.crevasse[y, x] > cfg.crevasse_block_above:
        return False
    return True


def _hazard_multiplier(field_: TerrainHazardField, x: int, y: int, cfg: CostConfig) -> float:
    """Per-unit-distance cost multiplier for entering cell (x, y)."""
    m = cfg.base_cost
    if "difficulty" in cfg.enabled_layers:
        m += cfg.difficulty_weight * field_.difficulty[y, x]
    if "avalanche" in cfg.enabled_layers:
        m += cfg.avalanche_weight * field_.avalanche[y, x]
    if "crevasse" in cfg.enabled_layers:
        m += cfg.crevasse_weight * field_.crevasse[y, x]
    if "weather" in cfg.enabled_layers:
        m += cfg.weather_weight * field_.weather[y, x]
    return m


def _step_cost(
    field_: TerrainHazardField,
    ax: int,
    ay: int,
    bx: int,
    by: int,
    cfg: CostConfig,
) -> float:
    step_cells = math.hypot(bx - ax, by - ay)
    cost = step_cells * _hazard_multiplier(field_, bx, by, cfg)
    dz = float(field_.elevation[by, bx] - field_.elevation[ay, ax])
    cost += cfg.ascent_cost_per_m * max(0.0, dz)
    cost += cfg.descent_cost_per_m * max(0.0, -dz)
    return cost


def _octile(ax: int, ay: int, bx: int, by: int) -> float:
    dx, dy = abs(ax - bx), abs(ay - by)
    return (dx + dy) + (math.sqrt(2.0) - 2.0) * min(dx, dy)


def plan_route(
    field_: TerrainHazardField,
    start: tuple[int, int],
    goal: tuple[int, int],
    cfg: CostConfig | None = None,
) -> PlannedRoute:
    """Run A* from ``start`` to ``goal``. Coordinates are ``(x, y)``."""
    cfg = cfg or CostConfig()
    started = time.perf_counter()
    sx, sy = start
    gx, gy = goal

    for name, (px, py) in (("start", start), ("goal", goal)):
        if not field_.in_bounds(px, py):
            return PlannedRoute(
                found=False,
                reason=f"The {name} cell ({px}, {py}) is outside the terrain grid.",
                compute_ms=(time.perf_counter() - started) * 1000,
            )
    if start == goal:
        return PlannedRoute(
            found=False,
            reason="Start and destination are the same cell.",
            compute_ms=(time.perf_counter() - started) * 1000,
        )
    if not _is_passable(field_, sx, sy, cfg):
        return PlannedRoute(
            found=False,
            reason=(
                "The start cell is impassable under the current hazard settings. "
                "Choose another start cell or disable the blocking hazard layer."
            ),
            compute_ms=(time.perf_counter() - started) * 1000,
        )
    if not _is_passable(field_, gx, gy, cfg):
        return PlannedRoute(
            found=False,
            reason=(
                "The destination cell is impassable under the current hazard "
                "settings. Choose another destination or disable the blocking "
                "hazard layer."
            ),
            compute_ms=(time.perf_counter() - started) * 1000,
        )

    h_scale = cfg.base_cost
    width = field_.width
    start_idx, goal_idx = sy * width + sx, gy * width + gx

    g_score: dict[int, float] = {start_idx: 0.0}
    came_from: dict[int, int] = {}
    closed: set[int] = set()
    heap: list[tuple[float, float, int]] = [(_octile(sx, sy, gx, gy) * h_scale, 0.0, start_idx)]
    nodes_expanded = 0

    while heap:
        _, g_cur, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        closed.add(cur)
        nodes_expanded += 1
        if cur == goal_idx:
            break
        cy, cx = divmod(cur, width)
        for dx, dy in NEIGHBOURS:
            nx, ny = cx + dx, cy + dy
            if not field_.in_bounds(nx, ny):
                continue
            nidx = ny * width + nx
            if nidx in closed or not _is_passable(field_, nx, ny, cfg):
                continue
            # Disallow diagonal moves that would cut a blocked corner.
            if (
                dx != 0
                and dy != 0
                and not _is_passable(field_, cx + dx, cy, cfg)
                and not _is_passable(field_, cx, cy + dy, cfg)
            ):
                continue
            tentative = g_cur + _step_cost(field_, cx, cy, nx, ny, cfg)
            if tentative < g_score.get(nidx, math.inf):
                g_score[nidx] = tentative
                came_from[nidx] = cur
                heapq.heappush(
                    heap,
                    (tentative + _octile(nx, ny, gx, gy) * h_scale, tentative, nidx),
                )

    compute_ms = (time.perf_counter() - started) * 1000
    if goal_idx not in g_score:
        return PlannedRoute(
            found=False,
            nodes_expanded=nodes_expanded,
            compute_ms=compute_ms,
            reason=(
                "No traversable route exists between these points under the "
                "current hazard configuration. Try disabling a hazard layer or "
                "relaxing the blocking thresholds."
            ),
        )

    # Reconstruct.
    path_idx: list[int] = [goal_idx]
    while path_idx[-1] != start_idx:
        path_idx.append(came_from[path_idx[-1]])
    path_idx.reverse()
    path = [(idx % width, idx // width) for idx in path_idx]

    return _summarise(field_, path, g_score[goal_idx], cfg, nodes_expanded, compute_ms)


def _summarise(
    field_: TerrainHazardField,
    path: list[tuple[int, int]],
    total_cost: float,
    cfg: CostConfig,
    nodes_expanded: int,
    compute_ms: float,
) -> PlannedRoute:
    distance_m = 0.0
    ascent = descent = 0.0
    minutes = 0.0
    hazard_sums = dict.fromkeys(HAZARD_LAYERS, 0.0)
    hazard_peaks = dict.fromkeys(HAZARD_LAYERS, 0.0)
    per_cell_risk: list[float] = []

    for i, (x, y) in enumerate(path):
        for layer in HAZARD_LAYERS:
            v = float(field_.layer(layer)[y, x])
            hazard_sums[layer] += v
            hazard_peaks[layer] = max(hazard_peaks[layer], v)
        # Composite exposure risk of this cell, 0..100.
        per_cell_risk.append(
            100.0
            * min(
                1.0,
                0.42 * float(field_.avalanche[y, x])
                + 0.42 * float(field_.crevasse[y, x])
                + 0.16 * float(field_.weather[y, x]),
            )
        )
        if i == 0:
            continue
        px, py = path[i - 1]
        seg_cells = math.hypot(x - px, y - py)
        seg_m = seg_cells * field_.cell_size_m
        distance_m += seg_m
        dz = float(field_.elevation[y, x] - field_.elevation[py, px])
        ascent += max(0.0, dz)
        descent += max(0.0, -dz)
        # Naismith-style time model, slowed by terrain difficulty.
        speed_kph = max(
            0.4,
            cfg.base_speed_kph
            * (1.0 - cfg.difficulty_speed_penalty * float(field_.difficulty[y, x])),
        )
        minutes += (seg_m / 1000.0) / speed_kph * 60.0
        minutes += max(0.0, dz) / 100.0 * cfg.ascent_minutes_per_100m

    n = max(1, len(path))
    return PlannedRoute(
        found=True,
        path=path,
        # Kept at full precision: the optimality check compares this against
        # Dijkstra exactly. Rounding happens only at the transport boundary.
        total_cost=float(total_cost),
        distance_m=round(distance_m, 1),
        ascent_m=round(ascent, 1),
        descent_m=round(descent, 1),
        estimated_minutes=round(minutes, 1),
        risk_score=round(sum(per_cell_risk) / n, 2),
        max_cell_risk=round(max(per_cell_risk) if per_cell_risk else 0.0, 2),
        mean_hazards={k: round(v / n, 4) for k, v in hazard_sums.items()},
        peak_hazards={k: round(v, 4) for k, v in hazard_peaks.items()},
        nodes_expanded=nodes_expanded,
        compute_ms=round(compute_ms, 2),
    )


def dijkstra_reference_cost(
    field_: TerrainHazardField,
    start: tuple[int, int],
    goal: tuple[int, int],
    cfg: CostConfig | None = None,
) -> float | None:
    """Uniform-cost search used by tests to verify A* optimality."""
    cfg = cfg or CostConfig()
    width = field_.width
    sx, sy = start
    gx, gy = goal
    if not _is_passable(field_, sx, sy, cfg) or not _is_passable(field_, gx, gy, cfg):
        return None
    dist: dict[int, float] = {sy * width + sx: 0.0}
    heap: list[tuple[float, int]] = [(0.0, sy * width + sx)]
    seen: set[int] = set()
    goal_idx = gy * width + gx
    while heap:
        d, cur = heapq.heappop(heap)
        if cur in seen:
            continue
        seen.add(cur)
        if cur == goal_idx:
            return d
        cy, cx = divmod(cur, width)
        for dx, dy in NEIGHBOURS:
            nx, ny = cx + dx, cy + dy
            if not field_.in_bounds(nx, ny) or not _is_passable(field_, nx, ny, cfg):
                continue
            if (
                dx != 0
                and dy != 0
                and not _is_passable(field_, cx + dx, cy, cfg)
                and not _is_passable(field_, cx, cy + dy, cfg)
            ):
                continue
            nidx = ny * width + nx
            nd = d + _step_cost(field_, cx, cy, nx, ny, cfg)
            if nd < dist.get(nidx, math.inf):
                dist[nidx] = nd
                heapq.heappush(heap, (nd, nidx))
    return dist.get(goal_idx)
