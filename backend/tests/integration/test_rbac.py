"""Role-based access control: the full matrix is asserted, not sampled.

Every (role, endpoint) pair below is exercised against the live app. A role
must receive 200/2xx exactly when it holds the endpoint's permission and 403
otherwise — with a machine-readable body naming the missing permission.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.permissions import ROLE_PERMISSIONS, Perm, Role

pytestmark = pytest.mark.asyncio

#: (method, path, required permission)
GUARDED_ENDPOINTS: list[tuple[str, str, Perm]] = [
    ("GET", "/dashboard", Perm.DASHBOARD_READ),
    ("GET", "/dashboard/twins", Perm.TWIN_READ),
    ("GET", "/personnel", Perm.PERSONNEL_READ),
    ("GET", "/personnel/summary/roster", Perm.PERSONNEL_READ),
    ("GET", "/vitals", Perm.VITALS_READ),
    ("GET", "/alerts", Perm.ALERT_READ),
    ("GET", "/alerts/summary", Perm.ALERT_READ),
    ("GET", "/alerts/rules", Perm.ALERT_READ),
    ("GET", "/predictions/models", Perm.PREDICTION_READ),
    ("GET", "/predictions/methods", Perm.PREDICTION_READ),
    ("GET", "/terrain/maps", Perm.TERRAIN_READ),
    ("GET", "/terrain/grid", Perm.TERRAIN_READ),
    ("GET", "/terrain/legend", Perm.TERRAIN_READ),
    ("GET", "/routes", Perm.ROUTE_READ),
    ("GET", "/drones", Perm.DRONE_READ),
    ("GET", "/drones/events", Perm.DRONE_READ),
    ("GET", "/drones/missions", Perm.DRONE_READ),
    ("GET", "/security/events", Perm.SECURITY_READ),
    ("GET", "/security/posture", Perm.SECURITY_READ),
    ("GET", "/security/catalogue", Perm.SECURITY_READ),
    ("GET", "/security/settings", Perm.SECURITY_READ),
    ("GET", "/audit", Perm.AUDIT_READ),
    ("GET", "/audit/facets", Perm.AUDIT_READ),
    ("GET", "/analytics", Perm.ANALYTICS_READ),
    ("GET", "/analytics/model-comparison", Perm.ANALYTICS_READ),
    ("GET", "/simulation/status", Perm.SIMULATION_READ),
    ("GET", "/simulation/scenarios", Perm.SIMULATION_READ),
    ("GET", "/simulation/runs", Perm.SIMULATION_READ),
    ("GET", "/simulation/data-source", Perm.SIMULATION_READ),
    ("GET", "/simulation/snapshot", Perm.SIMULATION_READ),
    ("GET", "/users", Perm.USER_READ),
    ("GET", "/users/roles", Perm.USER_READ),
    ("GET", "/config", Perm.CONFIG_READ),
    ("GET", "/config/defaults", Perm.CONFIG_READ),
]

ROLE_FIXTURES = {
    Role.ADMIN: "admin_headers",
    Role.COMMANDER: "commander_headers",
    Role.MEDICAL_OFFICER: "medic_headers",
    Role.OPERATOR: "operator_headers",
    Role.VIEWER: "viewer_headers",
}


async def test_permission_matrix(
    client: AsyncClient,
    admin_headers: dict[str, str],
    commander_headers: dict[str, str],
    medic_headers: dict[str, str],
    operator_headers: dict[str, str],
    viewer_headers: dict[str, str],
) -> None:
    """Assert the entire (role x endpoint) grid in one pass.

    Failures are collected so a broken guard reports every affected cell
    instead of stopping at the first one.
    """
    headers_by_role = {
        Role.ADMIN: admin_headers,
        Role.COMMANDER: commander_headers,
        Role.MEDICAL_OFFICER: medic_headers,
        Role.OPERATOR: operator_headers,
        Role.VIEWER: viewer_headers,
    }
    mismatches: list[str] = []
    for role, headers in headers_by_role.items():
        for method, path, permission in GUARDED_ENDPOINTS:
            response = await client.request(method, path, headers=headers)
            allowed = permission in ROLE_PERMISSIONS[role]
            expected = 200 if allowed else 403
            if response.status_code != expected:
                mismatches.append(
                    f"{role.value} {method} {path}: expected {expected}, "
                    f"got {response.status_code} ({response.text[:160]})"
                )
    assert not mismatches, "\n".join(mismatches)


async def test_denial_body_names_the_missing_permission(
    client: AsyncClient, viewer_headers: dict[str, str]
) -> None:
    response = await client.get("/users", headers=viewer_headers)
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "permission_denied"
    assert error["details"]["required_permissions"] == [Perm.USER_READ.value]
    assert error["details"]["missing"] == [Perm.USER_READ.value]
    assert error["request_id"]


async def test_every_guarded_endpoint_rejects_anonymous_callers(client: AsyncClient) -> None:
    for method, path, _ in GUARDED_ENDPOINTS:
        response = await client.request(method, path)
        assert response.status_code == 401, f"{path} allowed an anonymous call"


async def test_write_endpoints_are_denied_to_a_viewer(
    client: AsyncClient, viewer_headers: dict[str, str], a_person_id: str
) -> None:
    attempts = [
        ("POST", "/personnel", {"call_sign": "X-1", "name": "X", "age": 30, "unit": "U"}),
        ("PATCH", f"/personnel/{a_person_id}", {"rank": "Sepoy"}),
        ("DELETE", f"/personnel/{a_person_id}", None),
        ("POST", "/simulation/start", {}),
        ("POST", "/simulation/stop", None),
        ("POST", "/routes/plan", {"start_x": 3, "start_y": 3, "goal_x": 40, "goal_y": 40}),
        ("POST", "/security/inject", {"kind": "jamming"}),
        ("POST", "/predictions/reload", None),
        (
            "POST",
            "/users",
            {
                "email": "x@a4s.local",
                "full_name": "X",
                "password": "Aa1!aaaaaaaa",
                "roles": ["VIEWER"],
            },
        ),
    ]
    for method, path, body in attempts:
        response = await client.request(method, path, json=body, headers=viewer_headers)
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"


async def test_admin_can_reach_the_endpoints_other_roles_cannot(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    for path in ("/users", "/users/roles", "/config", "/config/defaults", "/audit"):
        assert (await client.get(path, headers=admin_headers)).status_code == 200


async def test_permissions_in_the_token_match_the_role_definition(
    client: AsyncClient, medic_headers: dict[str, str]
) -> None:
    body = (await client.get("/auth/me", headers=medic_headers)).json()
    assert set(body["permissions"]) == {p.value for p in ROLE_PERMISSIONS[Role.MEDICAL_OFFICER]}
