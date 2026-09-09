"""Live event stream over WebSockets.

These tests are synchronous on purpose: Starlette's ``TestClient`` is the only
supported way to drive a WebSocket route in-process, and it runs the ASGI app
on its own event loop in a worker thread.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

WS_URL = "/api/v1/ws"


@pytest.fixture(scope="module")
def ws_client(seeded: None) -> Iterator[TestClient]:
    with TestClient(create_app(), base_url="http://testserver") as test_client:
        yield test_client


def _login(test_client: TestClient, email: str, password: str) -> str:
    response = test_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["tokens"]["access_token"]
    return token


def _drain_until(websocket: Any, wanted: str, limit: int = 8) -> dict[str, Any]:
    for _ in range(limit):
        message = json.loads(websocket.receive_text())
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"never received a {wanted!r} frame")


def test_connection_without_a_token_is_closed_with_4401(ws_client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect) as error,
        ws_client.websocket_connect(WS_URL) as websocket,
    ):
        websocket.receive_text()
    assert error.value.code == 4401


def test_connection_with_a_garbage_token_is_closed(ws_client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect) as error,
        ws_client.websocket_connect(f"{WS_URL}?token=not.a.jwt") as websocket,
    ):
        websocket.receive_text()
    assert error.value.code == 4401


def test_a_refresh_token_cannot_be_used_to_open_the_stream(ws_client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    from seeds.seed import resolve_seed_passwords

    passwords = resolve_seed_passwords()
    response = ws_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@a4s.local", "password": passwords["admin@a4s.local"]},
    )
    refresh = response.json()["tokens"]["refresh_token"]

    with (
        pytest.raises(WebSocketDisconnect) as error,
        ws_client.websocket_connect(f"{WS_URL}?token={refresh}") as websocket,
    ):
        websocket.receive_text()
    assert error.value.code == 4401


def test_admin_receives_ready_frame_snapshot_and_pong(ws_client: TestClient) -> None:
    from seeds.seed import resolve_seed_passwords

    passwords = resolve_seed_passwords()
    token = _login(ws_client, "admin@a4s.local", passwords["admin@a4s.local"])

    with ws_client.websocket_connect(f"{WS_URL}?token={token}") as websocket:
        ready = json.loads(websocket.receive_text())
        assert ready["type"] == "connection.ready"
        assert ready["is_simulated"] is True
        assert set(ready["topics"]) == {
            "vitals",
            "alerts",
            "drones",
            "security",
            "simulation",
            "dashboard",
        }
        assert ready["user"]["email"] == "admin@a4s.local"
        assert ready["backend"] in ("InMemoryEventBus", "RedisEventBus")

        snapshot = _drain_until(websocket, "snapshot")
        assert snapshot["payload"]["personnel_total"] >= 1

        websocket.send_text(json.dumps({"action": "ping"}))
        assert _drain_until(websocket, "pong")["server_time"]

        websocket.send_text(json.dumps({"action": "snapshot"}))
        assert _drain_until(websocket, "snapshot")["payload"]["disclaimer"]


def test_unknown_action_and_malformed_json_produce_errors(ws_client: TestClient) -> None:
    from seeds.seed import resolve_seed_passwords

    passwords = resolve_seed_passwords()
    token = _login(ws_client, "admin@a4s.local", passwords["admin@a4s.local"])

    with ws_client.websocket_connect(f"{WS_URL}?token={token}") as websocket:
        websocket.send_text("{not json")
        assert "Malformed JSON" in _drain_until(websocket, "error")["message"]

        websocket.send_text(json.dumps({"action": "launch_missile"}))
        assert "Unknown action" in _drain_until(websocket, "error")["message"]


def test_topics_are_filtered_by_permission(ws_client: TestClient) -> None:
    """A medical officer must not be able to subscribe to the security feed."""
    from seeds.seed import resolve_seed_passwords

    passwords = resolve_seed_passwords()
    token = _login(ws_client, "medic@a4s.local", passwords["medic@a4s.local"])

    with ws_client.websocket_connect(
        f"{WS_URL}?token={token}&topics=vitals,security,drones"
    ) as websocket:
        ready = json.loads(websocket.receive_text())
        assert ready["type"] == "connection.ready"
        assert "vitals" in ready["topics"]
        assert "security" not in ready["topics"]


def test_requesting_an_unknown_topic_is_ignored_not_fatal(ws_client: TestClient) -> None:
    from seeds.seed import resolve_seed_passwords

    passwords = resolve_seed_passwords()
    token = _login(ws_client, "admin@a4s.local", passwords["admin@a4s.local"])

    with ws_client.websocket_connect(f"{WS_URL}?token={token}&topics=alerts,wormhole") as ws:
        ready = json.loads(ws.receive_text())
        assert ready["topics"] == ["alerts"]


def test_resubscribe_asks_the_client_to_reconnect(ws_client: TestClient) -> None:
    from seeds.seed import resolve_seed_passwords

    passwords = resolve_seed_passwords()
    token = _login(ws_client, "admin@a4s.local", passwords["admin@a4s.local"])

    with ws_client.websocket_connect(f"{WS_URL}?token={token}&topics=alerts") as websocket:
        json.loads(websocket.receive_text())
        websocket.send_text(json.dumps({"action": "subscribe", "topics": ["vitals"]}))
        subscribed = _drain_until(websocket, "subscribed")
        assert subscribed["topics"] == ["vitals"]
        notice = _drain_until(websocket, "notice")
        assert "Reconnect" in notice["message"]


def test_an_ingested_reading_is_broadcast_to_subscribers(ws_client: TestClient) -> None:
    """End-to-end proof that the event bus actually fans out to clients."""
    from seeds.seed import resolve_seed_passwords

    passwords = resolve_seed_passwords()
    token = _login(ws_client, "admin@a4s.local", passwords["admin@a4s.local"])
    headers = {"Authorization": f"Bearer {token}"}

    roster = ws_client.get("/api/v1/personnel", params={"limit": 1}, headers=headers)
    person_id = roster.json()["items"][0]["id"]

    with ws_client.websocket_connect(f"{WS_URL}?token={token}&topics=vitals") as websocket:
        json.loads(websocket.receive_text())  # connection.ready

        ingest = ws_client.post(
            "/api/v1/vitals/ingest",
            json={
                "personnel_id": person_id,
                "heart_rate": 132.0,
                "spo2": 79.0,
                "body_temp_c": 35.2,
                "respiratory_rate": 28.0,
                "bp_systolic": 148.0,
                "bp_diastolic": 96.0,
                "altitude_m": 5600.0,
                "fatigue_score": 0.8,
                "activity_level": "HEAVY",
                "env_temp_c": -18.0,
                "wind_kph": 40.0,
                "latitude": 34.1,
                "longitude": 77.6,
            },
            headers=headers,
        )
        assert ingest.status_code in (200, 201), ingest.text

        event = _drain_until(websocket, "event", limit=12)
        assert event["topic"] == "vitals"
        assert event["payload"]["personnel_id"] == person_id
