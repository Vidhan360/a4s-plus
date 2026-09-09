"""Safe-route planning: A* search, shortest-path comparison and persistence."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.astar import (
    HAZARD_LAYERS,
    CostConfig,
    PlannedRoute,
    dijkstra_reference_cost,
    plan_route,
)
from app.core.errors import NotFoundError, ValidationError
from app.models.terrain import Route, RouteCalculation, TerrainMap
from app.repositories import terrain as terrain_repo
from app.services.alert_engine import AlertEngine
from app.services.config_service import config_service
from app.services.terrain_service import terrain_service

#: Above this mean-hazard exposure a planned route raises a hazard alert.
# Route risk metrics are reported on a 0..100 scale (see astar._summarise).
HAZARD_ALERT_THRESHOLD = 45.0
PEAK_CELL_ALERT_THRESHOLD = 75.0


def _explanation(
    safest: PlannedRoute,
    shortest: PlannedRoute | None,
    cfg: CostConfig,
) -> dict[str, Any]:
    """Human-readable justification of the chosen path.

    Every number here is measured from the two searches — nothing is asserted
    that the planner did not actually compute.
    """
    lines: list[str] = []
    layers = sorted(cfg.enabled_layers)
    lines.append(
        "A* minimised a weighted cost of distance, climb and hazard exposure "
        f"over {'no hazard layers' if not layers else ', '.join(layers)}."
    )
    if safest.found:
        lines.append(
            f"Chosen path: {len(safest.path)} cells, {safest.distance_m / 1000:.2f} km, "
            f"+{safest.ascent_m:.0f} m ascent, mean hazard exposure "
            f"{safest.risk_score:.1f}/100, peak cell hazard "
            f"{safest.max_cell_risk:.1f}/100."
        )
        lines.append(
            f"Search expanded {safest.nodes_expanded} nodes in {safest.compute_ms:.1f} ms."
        )
    else:
        lines.append(f"No route found: {safest.reason}")

    delta: dict[str, Any] = {}
    if shortest is not None and shortest.found and safest.found:
        delta = {
            "distance_delta_m": round(safest.distance_m - shortest.distance_m, 1),
            "distance_delta_pct": (
                round(100.0 * (safest.distance_m - shortest.distance_m) / shortest.distance_m, 2)
                if shortest.distance_m
                else 0.0
            ),
            "risk_delta": round(safest.risk_score - shortest.risk_score, 4),
            "peak_risk_delta": round(safest.max_cell_risk - shortest.max_cell_risk, 4),
            "minutes_delta": round(safest.estimated_minutes - shortest.estimated_minutes, 1),
        }
        if delta["risk_delta"] < 0:
            lines.append(
                f"Compared with the shortest path, hazard exposure is "
                f"{abs(delta['risk_delta']):.3f} lower "
                f"({abs(delta['risk_delta']) / max(shortest.risk_score, 1e-9) * 100:.0f}%"
                f" reduction) "
                f"for {delta['distance_delta_m'] / 1000:+.2f} km of extra distance."
            )
        elif delta["risk_delta"] == 0:
            lines.append(
                "The safest and shortest paths coincide: no lower-hazard "
                "alternative exists under the current weights."
            )
        else:
            lines.append(
                "The hazard-weighted path is not lower-exposure than the shortest "
                "path here, which happens when hazards are uniform along every "
                "corridor between these points."
            )
    return {
        "summary": lines,
        "enabled_layers": layers,
        "weights": cfg.as_dict(),
        "delta_vs_shortest": delta,
        "hazard_profile": {
            "mean": safest.mean_hazards,
            "peak": safest.peak_hazards,
        },
        "time_model": (
            "Naismith-style estimate: horizontal speed reduced by traverse "
            "difficulty plus a fixed penalty per 100 m of ascent."
        ),
        "terrain_provenance": "SYNTHETIC_PROCEDURAL_TERRAIN",
    }


def _calc_row(
    route_id: uuid.UUID,
    profile: str,
    result: PlannedRoute,
    cfg: CostConfig,
    explanation: dict[str, Any],
    created_by_id: uuid.UUID | None,
) -> RouteCalculation:
    return RouteCalculation(
        id=uuid.uuid4(),
        route_id=route_id,
        profile=profile,
        cost_config=cfg.as_dict(),
        path=[{"x": x, "y": y} for x, y in result.path],
        found=result.found,
        distance_m=round(result.distance_m, 2),
        ascent_m=round(result.ascent_m, 2),
        descent_m=round(result.descent_m, 2),
        estimated_minutes=round(result.estimated_minutes, 2),
        total_cost=round(result.total_cost, 6),
        risk_score=round(result.risk_score, 5),
        max_cell_risk=round(result.max_cell_risk, 5),
        avoided_hazards={
            "mean": result.mean_hazards,
            "peak": result.peak_hazards,
            "layers": sorted(cfg.enabled_layers),
        },
        nodes_expanded=result.nodes_expanded,
        compute_ms=round(result.compute_ms, 3),
        explanation=explanation,
        created_by_id=created_by_id,
    )


def _ephemeral_payload(
    profile: str, result: PlannedRoute, cfg: CostConfig, explanation: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": None,
        "route_id": None,
        "profile": profile,
        "cost_config": cfg.as_dict(),
        "path": [{"x": x, "y": y} for x, y in result.path],
        "found": result.found,
        "distance_m": round(result.distance_m, 2),
        "ascent_m": round(result.ascent_m, 2),
        "descent_m": round(result.descent_m, 2),
        "estimated_minutes": round(result.estimated_minutes, 2),
        "total_cost": round(result.total_cost, 6),
        "risk_score": round(result.risk_score, 5),
        "max_cell_risk": round(result.max_cell_risk, 5),
        "avoided_hazards": {
            "mean": result.mean_hazards,
            "peak": result.peak_hazards,
            "layers": sorted(cfg.enabled_layers),
        },
        "nodes_expanded": result.nodes_expanded,
        "compute_ms": round(result.compute_ms, 3),
        "explanation": explanation,
        "created_at": None,
    }


class RouteService:
    def __init__(self, alert_engine: AlertEngine | None = None) -> None:
        self._alerts = alert_engine

    async def _engine(self, session: AsyncSession) -> AlertEngine:
        if self._alerts is not None:
            return self._alerts
        return AlertEngine(await config_service.alert_rules(session))

    async def plan(
        self,
        session: AsyncSession,
        *,
        map_id: uuid.UUID | None,
        name: str,
        start: tuple[int, int],
        goal: tuple[int, int],
        enabled_layers: list[str] | None = None,
        compare_shortest: bool = True,
        persist: bool = True,
        notes: str | None = None,
        created_by_id: uuid.UUID | None = None,
        raise_alerts: bool = True,
    ) -> dict[str, Any]:
        terrain_map = await terrain_service.require_map(session, map_id)
        layers = await terrain_repo.load_layers(session, terrain_map)
        field = layers.hazard_field()

        for label, (x, y) in (("start", start), ("goal", goal)):
            if not field.in_bounds(x, y):
                raise ValidationError(
                    f"{label} cell ({x}, {y}) is outside the {terrain_map.width}x"
                    f"{terrain_map.height} map."
                )

        costs = await config_service.route_costs(session)
        cfg = CostConfig.from_config(
            costs, enabled_layers=enabled_layers if enabled_layers is not None else HAZARD_LAYERS
        )
        safest = plan_route(field, start, goal, cfg)

        shortest = None
        if compare_shortest:
            shortest = plan_route(field, start, goal, cfg.shortest_profile())

        explanation = _explanation(safest, shortest, cfg)

        route: Route | None = None
        safest_payload: Any
        shortest_payload: Any = None
        if persist:
            route = Route(
                id=uuid.uuid4(),
                map_id=terrain_map.id,
                name=name,
                start_x=start[0],
                start_y=start[1],
                goal_x=goal[0],
                goal_y=goal[1],
                notes=notes,
                created_by_id=created_by_id,
            )
            session.add(route)
            await session.flush()
            safest_row = _calc_row(route.id, "SAFEST", safest, cfg, explanation, created_by_id)
            session.add(safest_row)
            safest_payload = safest_row
            if shortest is not None:
                shortest_row = _calc_row(
                    route.id,
                    "SHORTEST",
                    shortest,
                    cfg.shortest_profile(),
                    {"summary": ["Hazard-free reference path for comparison."]},
                    created_by_id,
                )
                session.add(shortest_row)
                shortest_payload = shortest_row
            await session.flush()
        else:
            safest_payload = _ephemeral_payload("SAFEST", safest, cfg, explanation)
            if shortest is not None:
                shortest_payload = _ephemeral_payload(
                    "SHORTEST",
                    shortest,
                    cfg.shortest_profile(),
                    {"summary": ["Hazard-free reference path for comparison."]},
                )

        hazard_alerts: list[dict[str, Any]] = []
        if (
            raise_alerts
            and safest.found
            and route is not None
            and (
                safest.risk_score >= HAZARD_ALERT_THRESHOLD
                or safest.max_cell_risk >= PEAK_CELL_ALERT_THRESHOLD
            )
        ):
            engine = await self._engine(session)
            candidates = engine.from_route_hazard(name, safest_payload, route.id)
            for candidate in candidates:
                outcome = await engine.submit(session, candidate)
                hazard_alerts.append(
                    {
                        "action": outcome.action,
                        "alert_id": str(outcome.alert.id) if outcome.alert else None,
                        "title": candidate.title,
                        "severity": candidate.severity.value,
                    }
                )

        if route is not None:
            # Eager-load the relationship while we are still inside the async
            # greenlet context; serialisation happens in the router layer.
            await session.refresh(route, ["calculations"])

        return {
            "route": route,
            "safest": safest_payload,
            "shortest": shortest_payload,
            "comparison": {
                "profiles": ["SAFEST"] + (["SHORTEST"] if shortest is not None else []),
                "delta": explanation["delta_vs_shortest"],
                "optimality_note": (
                    "A* uses an admissible octile-distance heuristic scaled by the "
                    "minimum per-cell cost, so the returned path is cost-optimal for "
                    "the configured weights. tests/test_astar.py asserts equality "
                    "with an uninformed Dijkstra search."
                ),
            },
            "hazard_alerts": hazard_alerts,
            "is_synthetic_terrain": True,
            "terrain_map": terrain_map,
        }

    async def verify_optimality(
        self,
        session: AsyncSession,
        *,
        map_id: uuid.UUID | None,
        start: tuple[int, int],
        goal: tuple[int, int],
    ) -> dict[str, Any]:
        """Measured A*-vs-Dijkstra check, exposed for the demo."""
        terrain_map: TerrainMap = await terrain_service.require_map(session, map_id)
        layers = await terrain_repo.load_layers(session, terrain_map)
        field = layers.hazard_field()
        costs = await config_service.route_costs(session)
        cfg = CostConfig.from_config(costs)
        astar_result = plan_route(field, start, goal, cfg)
        reference = dijkstra_reference_cost(field, start, goal, cfg)
        matches = (
            reference is not None
            and astar_result.found
            and abs(astar_result.total_cost - reference) < 1e-6
        )
        return {
            "astar_cost": round(astar_result.total_cost, 6),
            "dijkstra_cost": None if reference is None else round(reference, 6),
            "optimal": bool(matches),
            "nodes_expanded_astar": astar_result.nodes_expanded,
            "compute_ms_astar": round(astar_result.compute_ms, 3),
        }

    async def get_route(self, session: AsyncSession, route_id: uuid.UUID) -> Route:
        route = await terrain_repo.get_route(session, route_id)
        if route is None:
            raise NotFoundError("Route not found.")
        return route

    async def delete_route(self, session: AsyncSession, route_id: uuid.UUID) -> None:
        route = await self.get_route(session, route_id)
        await session.delete(route)
        await session.flush()


route_service = RouteService()
