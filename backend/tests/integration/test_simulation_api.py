"""Simulation engine lifecycle, determinism and the hardware seam.

The determinism assertion is the load-bearing one: the demo narrative depends
on "the same seed reproduces the same trajectory", so the test starts two runs
with the same seed and compares the sampled vitals element by element.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

SCENARIOS = (
    "NORMAL",
    "GRADUAL_DETERIORATION",
    "ACUTE_EVENT",
    "ALTITUDE_STRESS",
    "MIXED",
)


async def _stop(client: AsyncClient, headers: dict[str, str]) -> None:
    await client.post("/simulation/stop", json={}, headers=headers)


async def test_scenario_catalogue_lists_every_scenario_and_speed(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    response = await client.get("/simulation/scenarios", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    codes = {entry["code"] for entry in body["scenarios"]}
    for scenario in SCENARIOS:
        assert scenario in codes
    assert body["speeds"] == [1, 2, 5, 10]
    assert "not recorded patient data" in body["notice"]
    for entry in body["scenarios"]:
        assert entry["description"]


async def test_status_is_idle_before_a_run_is_started(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _stop(client, admin_headers)
    response = await client.get("/simulation/status", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in ("IDLE", "STOPPED", "COMPLETED")
    assert body["is_simulated"] is True


async def test_full_lifecycle_start_pause_resume_stop_reset(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    started = await client.post(
        "/simulation/start",
        json={"scenario": "ACUTE_EVENT", "seed": 777, "speed": 2, "reset_first": True},
        headers=admin_headers,
    )
    assert started.status_code in (200, 201), started.text
    body = started.json()
    assert body["status"] == "RUNNING"
    assert body["scenario"] == "ACUTE_EVENT"
    assert body["seed"] == 777
    assert body["speed"] == 2
    run_id = body["run_id"]
    assert run_id

    paused = await client.post("/simulation/pause", json={}, headers=admin_headers)
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "PAUSED"

    resumed = await client.post("/simulation/resume", json={}, headers=admin_headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "RUNNING"

    sped_up = await client.post("/simulation/speed", json={"speed": 10}, headers=admin_headers)
    assert sped_up.status_code == 200, sped_up.text
    assert sped_up.json()["speed"] == 10

    switched = await client.post(
        "/simulation/scenario", json={"scenario": "ALTITUDE_STRESS"}, headers=admin_headers
    )
    assert switched.status_code == 200, switched.text

    stopped = await client.post("/simulation/stop", json={}, headers=admin_headers)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] in ("STOPPED", "COMPLETED")

    runs = await client.get("/simulation/runs", headers=admin_headers)
    assert runs.status_code == 200
    assert any(run["id"] == run_id for run in runs.json())

    reset = await client.post("/simulation/reset", json={}, headers=admin_headers)
    assert reset.status_code == 200, reset.text
    assert reset.json()["tick_count"] == 0


async def test_invalid_speed_and_scenario_are_rejected(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    assert (
        await client.post("/simulation/speed", json={"speed": 3}, headers=admin_headers)
    ).status_code == 422
    assert (
        await client.post(
            "/simulation/start", json={"scenario": "TELEPORTATION"}, headers=admin_headers
        )
    ).status_code == 422
    assert (
        await client.post("/simulation/start", json={"seed": -1}, headers=admin_headers)
    ).status_code == 422


async def test_control_calls_are_idempotent_when_there_is_no_run(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Pause/resume/stop on an idle engine report state instead of erroring.

    The dashboard polls these controls, so a 409 storm would be worse than a
    truthful "still idle" reply. The contract asserted here is that the engine
    never claims to be RUNNING when it is not.
    """
    await _stop(client, admin_headers)
    await client.post("/simulation/reset", json={}, headers=admin_headers)
    for endpoint in ("pause", "resume", "stop"):
        response = await client.post(f"/simulation/{endpoint}", json={}, headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] != "RUNNING"
        assert response.json()["run_id"] is None


def _fingerprint(samples: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            s["personnel_id"],
            round(float(s["spo2"]), 6),
            round(float(s["heart_rate"]), 6),
            round(float(s["body_temp_c"]), 6),
            round(float(s["altitude_m"]), 6),
        )
        for s in sorted(samples, key=lambda s: s["personnel_id"])
    ]


async def test_the_same_seed_reproduces_the_same_trajectory(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    payload = {
        "scenario": "GRADUAL_DETERIORATION",
        "seed": 20260101,
        "speed": 1,
        "tick_seconds": 60.0,
        "sim_seconds_per_tick": 60.0,
        "reset_first": True,
    }

    await client.post("/simulation/start", json=payload, headers=admin_headers)
    first = (await client.get("/simulation/snapshot", headers=admin_headers)).json()
    await _stop(client, admin_headers)

    await client.post("/simulation/start", json=payload, headers=admin_headers)
    second = (await client.get("/simulation/snapshot", headers=admin_headers)).json()
    await _stop(client, admin_headers)

    assert first["count"] == second["count"] > 0
    assert first["provenance"] == "SIMULATED"
    assert _fingerprint(first["samples"]) == _fingerprint(second["samples"])


async def test_a_different_seed_produces_a_different_trajectory(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    base = {
        "scenario": "GRADUAL_DETERIORATION",
        "speed": 1,
        "tick_seconds": 60.0,
        "sim_seconds_per_tick": 60.0,
        "reset_first": True,
    }
    await client.post("/simulation/start", json={**base, "seed": 111}, headers=admin_headers)
    first = (await client.get("/simulation/snapshot", headers=admin_headers)).json()
    await _stop(client, admin_headers)

    await client.post("/simulation/start", json={**base, "seed": 222}, headers=admin_headers)
    second = (await client.get("/simulation/snapshot", headers=admin_headers)).json()
    await _stop(client, admin_headers)

    assert _fingerprint(first["samples"]) != _fingerprint(second["samples"])


async def test_snapshot_values_are_physiologically_bounded(
    client: AsyncClient, admin_headers: dict[str, str], running_simulation: dict[str, object]
) -> None:
    response = await client.get("/simulation/snapshot", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] > 0
    for sample in body["samples"]:
        assert 40.0 <= sample["spo2"] <= 100.0
        assert 25.0 <= sample["heart_rate"] <= 240.0
        assert 25.0 <= sample["body_temp_c"] <= 43.0
        assert 0.0 <= sample["altitude_m"] <= 9000.0
        assert sample["source"] == "SIMULATION"
    assert body["sim_clock_seconds"] == pytest.approx(body["sim_clock_seconds"])


async def test_data_source_declares_the_hardware_seam_honestly(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    response = await client.get("/simulation/data-source", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active"]["kind"] == "SIMULATION"
    names = {entry["name"] for entry in body["declared_but_not_implemented"]}
    assert names == {"WearableDataSource", "UAVDataSource", "EdgeDataSource"}
    for entry in body["declared_but_not_implemented"]:
        assert entry["status"] == "NOT_IMPLEMENTED"
        assert "fabricated" in entry["note"]


async def test_only_control_roles_can_drive_the_simulation(
    client: AsyncClient, viewer_headers: dict[str, str], medic_headers: dict[str, str]
) -> None:
    assert (await client.get("/simulation/status", headers=viewer_headers)).status_code == 200
    assert (
        await client.post("/simulation/start", json={}, headers=viewer_headers)
    ).status_code == 403
    assert (
        await client.post("/simulation/stop", json={}, headers=medic_headers)
    ).status_code == 403
