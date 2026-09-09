"""Security monitor, simulated-attack catalogue and the AEAD demonstration.

Two things matter here beyond happy-path plumbing:

* Real security telemetry (failed sign-ins, permission denials) must be
  distinguishable from injected demo events, so the ``origin`` field is
  asserted explicitly.
* The cryptography endpoint is an *authenticated-encryption demonstration*.
  The tests assert the wording never drifts into "military-grade" marketing.
"""

from __future__ import annotations

import base64

from httpx import AsyncClient


async def test_catalogue_separates_real_and_simulated_origins(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/security/catalogue", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    kinds = {entry["kind"] for entry in body["simulated_events"]}
    assert kinds == {"jamming", "spoofing", "intrusion", "suspicious_api"}
    for entry in body["simulated_events"]:
        assert "simulat" in entry["description"].lower()
    assert set(body["origin_semantics"]) == {"REAL", "SIMULATED"}
    assert "No real attack" in body["origin_semantics"]["SIMULATED"]
    assert body["automatic_responses"]


async def test_injected_events_are_marked_simulated(
    client: AsyncClient, admin_headers: dict[str, str], clean_transient: None
) -> None:
    for kind in ("jamming", "spoofing", "intrusion", "suspicious_api"):
        response = await client.post("/security/inject", json={"kind": kind}, headers=admin_headers)
        assert response.status_code == 200, response.text
        event = response.json()
        assert event["origin"] == "SIMULATED"
        assert event["status"] == "NEW"
        assert event["response_action"]


async def test_unknown_injection_kind_is_rejected(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/security/inject", json={"kind": "nuclear_launch"}, headers=admin_headers
    )
    assert response.status_code == 422


async def test_events_can_be_filtered_and_acknowledged(
    client: AsyncClient, admin_headers: dict[str, str], clean_transient: None
) -> None:
    created = await client.post(
        "/security/inject", json={"kind": "intrusion"}, headers=admin_headers
    )
    event_id = created.json()["id"]

    filtered = await client.get(
        "/security/events",
        params={"origin": "SIMULATED", "status": "NEW", "limit": 50},
        headers=admin_headers,
    )
    assert filtered.status_code == 200
    assert any(item["id"] == event_id for item in filtered.json()["items"])

    acknowledged = await client.post(
        f"/security/events/{event_id}/acknowledge",
        json={"note": "Reviewed during rehearsal."},
        headers=admin_headers,
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "MITIGATED"

    missing = await client.post(
        "/security/events/00000000-0000-0000-0000-000000000000/acknowledge",
        json={},
        headers=admin_headers,
    )
    assert missing.status_code == 404


async def test_failed_login_appears_as_a_real_origin_event(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await client.post(
        "/auth/login",
        json={"email": "viewer@a4s.local", "password": "definitely-not-the-password"},
    )
    response = await client.get(
        "/security/events", params={"origin": "REAL", "limit": 50}, headers=admin_headers
    )
    assert response.status_code == 200
    types = {item["event_type"] for item in response.json()["items"]}
    assert "FAILED_LOGIN" in types


async def test_posture_summarises_controls_without_overclaiming(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/security/posture", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["open_events"] >= 0
    assert isinstance(body["by_severity"], dict)
    assert isinstance(body["by_origin"], dict)
    assert body["failed_logins_24h"] >= 0
    assert body["locked_accounts"] >= 0
    assert body["controls"]
    blob = response.text.lower()
    assert "military-grade" not in blob
    assert "military grade" not in blob


async def test_security_settings_expose_the_real_token_policy(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/security/settings", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token_minutes"] >= 1
    assert body["controls"]


async def test_crypto_demo_round_trips_and_detects_tampering(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/security/crypto-demo",
        json={"plaintext": "Casualty evacuation at grid 42,17", "aad": "personnel-record"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["algorithm"] == "AES-256-GCM"
    assert body["key_bits"] == 256
    assert body["nonce_bits"] == 96
    assert body["tag_bytes"] == 16
    assert body["decrypted_matches_input"] is True
    assert body["aad"] == "personnel-record"

    # Ciphertext must actually be ciphertext: it must not contain the plaintext.
    raw = base64.b64decode(body["ciphertext_b64"])
    assert b"Casualty" not in raw
    # GCM ciphertext is plaintext length plus the 16-byte tag.
    assert body["ciphertext_length"] == body["plaintext_length"] + 16

    # Tamper detection is the whole point of an AEAD demonstration.
    assert body["tamper_test"]["detected"] is True

    assert "demonstration" in body["label"].lower()
    lowered = response.text.lower()
    assert "military-grade" not in lowered
    assert "military grade" not in lowered


async def test_crypto_demo_rejects_empty_plaintext(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/security/crypto-demo", json={"plaintext": ""}, headers=admin_headers
    )
    assert response.status_code == 422


async def test_security_read_and_simulate_are_separate_permissions(
    client: AsyncClient,
    viewer_headers: dict[str, str],
    operator_headers: dict[str, str],
    medic_headers: dict[str, str],
) -> None:
    # VIEWER may observe the posture but must not be able to inject events.
    assert (await client.get("/security/posture", headers=viewer_headers)).status_code == 200
    assert (
        await client.post("/security/inject", json={"kind": "intrusion"}, headers=viewer_headers)
    ).status_code == 403
    # OPERATOR runs the demo, so it does hold security:simulate.
    assert (
        await client.post("/security/inject", json={"kind": "intrusion"}, headers=operator_headers)
    ).status_code == 200
    # MEDICAL_OFFICER has no security permissions at all.
    assert (await client.get("/security/posture", headers=medic_headers)).status_code == 403


async def test_invalid_filter_values_are_rejected(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    for params in (
        {"severity": "APOCALYPTIC"},
        {"origin": "MAGIC"},
        {"status": "OPEN"},
        {"event_type": "NOT_A_TYPE"},
    ):
        response = await client.get("/security/events", params=params, headers=admin_headers)
        assert response.status_code == 422, f"{params} -> {response.status_code}"
