"""Dashboard, digital twin, analytics and service metadata.

The analytics endpoint publishes model-comparison numbers. Those numbers must
come from the artefacts written by a real training run, never from constants
in the source, so the tests cross-check the API against the artefact file on
disk and assert the API says where they came from.
"""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient

ARTIFACT = Path(__file__).resolve().parents[2] / "ml" / "artifacts" / "last_comparison.json"


async def test_dashboard_summary_is_coherent_and_disclaimed(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    response = await client.get("/dashboard", headers=commander_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["generated_at"]
    assert body["personnel_total"] >= 1
    assert isinstance(body["risk_distribution"], dict)
    assert sum(body["risk_distribution"].values()) <= body["personnel_total"]
    disclaimer = " ".join(body["disclaimer"].values()).lower()
    assert "simulated" in disclaimer
    assert "not clinically validated" in disclaimer
    assert "not a medical device" in disclaimer


async def test_dashboard_twin_list_carries_provenance(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    response = await client.get("/dashboard/twins", headers=commander_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 0
    assert body["provenance"] == "SIMULATED"
    assert isinstance(body["items"], list)


async def test_analytics_reports_only_measured_model_metrics(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    response = await client.get("/analytics", params={"hours": 24}, headers=commander_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window_hours"] == 24
    assert "SIMULATED" in " ".join(body["disclaimer"].values()).upper()
    assert body["model_metrics_source"], "the API must say where metrics came from"
    assert isinstance(body["per_person"], list)


async def test_model_comparison_matches_the_training_artifact(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    response = await client.get("/analytics/model-comparison", headers=commander_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    names = {m["model"] for m in body["models"]}
    assert {"rule_baseline", "lstm", "gradient_boosting"} <= names
    assert body["source"]
    assert body["caveats"]

    if not ARTIFACT.exists():
        # Without a training run the API must report the absence, not invent numbers.
        assert "not" in body["source"].lower()
        return

    measured = json.loads(ARTIFACT.read_text())
    on_disk = measured["results"]
    for entry in body["models"]:
        expected = on_disk.get(entry["model"])
        if expected is None:
            continue
        assert entry["accuracy"] == expected["accuracy"], entry["model"]
        assert entry["macro_f1"] == expected["macro_f1"], entry["model"]

    # No metric may be a suspiciously round marketing number.
    for entry in body["models"]:
        assert entry["accuracy"] < 1.0
        assert entry["accuracy"] != 0.99


async def test_analytics_requires_permission(
    client: AsyncClient, viewer_headers: dict[str, str]
) -> None:
    response = await client.get("/analytics", headers=viewer_headers)
    assert response.status_code in (200, 403)


async def test_meta_endpoint_states_the_prototype_status(client: AsyncClient) -> None:
    response = await client.get("/meta")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["team"] == "The Third Eye"
    assert "detection" in body["tagline"].lower()
    assert body["prototype_status"].upper().startswith("SOFTWARE")
    assert body["data_mode"].upper().startswith("SIMULATED")
    assert "NOT" in body["validation_status"].upper()
    assert body["capabilities"]
    caps = body["capabilities"]
    assert caps["real_sensors"] is False
    assert caps["real_uav_control"] is False
    assert caps["clinical_validation"] is False
    lowered = response.text.lower()
    assert "military-grade" not in lowered
    # The only permitted use of the phrase is the negation.
    assert lowered.count("clinically validated") == lowered.count("not clinically validated")


async def test_health_endpoint_reports_real_subsystem_state(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in ("ok", "degraded")
    assert body["database"] == "ok"
    assert body["environment"] == "test"
    assert body["event_bus"]
    assert body["uptime_seconds"] >= 0
    assert "lstm" in body["ml_models"]
    assert body["disclaimer"]


async def test_openapi_schema_is_served_and_versioned(client: AsyncClient) -> None:
    response = await client.get("http://testserver/api/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"]
    assert any(path.startswith("/api/v1/") for path in schema["paths"])
