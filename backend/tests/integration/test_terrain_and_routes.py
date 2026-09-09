"""Terrain maps and the A* safe-route planner over the HTTP API."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_maps_are_labelled_synthetic(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    maps = (await client.get("/terrain/maps", headers=commander_headers)).json()
    assert maps
    assert all(m["is_synthetic"] is True for m in maps)
    assert any(m["is_default"] for m in maps)
    assert all(m["generator_version"] for m in maps)


async def test_grid_returns_dense_layers_matching_the_declared_size(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    body = (await client.get("/terrain/grid", headers=commander_headers)).json()
    width, height = body["map"]["width"], body["map"]["height"]
    assert width > 0 and height > 0
    for layer in ("elevation", "difficulty", "avalanche", "crevasse", "weather", "blocked"):
        assert len(body[layer]) == height, layer
        assert all(len(row) == width for row in body[layer]), layer
    assert body["is_synthetic"] is True
    assert body["legend"]


async def test_legend_documents_types_and_hazards(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    body = (await client.get("/terrain/legend", headers=commander_headers)).json()
    assert body["types"] and body["hazards"]
    assert "synthetic" in body["notice"].lower()


async def test_cell_lookup_and_out_of_bounds_handling(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    ok = await client.get("/terrain/cell", params={"x": 10, "y": 10}, headers=commander_headers)
    assert ok.status_code == 200
    body = ok.json()
    assert body["elevation_m"] > 0
    assert body["is_synthetic"] is True

    out = await client.get(
        "/terrain/cell", params={"x": 99999, "y": 99999}, headers=commander_headers
    )
    assert out.status_code in (404, 422)


async def test_plan_returns_a_safest_route_and_a_shortest_comparison(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/routes/plan",
        json={
            "name": "Test evacuation lane",
            "start_x": 4,
            "start_y": 4,
            "goal_x": 56,
            "goal_y": 56,
            "compare_shortest": True,
            "persist": True,
        },
        headers=operator_headers,
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    safest = body["safest"]
    assert safest["found"] is True
    assert len(safest["path"]) > 10
    assert safest["distance_m"] > 0
    assert safest["estimated_minutes"] > 0
    assert safest["nodes_expanded"] > 0
    assert safest["explanation"]["summary"]

    shortest = body["shortest"]
    assert shortest["found"] is True
    # The hazard-aware route is never riskier than the hazard-blind one.
    assert safest["risk_score"] <= shortest["risk_score"] + 1e-6
    assert body["comparison"]["delta"]["risk_delta"] <= 1e-6
    assert body["comparison"]["optimality_note"]

    route_id = body["route"]["id"]
    fetched = await client.get(f"/routes/{route_id}", headers=operator_headers)
    assert fetched.status_code == 200
    listed = await client.get("/routes", headers=operator_headers)
    assert any(r["id"] == route_id for r in listed.json()["items"])
    deleted = await client.delete(f"/routes/{route_id}", headers=operator_headers)
    assert deleted.status_code in (200, 204)


async def test_layer_toggles_change_the_plan(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    base = {
        "start_x": 4,
        "start_y": 4,
        "goal_x": 56,
        "goal_y": 56,
        "persist": False,
        "compare_shortest": False,
    }
    all_layers = (
        await client.post(
            "/routes/plan",
            json={**base, "enabled_layers": ["avalanche", "crevasse", "weather", "difficulty"]},
            headers=operator_headers,
        )
    ).json()["safest"]
    avalanche_only = (
        await client.post(
            "/routes/plan", json={**base, "enabled_layers": ["avalanche"]}, headers=operator_headers
        )
    ).json()["safest"]
    assert all_layers["found"] and avalanche_only["found"]
    assert all_layers["total_cost"] != avalanche_only["total_cost"]


async def test_optimality_is_verifiable_through_the_api(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    response = await client.get(
        "/routes/verify-optimality",
        params={"start_x": 6, "start_y": 6, "goal_x": 56, "goal_y": 56},
        headers=operator_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["optimal"] is True
    assert abs(body["astar_cost"] - body["dijkstra_cost"]) < 1e-6
    assert "admissible" in body["interpretation"]


async def test_unreachable_and_invalid_requests_are_reported_clearly(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    invalid = await client.post(
        "/routes/plan",
        json={"start_x": -1, "start_y": 0, "goal_x": 5, "goal_y": 5},
        headers=operator_headers,
    )
    assert invalid.status_code == 422

    missing_map = await client.post(
        "/routes/plan",
        json={"map_id": str(uuid.uuid4()), "start_x": 1, "start_y": 1, "goal_x": 5, "goal_y": 5},
        headers=operator_headers,
    )
    assert missing_map.status_code == 404


async def test_planning_is_deterministic(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    body = {
        "start_x": 8,
        "start_y": 12,
        "goal_x": 50,
        "goal_y": 44,
        "persist": False,
        "compare_shortest": False,
    }
    first = (await client.post("/routes/plan", json=body, headers=operator_headers)).json()
    second = (await client.post("/routes/plan", json=body, headers=operator_headers)).json()
    assert first["safest"]["path"] == second["safest"]["path"]
    assert first["safest"]["total_cost"] == second["safest"]["total_cost"]
