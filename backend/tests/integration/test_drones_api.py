"""UAV swarm simulation API.

Every assertion here is about *simulated* aircraft. The suite deliberately
checks that the API keeps saying so, because an operator reading the response
must never mistake it for real flight control.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_swarm_status_is_labelled_as_simulated(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    response = await client.get("/drones", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_simulated"] is True
    assert "does not command real aircraft" in body["notice"]
    assert body["formation"] in ("LINE", "WEDGE", "COLUMN", "DIAMOND")
    assert len(body["drones"]) >= 1
    for drone in body["drones"]:
        assert drone["is_simulated"] is True
        assert 0.0 <= drone["battery_pct"] <= 100.0
        assert drone["status"] in ("ACTIVE", "RETURNING", "OFFLINE", "JAMMED", "ALERT")
    assert sum(body["counts"].values()) >= len(body["drones"])


async def test_single_drone_lookup_and_unknown_id(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    listing = await client.get("/drones", headers=operator_headers)
    drone_id = listing.json()["drones"][0]["id"]

    found = await client.get(f"/drones/{drone_id}", headers=operator_headers)
    assert found.status_code == 200
    assert found.json()["id"] == drone_id

    missing = await client.get(
        "/drones/00000000-0000-0000-0000-000000000000", headers=operator_headers
    )
    assert missing.status_code == 404


async def test_every_advertised_command_is_accepted(
    client: AsyncClient, operator_headers: dict[str, str], running_simulation: dict[str, object]
) -> None:
    """Regression test: the schema advertised commands the engine rejected."""
    listing = await client.get("/drones", headers=operator_headers)
    drone_id = listing.json()["drones"][0]["id"]

    for action in ("HOLD", "RTB", "RESUME", "LAND", "LAUNCH"):
        response = await client.post(
            f"/drones/{drone_id}/command",
            json={"action": action},
            headers=operator_headers,
        )
        assert response.status_code == 200, f"{action}: {response.text}"
        body = response.json()
        assert body["command"] == action
        assert body["accepted"] is True, f"{action} produced no events"
        assert "No real aircraft" in body["notice"]

    await client.post(
        f"/drones/{drone_id}/command", json={"action": "RESUME"}, headers=operator_headers
    )


async def test_unsupported_command_is_rejected(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    listing = await client.get("/drones", headers=operator_headers)
    drone_id = listing.json()["drones"][0]["id"]
    response = await client.post(
        f"/drones/{drone_id}/command", json={"action": "SELF_DESTRUCT"}, headers=operator_headers
    )
    assert response.status_code == 422
    assert "Supported" in response.text


async def test_formation_change_and_validation(
    client: AsyncClient, operator_headers: dict[str, str], running_simulation: dict[str, object]
) -> None:
    ok = await client.post(
        "/drones/formation", json={"formation": "diamond"}, headers=operator_headers
    )
    assert ok.status_code == 200, ok.text

    status = await client.get("/drones", headers=operator_headers)
    assert status.json()["formation"] == "DIAMOND"

    bad = await client.post(
        "/drones/formation", json={"formation": "SPIRAL"}, headers=operator_headers
    )
    assert bad.status_code == 422

    await client.post("/drones/formation", json={"formation": "WEDGE"}, headers=operator_headers)


async def test_jamming_injection_degrades_link_and_raises_security_event(
    client: AsyncClient,
    operator_headers: dict[str, str],
    admin_headers: dict[str, str],
    running_simulation: dict[str, object],
) -> None:
    listing = await client.get("/drones", headers=operator_headers)
    drone_id = listing.json()["drones"][0]["id"]

    response = await client.post(
        "/drones/inject/jamming",
        json={"drone_id": drone_id, "duration_seconds": 120},
        headers=operator_headers,
    )
    assert response.status_code == 200, response.text

    drone = (await client.get(f"/drones/{drone_id}", headers=operator_headers)).json()
    assert drone["under_jamming"] is True

    events = await client.get("/security/events", params={"limit": 50}, headers=admin_headers)
    kinds = {event["event_type"] for event in events.json()["items"]}
    assert "SIMULATED_JAMMING" in kinds


async def test_spoofing_injection_creates_a_position_discrepancy(
    client: AsyncClient, operator_headers: dict[str, str], running_simulation: dict[str, object]
) -> None:
    listing = await client.get("/drones", headers=operator_headers)
    drones = listing.json()["drones"]
    drone_id = drones[1]["id"] if len(drones) > 1 else drones[0]["id"]

    response = await client.post(
        "/drones/inject/spoofing",
        json={"drone_id": drone_id, "duration_seconds": 120},
        headers=operator_headers,
    )
    assert response.status_code == 200, response.text

    drone = (await client.get(f"/drones/{drone_id}", headers=operator_headers)).json()
    assert drone["under_spoofing"] is True
    assert drone["reported_grid_x"] is not None
    delta = abs(drone["reported_grid_x"] - drone["grid_x"]) + abs(
        drone["reported_grid_y"] - drone["grid_y"]
    )
    assert delta > 0.0


async def test_events_and_missions_are_listed(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    events = await client.get("/drones/events", params={"limit": 5}, headers=operator_headers)
    assert events.status_code == 200
    assert isinstance(events.json(), list)

    missions = await client.get("/drones/missions", headers=operator_headers)
    assert missions.status_code == 200
    assert isinstance(missions.json(), list)


async def test_viewer_cannot_command_drones(
    client: AsyncClient, viewer_headers: dict[str, str], operator_headers: dict[str, str]
) -> None:
    listing = await client.get("/drones", headers=operator_headers)
    drone_id = listing.json()["drones"][0]["id"]
    response = await client.post(
        f"/drones/{drone_id}/command", json={"action": "HOLD"}, headers=viewer_headers
    )
    assert response.status_code == 403
