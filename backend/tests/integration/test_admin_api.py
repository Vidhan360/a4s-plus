"""User administration, runtime configuration and the append-only audit trail.

The audit assertions are the important ones: the append-only guarantee is
enforced by a database trigger, so the test talks to PostgreSQL directly and
tries to tamper with a row. If the trigger were ever dropped from a migration,
this test fails.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


async def test_role_catalogue_requires_authentication(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    assert (await client.get("/users/roles")).status_code == 401

    response = await client.get("/users/roles", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    roles = body["roles"]
    assert body["permissions"]
    assert "permission-based" in body["note"]
    codes = {role["code"] for role in roles}
    assert codes == {"ADMIN", "COMMANDER", "MEDICAL_OFFICER", "OPERATOR", "VIEWER"}
    for role in roles:
        assert role["permissions"], f"{role['code']} has no permissions"
    admin = next(r for r in roles if r["code"] == "ADMIN")
    viewer = next(r for r in roles if r["code"] == "VIEWER")
    assert set(viewer["permissions"]) < set(admin["permissions"])


async def test_user_lifecycle(
    client: AsyncClient, admin_headers: dict[str, str], unique_suffix: str
) -> None:
    email = f"lifecycle-{unique_suffix}@a4s.local"
    created = await client.post(
        "/users",
        json={
            "email": email,
            "full_name": "Lifecycle Tester",
            "password": "Str0ng-Passphrase-2026!",
            "roles": ["OPERATOR"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["email"] == email
    assert user["roles"] == ["OPERATOR"]
    assert user["status"] == "ACTIVE"
    user_id = user["id"]

    # Sanity: the schema is enforced rather than silently defaulted.
    assert (await client.post("/users", json={}, headers=admin_headers)).status_code == 422

    session_login = await client.post(
        "/auth/login", json={"email": email, "password": "Str0ng-Passphrase-2026!"}
    )
    assert session_login.status_code == 200, session_login.text

    # Duplicate email is rejected rather than silently overwriting.
    duplicate = await client.post(
        "/users",
        json={
            "email": email,
            "full_name": "Impostor",
            "password": "Another-Passphrase-2026!",
            "roles": ["VIEWER"],
        },
        headers=admin_headers,
    )
    assert duplicate.status_code == 409, duplicate.text

    updated = await client.patch(
        f"/users/{user_id}",
        json={"full_name": "Lifecycle Tester II", "roles": ["VIEWER", "OPERATOR"]},
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Lifecycle Tester II"
    assert updated.json()["roles"] == ["OPERATOR", "VIEWER"]

    reset = await client.post(
        f"/users/{user_id}/password",
        json={"new_password": "Rotated-Passphrase-2026!"},
        headers=admin_headers,
    )
    assert reset.status_code == 200, reset.text

    # The old password no longer works; the new one does.
    assert (
        await client.post(
            "/auth/login", json={"email": email, "password": "Str0ng-Passphrase-2026!"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/auth/login", json={"email": email, "password": "Rotated-Passphrase-2026!"}
        )
    ).status_code == 200

    disabled = await client.patch(
        f"/users/{user_id}", json={"status": "DISABLED"}, headers=admin_headers
    )
    assert disabled.status_code == 200
    assert (
        await client.post(
            "/auth/login", json={"email": email, "password": "Rotated-Passphrase-2026!"}
        )
    ).status_code in (401, 403)


async def test_weak_passwords_are_rejected_with_422(
    client: AsyncClient, admin_headers: dict[str, str], unique_suffix: str
) -> None:
    result = await client.post(
        "/users",
        json={
            "email": f"weak-{unique_suffix}@a4s.local",
            "full_name": "Weak Password",
            "password": "password1234",
            "roles": ["VIEWER"],
        },
        headers=admin_headers,
    )
    assert result.status_code == 422, result.text


async def test_unknown_role_is_rejected(
    client: AsyncClient, admin_headers: dict[str, str], unique_suffix: str
) -> None:
    response = await client.post(
        "/users",
        json={
            "email": f"badrole-{unique_suffix}@a4s.local",
            "full_name": "Bad Role",
            "password": "Str0ng-Passphrase-2026!",
            "roles": ["SUPREME_LEADER"],
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "Unknown role" in response.text


async def test_user_listing_paginates_and_filters(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/users", params={"limit": 2}, headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) <= 2
    assert body["meta"]["total"] >= 5

    by_role = await client.get("/users", params={"role": "ADMIN"}, headers=admin_headers)
    assert by_role.status_code == 200
    assert all("ADMIN" in item["roles"] for item in by_role.json()["items"])


async def test_unknown_user_returns_404(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    response = await client.get(f"/users/{uuid.uuid4()}", headers=admin_headers)
    assert response.status_code == 404


async def test_only_admin_manages_users(
    client: AsyncClient, commander_headers: dict[str, str], viewer_headers: dict[str, str]
) -> None:
    payload = {
        "email": "nope@a4s.local",
        "full_name": "Not Allowed",
        "password": "Str0ng-Passphrase-2026!",
        "roles": ["VIEWER"],
    }
    assert (await client.post("/users", json=payload, headers=commander_headers)).status_code == 403
    assert (await client.post("/users", json=payload, headers=viewer_headers)).status_code == 403
    assert (await client.get("/users", headers=viewer_headers)).status_code == 403


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


async def test_config_defaults_are_documented(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/config/defaults", headers=admin_headers)
    assert response.status_code == 200, response.text
    defaults = response.json()["defaults"]
    assert "risk.thresholds" in defaults
    assert "alert.rules" in defaults
    assert "route.costs" in defaults
    assert "prediction.defaults" in defaults
    for key, entry in defaults.items():
        assert entry["description"], f"{key} has no description"


async def test_config_can_be_updated_and_reset(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    listing = await client.get("/config", headers=admin_headers)
    assert listing.status_code == 200
    keys = {row["key"] for row in listing.json()}
    assert "risk.categories" in keys

    original = (await client.get("/config/risk.categories", headers=admin_headers)).json()
    assert original["value"]["HIGH"] == pytest.approx(65.0)

    updated = await client.put(
        "/config/risk.categories",
        json={"value": {**original["value"], "HIGH": 70.0}},
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"]["HIGH"] == pytest.approx(70.0)
    assert updated.json()["version"] > original["version"]

    reset = await client.post("/config/risk.categories/reset", headers=admin_headers)
    assert reset.status_code == 200, reset.text
    assert reset.json()["value"]["HIGH"] == pytest.approx(65.0)


async def test_unknown_config_key_returns_404(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    assert (await client.get("/config/not.a.key", headers=admin_headers)).status_code == 404
    assert (
        await client.put("/config/not.a.key", json={"value": 1}, headers=admin_headers)
    ).status_code == 404


async def test_invalid_config_payload_is_rejected(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/config/risk.categories",
        json={"value": {"LOW": "not-a-number"}},
        headers=admin_headers,
    )
    assert response.status_code == 422, response.text


async def test_non_admin_cannot_write_config(
    client: AsyncClient, operator_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/config/risk.categories", json={"value": {}}, headers=operator_headers
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------


async def test_audit_records_admin_actions_with_actor_and_request_id(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await client.post("/config/risk.categories/reset", headers=admin_headers)

    response = await client.get(
        "/audit", params={"action": "config.reset", "limit": 5}, headers=admin_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"], "config.reset was not audited"
    entry = body["items"][0]
    assert entry["actor_email"] == "admin@a4s.local"
    assert entry["resource_type"] == "system_configuration"
    assert entry["request_id"]
    assert entry["result"] in ("SUCCESS", "FAILURE")
    assert "Append-only" in body["immutability"]


async def test_audit_facets_and_filters(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    facets = await client.get("/audit/facets", headers=admin_headers)
    assert facets.status_code == 200, facets.text
    body = facets.json()
    assert body["actions"]
    assert body["resource_types"]
    assert body["results"]

    filtered = await client.get(
        "/audit",
        params={"actor_email": "admin@a4s.local", "hours": 24, "limit": 5},
        headers=admin_headers,
    )
    assert filtered.status_code == 200
    assert all(i["actor_email"] == "admin@a4s.local" for i in filtered.json()["items"])

    empty = await client.get("/audit", params={"action": "no.such.action"}, headers=admin_headers)
    assert empty.status_code == 200
    assert empty.json()["items"] == []


async def test_audit_api_exposes_no_mutation_path(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = await getattr(client, method)("/audit", headers=admin_headers)
        assert response.status_code in (404, 405), f"{method} /audit -> {response.status_code}"


async def test_audit_rows_cannot_be_updated_or_deleted_in_the_database(
    session: AsyncSession, client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The append-only guarantee is enforced by a trigger, so prove it."""
    await client.get("/dashboard", headers=admin_headers)
    row = (
        await session.execute(text("SELECT id FROM audit_logs ORDER BY created_at DESC LIMIT 1"))
    ).first()
    assert row is not None, "no audit rows to tamper with"
    audit_id = row[0]

    with pytest.raises(DBAPIError) as update_error:
        await session.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :i"), {"i": audit_id}
        )
    assert "append-only" in str(update_error.value).lower()
    await session.rollback()

    with pytest.raises(DBAPIError) as delete_error:
        await session.execute(text("DELETE FROM audit_logs WHERE id = :i"), {"i": audit_id})
    assert "append-only" in str(delete_error.value).lower()
    await session.rollback()

    still_there = (
        await session.execute(text("SELECT action FROM audit_logs WHERE id = :i"), {"i": audit_id})
    ).scalar_one()
    assert still_there != "tampered"


async def test_only_privileged_roles_read_the_audit_trail(
    client: AsyncClient, viewer_headers: dict[str, str], operator_headers: dict[str, str]
) -> None:
    assert (await client.get("/audit", headers=viewer_headers)).status_code == 403
    assert (await client.get("/audit", headers=operator_headers)).status_code == 403
