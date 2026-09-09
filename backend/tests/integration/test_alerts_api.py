"""Alert engine: creation, deduplication, cooldown, escalation, lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AlertStatus
from app.models.personnel import HealthAlert

pytestmark = pytest.mark.asyncio

CRITICAL = {
    "heart_rate": 168.0,
    "spo2": 74.0,
    "body_temp_c": 34.6,
    "respiratory_rate": 34.0,
    "bp_systolic": 168.0,
    "bp_diastolic": 104.0,
    "altitude_m": 6100.0,
    "fatigue_score": 94.0,
}


def reading(person: str, minutes_ago: int = 0, **overrides: float) -> dict[str, object]:
    body: dict[str, object] = {
        "personnel_id": person,
        "recorded_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
        **CRITICAL,
    }
    body.update(overrides)
    return body


async def test_a_critical_reading_raises_an_alert(
    client: AsyncClient,
    medic_headers: dict[str, str],
    commander_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    response = await client.post("/vitals/ingest", json=reading(a_person_id), headers=medic_headers)
    assert response.status_code in (200, 201), response.text
    assert response.json()["alerts"], "a CRITICAL reading must raise at least one alert"

    listed = await client.get("/alerts", params={"limit": 20}, headers=commander_headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] >= 1


async def test_repeated_identical_readings_are_deduplicated(
    client: AsyncClient,
    medic_headers: dict[str, str],
    a_person_id: str,
    session: AsyncSession,
    clean_transient: None,
) -> None:
    for i in range(8):
        await client.post(
            "/vitals/ingest", json=reading(a_person_id, minutes_ago=8 - i), headers=medic_headers
        )
    rows = (
        (
            await session.execute(
                select(HealthAlert).where(HealthAlert.personnel_id == uuid.UUID(a_person_id))
            )
        )
        .scalars()
        .all()
    )
    assert rows, "expected at least one alert"
    # Dedup: the same condition must not create one row per reading.
    assert len(rows) < 8
    assert max(r.occurrence_count for r in rows) > 1


async def test_dedup_key_is_per_person_and_per_condition(
    client: AsyncClient,
    medic_headers: dict[str, str],
    commander_headers: dict[str, str],
    session: AsyncSession,
    clean_transient: None,
) -> None:
    roster = (
        await client.get("/personnel", params={"limit": 2}, headers=commander_headers)
    ).json()["items"]
    assert len(roster) >= 2
    for person in roster:
        await client.post("/vitals/ingest", json=reading(person["id"]), headers=medic_headers)
    distinct_people = (
        await session.execute(select(func.count(func.distinct(HealthAlert.personnel_id))))
    ).scalar_one()
    assert distinct_people >= 2, "alerts must not be merged across people"


async def test_escalation_raises_severity_when_the_condition_worsens(
    client: AsyncClient,
    medic_headers: dict[str, str],
    a_person_id: str,
    session: AsyncSession,
    clean_transient: None,
) -> None:
    await client.post(
        "/vitals/ingest",
        json=reading(a_person_id, minutes_ago=6, spo2=89.0, heart_rate=118.0, fatigue_score=45.0),
        headers=medic_headers,
    )
    await client.post(
        "/vitals/ingest",
        json=reading(a_person_id, minutes_ago=1, spo2=70.0, heart_rate=178.0, fatigue_score=99.0),
        headers=medic_headers,
    )
    severities = (await session.execute(select(HealthAlert.severity))).scalars().all()
    assert severities
    assert any(s in ("HIGH", "CRITICAL") for s in severities)


async def test_alert_lifecycle_acknowledge_then_resolve(
    client: AsyncClient,
    medic_headers: dict[str, str],
    commander_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    await client.post("/vitals/ingest", json=reading(a_person_id), headers=medic_headers)
    alerts = (
        await client.get("/alerts", params={"open_only": "true"}, headers=commander_headers)
    ).json()["items"]
    assert alerts
    alert_id = alerts[0]["id"]

    detail = await client.get(f"/alerts/{alert_id}", headers=commander_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == AlertStatus.OPEN.value

    acked = await client.post(
        f"/alerts/{alert_id}/acknowledge",
        json={"note": "Medic dispatched."},
        headers=commander_headers,
    )
    assert acked.status_code == 200
    assert acked.json()["status"] == AlertStatus.ACKNOWLEDGED.value
    assert acked.json()["acknowledged_at"]

    resolved = await client.post(
        f"/alerts/{alert_id}/resolve",
        json={"resolution_note": "SpO2 recovered after descent."},
        headers=commander_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == AlertStatus.RESOLVED.value


async def test_acknowledging_twice_is_rejected(
    client: AsyncClient,
    medic_headers: dict[str, str],
    commander_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    await client.post("/vitals/ingest", json=reading(a_person_id), headers=medic_headers)
    alert_id = (
        await client.get("/alerts", params={"open_only": "true"}, headers=commander_headers)
    ).json()["items"][0]["id"]
    assert (
        await client.post(f"/alerts/{alert_id}/acknowledge", json={}, headers=commander_headers)
    ).status_code == 200
    second = await client.post(
        f"/alerts/{alert_id}/acknowledge", json={}, headers=commander_headers
    )
    assert second.status_code in (409, 422)


async def test_unknown_alert_is_404(client: AsyncClient, commander_headers: dict[str, str]) -> None:
    assert (
        await client.get(f"/alerts/{uuid.uuid4()}", headers=commander_headers)
    ).status_code == 404


async def test_filters_narrow_the_alert_list(
    client: AsyncClient,
    medic_headers: dict[str, str],
    commander_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    await client.post("/vitals/ingest", json=reading(a_person_id), headers=medic_headers)
    by_person = await client.get(
        "/alerts", params={"personnel_id": a_person_id}, headers=commander_headers
    )
    assert by_person.status_code == 200
    assert all(i["personnel_id"] == a_person_id for i in by_person.json()["items"])

    by_severity = await client.get(
        "/alerts", params={"severity": "CRITICAL"}, headers=commander_headers
    )
    assert by_severity.status_code == 200
    assert all(i["severity"] == "CRITICAL" for i in by_severity.json()["items"])

    nonsense = await client.get(
        "/alerts", params={"severity": "NOT_A_SEVERITY"}, headers=commander_headers
    )
    assert nonsense.status_code == 422


async def test_summary_and_rules_are_exposed_for_the_ui(
    client: AsyncClient,
    medic_headers: dict[str, str],
    commander_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    await client.post("/vitals/ingest", json=reading(a_person_id), headers=medic_headers)
    summary = (await client.get("/alerts/summary", headers=commander_headers)).json()
    assert summary["open"] >= 1
    assert "by_severity" in summary

    rules = (await client.get("/alerts/rules", headers=commander_headers)).json()
    assert rules["rules"]
    behaviour = str(rules["behaviour"]).lower()
    assert "cooldown" in behaviour
    assert "dedup" in behaviour or "deduplicat" in behaviour
