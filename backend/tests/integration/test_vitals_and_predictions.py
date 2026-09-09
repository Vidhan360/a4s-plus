"""Vitals ingestion, the risk pipeline and LSTM prediction + explainability."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personnel import HealthPrediction, VitalReading

pytestmark = pytest.mark.asyncio

BASE_READING = {
    "heart_rate": 92.0,
    "spo2": 93.0,
    "body_temp_c": 36.6,
    "respiratory_rate": 17.0,
    "bp_systolic": 126.0,
    "bp_diastolic": 80.0,
    "altitude_m": 4600.0,
    "fatigue_score": 30.0,
}


def reading(person: str, minutes_ago: int = 0, **overrides: float) -> dict[str, object]:
    body: dict[str, object] = {
        "personnel_id": person,
        "recorded_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
        **BASE_READING,
    }
    body.update(overrides)
    return body


async def seed_series(
    client: AsyncClient, headers: dict[str, str], person: str, count: int
) -> None:
    """Ingest a deteriorating series long enough for the LSTM window."""
    for i in range(count):
        step = count - i
        await client.post(
            "/vitals/ingest",
            json=reading(
                person,
                minutes_ago=step,
                heart_rate=88.0 + i * 1.6,
                spo2=95.0 - i * 0.45,
                respiratory_rate=16.0 + i * 0.35,
                fatigue_score=min(100.0, 25.0 + i * 1.8),
                altitude_m=4500.0 + i * 18,
            ),
            headers=headers,
        )


# ------------------------------------------------------------------ ingestion
async def test_ingest_persists_a_reading_and_derives_risk(
    client: AsyncClient,
    medic_headers: dict[str, str],
    commander_headers: dict[str, str],
    a_person_id: str,
    session: AsyncSession,
    clean_transient: None,
) -> None:
    response = await client.post(
        "/vitals/ingest",
        json=reading(a_person_id, spo2=84.0, heart_rate=132.0),
        headers=medic_headers,
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["reading"]["spo2"] == 84.0
    assert body["risk"]["score"] > 0
    assert body["risk"]["category"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert body["risk"]["top_factors"]

    stored = (
        await session.execute(
            select(func.count())
            .select_from(VitalReading)
            .where(VitalReading.personnel_id == uuid.UUID(a_person_id))
        )
    ).scalar_one()
    assert stored >= 1

    listed = await client.get(
        "/vitals", params={"personnel_id": a_person_id, "limit": 5}, headers=commander_headers
    )
    assert listed.status_code == 200
    assert listed.json()["items"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"spo2": 5.0},
        {"spo2": 140.0},
        {"heart_rate": -10.0},
        {"heart_rate": 900.0},
        {"body_temp_c": 12.0},
        {"altitude_m": 40000.0},
        {"fatigue_score": 500.0},
        {"respiratory_rate": 0.0},
    ],
)
async def test_physiologically_impossible_values_are_rejected(
    client: AsyncClient, medic_headers: dict[str, str], a_person_id: str, overrides: dict
) -> None:
    response = await client.post(
        "/vitals/ingest", json=reading(a_person_id, **overrides), headers=medic_headers
    )
    assert response.status_code == 422, response.text


async def test_ingest_for_an_unknown_person_is_404(
    client: AsyncClient, medic_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/vitals/ingest", json=reading(str(uuid.uuid4())), headers=medic_headers
    )
    assert response.status_code == 404


async def test_manual_ingestion_is_labelled_manual_not_simulated(
    client: AsyncClient, medic_headers: dict[str, str], a_person_id: str, clean_transient: None
) -> None:
    body = (
        await client.post("/vitals/ingest", json=reading(a_person_id), headers=medic_headers)
    ).json()
    assert body["reading"]["source"] == "MANUAL"


# ----------------------------------------------------------------- prediction
async def test_model_catalogue_reports_only_measured_metrics(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    body = (await client.get("/predictions/models", headers=commander_headers)).json()
    models = {m["name"]: m for m in body}
    assert {"rule_baseline", "lstm", "gradient_boosting"} <= set(models)
    for name, model in models.items():
        assert model["data_provenance"]
        if model["available"] and model["metrics"]:
            assert 0.0 <= model["metrics"]["accuracy"] <= 1.0
        if not model["available"]:
            assert model["unavailable_reason"], name


async def test_explanation_methods_are_documented_and_honest(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    body = (await client.get("/predictions/methods", headers=commander_headers)).json()
    assert body["methods"]
    implemented = str(body["methods"]).lower()
    assert "occlusion" in implemented
    # SHAP may only ever be mentioned to state that it is *not* used.
    for entry in body["methods"]:
        description = entry["description"].lower()
        if "shap" in description:
            assert "not shap" in description or "is not shap" in description
    # It is instead explicitly listed as not implemented, with a reason.
    not_implemented = {entry["name"] for entry in body["not_implemented"]}
    assert "SHAP" in not_implemented


async def test_prediction_needs_enough_history_and_says_so(
    client: AsyncClient,
    commander_headers: dict[str, str],
    medic_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    empty = await client.post(f"/predictions/{a_person_id}/run", headers=commander_headers)
    assert empty.status_code == 422
    assert "reading" in empty.json()["error"]["message"].lower()

    # A handful of readings is still not a full LSTM window: the service must
    # fall back to the transparent baseline and say that it did.
    await seed_series(client, medic_headers, a_person_id, 6)
    short = await client.post(
        f"/predictions/{a_person_id}/run", params={"model": "lstm"}, headers=commander_headers
    )
    assert short.status_code == 200
    body = short.json()
    assert body["model_name"] == "rule_baseline"
    assert "NOT from the lstm model" in body["fallback_reason"]


async def test_lstm_prediction_is_real_and_explained_by_occlusion(
    client: AsyncClient,
    commander_headers: dict[str, str],
    medic_headers: dict[str, str],
    a_person_id: str,
    session: AsyncSession,
    clean_transient: None,
) -> None:
    await seed_series(client, medic_headers, a_person_id, 30)
    response = await client.post(
        f"/predictions/{a_person_id}/run",
        params={"model": "lstm", "persist": "true"},
        headers=commander_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_name"] == "lstm"
    assert body["model_version"].startswith("v")
    assert body.get("fallback_reason") is None
    assert 0.0 <= body["risk_probability"] <= 1.0
    assert body["horizon_minutes"] == 30
    assert body["readings_used"] >= 24
    assert body["inference_ms"] > 0

    explanation = body["explanation"]
    assert explanation["method"] == "OCCLUSION_SENSITIVITY"
    assert len(explanation["contributions"]) >= 10
    assert all(
        c["direction"] in ("increases", "decreases", "neutral")
        for c in explanation["contributions"]
    )
    # Contributions are ordered by absolute influence.
    magnitudes = [abs(c["contribution"]) for c in explanation["contributions"]]
    assert magnitudes == sorted(magnitudes, reverse=True)

    persisted = (
        (
            await session.execute(
                select(HealthPrediction).where(
                    HealthPrediction.personnel_id == uuid.UUID(a_person_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(p.model_name == "lstm" for p in persisted)

    history = await client.get(f"/predictions/{a_person_id}/history", headers=commander_headers)
    assert history.status_code == 200
    assert history.json()

    prediction_id = str(persisted[0].id)
    explained = await client.get(f"/predictions/explain/{prediction_id}", headers=commander_headers)
    assert explained.status_code == 200
    assert explained.json()["explanation"]


async def test_lstm_is_the_configured_default_model(
    client: AsyncClient,
    commander_headers: dict[str, str],
    medic_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    await seed_series(client, medic_headers, a_person_id, 30)
    body = (await client.post(f"/predictions/{a_person_id}/run", headers=commander_headers)).json()
    assert body["model_name"] == "lstm"


async def test_model_comparison_runs_every_model_on_the_same_window(
    client: AsyncClient,
    commander_headers: dict[str, str],
    medic_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    await seed_series(client, medic_headers, a_person_id, 30)
    body = (
        await client.get(f"/predictions/{a_person_id}/compare", headers=commander_headers)
    ).json()
    names = {r["model_name"] for r in body["results"]}
    assert {"rule_baseline", "lstm", "gradient_boosting"} <= names
    assert body["readings_used"] >= 24
    for result in body["results"]:
        if result["available"]:
            assert 0.0 <= result["risk_probability"] <= 1.0
            assert result["explanation_method"]


async def test_prediction_is_deterministic_for_the_same_input(
    client: AsyncClient,
    commander_headers: dict[str, str],
    medic_headers: dict[str, str],
    a_person_id: str,
    clean_transient: None,
) -> None:
    await seed_series(client, medic_headers, a_person_id, 30)
    first = (
        await client.post(
            f"/predictions/{a_person_id}/run", params={"model": "lstm"}, headers=commander_headers
        )
    ).json()
    second = (
        await client.post(
            f"/predictions/{a_person_id}/run", params={"model": "lstm"}, headers=commander_headers
        )
    ).json()
    assert first["risk_probability"] == second["risk_probability"]
    assert first["predicted_category"] == second["predicted_category"]


async def test_unknown_model_name_is_rejected(
    client: AsyncClient, commander_headers: dict[str, str], a_person_id: str
) -> None:
    response = await client.post(
        f"/predictions/{a_person_id}/run",
        params={"model": "definitely-not-a-model"},
        headers=commander_headers,
    )
    assert response.status_code in (404, 422)
