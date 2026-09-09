"""Personnel CRUD, roster, validation, pagination and provenance labelling."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def payload(suffix: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "call_sign": f"TESTCAT-{suffix}",
        "name": "Test Subject",
        "age": 29,
        "unit": "14 Test Bn",
        "rank": "Naik",
        "baseline_heart_rate": 66,
        "baseline_spo2": 96.5,
        "sim_scenario": "NORMAL",
    }
    body.update(overrides)
    return body


async def test_list_is_paginated_with_metadata(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    response = await client.get("/personnel", params={"limit": 5}, headers=commander_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) <= 5
    assert body["meta"]["total"] >= 12
    assert body["meta"]["limit"] == 5
    assert body["meta"]["offset"] == 0


async def test_pagination_offsets_do_not_overlap(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    first = (
        await client.get("/personnel", params={"limit": 4, "offset": 0}, headers=commander_headers)
    ).json()["items"]
    second = (
        await client.get("/personnel", params={"limit": 4, "offset": 4}, headers=commander_headers)
    ).json()["items"]
    assert {p["id"] for p in first}.isdisjoint({p["id"] for p in second})


async def test_search_filters_by_call_sign_name_and_unit(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    everyone = (
        await client.get("/personnel", params={"limit": 100}, headers=commander_headers)
    ).json()["items"]
    target = everyone[0]
    hit = (
        await client.get(
            "/personnel",
            params={"search": target["call_sign"][:5].lower()},
            headers=commander_headers,
        )
    ).json()
    assert hit["meta"]["total"] >= 1
    assert any(p["id"] == target["id"] for p in hit["items"])

    miss = (
        await client.get(
            "/personnel", params={"search": "zzz-no-such-person"}, headers=commander_headers
        )
    ).json()
    assert miss["meta"]["total"] == 0
    assert miss["items"] == []


async def test_roster_summary_reports_counts_and_a_disclaimer(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    body = (await client.get("/personnel/summary/roster", headers=commander_headers)).json()
    assert body["total"] >= 12
    assert "by_status" in body
    assert "by_risk" in body
    assert "SIMULAT" in str(body).upper()


async def test_full_lifecycle_create_read_update_delete(
    client: AsyncClient,
    commander_headers: dict[str, str],
    admin_headers: dict[str, str],
    unique_suffix: str,
) -> None:
    created = await client.post(
        "/personnel", json=payload(unique_suffix), headers=commander_headers
    )
    assert created.status_code == 201, created.text
    person = created.json()
    assert person["call_sign"] == f"TESTCAT-{unique_suffix}".upper()
    assert person["is_simulated"] is True

    fetched = await client.get(f"/personnel/{person['id']}", headers=commander_headers)
    assert fetched.status_code == 200
    detail = fetched.json()
    assert detail["personnel"]["name"] == "Test Subject"
    assert detail["readings"] == []
    assert detail["open_alerts"] == []

    updated = await client.patch(
        f"/personnel/{person['id']}",
        json={"rank": "Havildar", "status": "RESTING"},
        headers=commander_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["rank"] == "Havildar"
    assert updated.json()["status"] == "RESTING"

    # Deletion is a separate, stricter permission than personnel:write.
    assert (
        await client.delete(f"/personnel/{person['id']}", headers=commander_headers)
    ).status_code == 403
    deleted = await client.delete(f"/personnel/{person['id']}", headers=admin_headers)
    assert deleted.status_code in (200, 204)
    assert (
        await client.get(f"/personnel/{person['id']}", headers=commander_headers)
    ).status_code == 404


async def test_duplicate_call_sign_is_a_conflict(
    client: AsyncClient, commander_headers: dict[str, str], unique_suffix: str
) -> None:
    body = payload(unique_suffix)
    first = await client.post("/personnel", json=body, headers=commander_headers)
    assert first.status_code == 201
    clash = await client.post("/personnel", json=body, headers=commander_headers)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "conflict"
    await client.delete(f"/personnel/{first.json()['id']}", headers=commander_headers)


@pytest.mark.parametrize(
    "overrides",
    [
        {"call_sign": "X"},
        {"age": 12},
        {"age": 99},
        {"baseline_spo2": 40},
        {"baseline_heart_rate": 5},
        {"unit": ""},
        {"sim_scenario": "NOT_A_SCENARIO"},
        {"name": ""},
    ],
)
async def test_invalid_payloads_are_rejected_with_422(
    client: AsyncClient,
    commander_headers: dict[str, str],
    unique_suffix: str,
    overrides: dict[str, object],
) -> None:
    response = await client.post(
        "/personnel", json=payload(unique_suffix, **overrides), headers=commander_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]


async def test_unknown_id_is_a_404_and_a_malformed_id_is_a_422(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    missing = await client.get(f"/personnel/{uuid.uuid4()}", headers=commander_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert (await client.get("/personnel/not-a-uuid", headers=commander_headers)).status_code == 422


async def test_twin_is_404_until_a_reading_exists_then_becomes_available(
    client: AsyncClient,
    commander_headers: dict[str, str],
    medic_headers: dict[str, str],
    unique_suffix: str,
    clean_transient: None,
) -> None:
    """A digital twin only exists once there is telemetry to build it from.

    The test creates its own soldier rather than borrowing one from the roster
    so that it cannot be affected by readings another test ingested.
    """
    created = await client.post(
        "/personnel",
        json={
            "call_sign": f"TWIN-{unique_suffix[:6].upper()}",
            "name": "Twin Probe",
            "age": 29,
            "unit": "14 Rajput Rifles",
            "rank": "Rifleman",
        },
        headers=commander_headers,
    )
    assert created.status_code == 201, created.text
    a_person_id = created.json()["id"]

    risk = await client.get(f"/personnel/{a_person_id}/risk", headers=commander_headers)
    assert risk.status_code == 200

    empty = await client.get(f"/personnel/{a_person_id}/twin", headers=commander_headers)
    assert empty.status_code == 404
    assert "reading" in empty.json()["error"]["message"].lower()

    ingested = await client.post(
        "/vitals/ingest",
        json={
            "personnel_id": a_person_id,
            "heart_rate": 118.0,
            "spo2": 86.0,
            "body_temp_c": 36.2,
            "respiratory_rate": 24.0,
            "bp_systolic": 138.0,
            "bp_diastolic": 84.0,
            "altitude_m": 5200.0,
            "fatigue_score": 62.0,
        },
        headers=medic_headers,
    )
    assert ingested.status_code in (200, 201), ingested.text

    twin = await client.get(f"/personnel/{a_person_id}/twin", headers=commander_headers)
    assert twin.status_code == 200
    body = twin.json()
    assert body["personnel_id"] == a_person_id
    assert body["risk_score"] is not None
    assert body["risk_category"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    state = body["state"]
    for key in ("personnel", "vitals", "environment", "location", "risk", "provenance"):
        assert key in state, key
    # A manually recorded observation is honestly labelled as MANUAL, not
    # SIMULATION, and therefore is_simulated is False for this reading.
    assert state["provenance"]["source"] == "MANUAL"
    assert state["provenance"]["is_simulated"] is False
    assert state["vitals"]["spo2"] == 86.0


async def test_vitals_history_endpoint_is_ordered_and_labelled(
    client: AsyncClient, commander_headers: dict[str, str], a_person_id: str
) -> None:
    response = await client.get(
        f"/personnel/{a_person_id}/vitals", params={"limit": 10}, headers=commander_headers
    )
    assert response.status_code == 200
    items = response.json()["items"]
    if items:
        timestamps = [i["recorded_at"] for i in items]
        assert timestamps == sorted(timestamps, reverse=True) or timestamps == sorted(timestamps)
        assert all(i["source"] == "SIMULATION" for i in items)


@pytest.mark.asyncio
async def test_detail_serialises_open_alerts_and_twin_envelope(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Regression: `/personnel/{id}` must return JSON-serialisable alerts.

    The endpoint previously leaked SQLAlchemy ``HealthAlert`` instances into
    the response, which Pydantic refused to serialise and turned into a 500.
    It also returned the raw twin *state* while ``/personnel/{id}/twin``
    returned an enveloped object, so the two disagreed on shape.
    """
    created = await client.post(
        "/personnel",
        headers=admin_headers,
        json={
            "call_sign": "SERIAL-1",
            "name": "Serialisation Check",
            "age": 30,
            "unit": "Test Unit",
            "rank": "Sep",
        },
    )
    assert created.status_code == 201
    person_id = created.json()["id"]

    # Ingest a reading bad enough to raise at least one alert.
    ingest = await client.post(
        "/vitals/ingest",
        headers=admin_headers,
        json={
            "personnel_id": person_id,
            "heart_rate": 178,
            "spo2": 71.0,
            "body_temp_c": 34.4,
            "respiratory_rate": 40,
            "bp_systolic": 165,
            "bp_diastolic": 105,
            "altitude_m": 6800,
            "fatigue_score": 98,
            "activity_level": "HEAVY",
            "env_temp_c": -26.0,
            "wind_kph": 62.0,
        },
    )
    assert ingest.status_code == 201, ingest.text
    assert ingest.json()["alerts"], "expected the alert engine to fire on these vitals"

    detail = await client.get(f"/personnel/{person_id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()

    assert body["open_alerts"], "the freshly raised alert should be listed"
    for alert in body["open_alerts"]:
        assert isinstance(alert, dict)
        assert {"id", "severity", "reason", "recommended_action", "status"} <= alert.keys()

    # Both twin surfaces must agree on the envelope.
    assert body["twin"] is not None
    assert {"personnel_id", "call_sign", "is_stale", "state"} <= body["twin"].keys()
    assert "risk" in body["twin"]["state"]

    twin = await client.get(f"/personnel/{person_id}/twin", headers=admin_headers)
    assert twin.status_code == 200
    assert twin.json().keys() == body["twin"].keys()


@pytest.mark.asyncio
async def test_prediction_narrative_is_prose_not_a_list(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The explainer emits one prose paragraph; the contract must not drift.

    The frontend renders `narrative` as text. If this ever became a list the
    UI would break, so the shape is asserted here rather than discovered in
    the browser.
    """
    roster = await client.get("/personnel", headers=admin_headers, params={"limit": 1})
    assert roster.status_code == 200
    person_id = roster.json()["items"][0]["id"]

    run = await client.post(
        f"/predictions/{person_id}/run",
        headers=admin_headers,
        params={"persist": "false"},
    )
    if run.status_code == 422:
        pytest.skip("not enough history for this person to run a prediction")
    assert run.status_code == 200, run.text
    assert isinstance(run.json()["explanation"]["narrative"], str)


@pytest.mark.asyncio
async def test_route_paths_are_objects_with_x_and_y(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Regression: the planner encodes path nodes as ``{x, y}`` objects."""
    plan = await client.post(
        "/routes/plan",
        headers=admin_headers,
        json={
            "start_x": 4,
            "start_y": 58,
            "goal_x": 56,
            "goal_y": 6,
            "persist": False,
            "compare_shortest": True,
        },
    )
    assert plan.status_code == 201, plan.text
    path = plan.json()["safest"]["path"]
    assert path and all(node.keys() == {"x", "y"} for node in path)
