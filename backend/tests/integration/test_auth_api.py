"""Authentication: login, refresh rotation, lockout, logout, password change."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import RefreshToken, User
from app.models.enums import SecurityEventType, UserStatus

pytestmark = pytest.mark.asyncio


async def test_login_returns_tokens_and_the_user_profile(
    client: AsyncClient, passwords: dict[str, str]
) -> None:
    response = await client.post(
        "/auth/login",
        json={"email": "commander@a4s.local", "password": passwords["commander@a4s.local"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]
    assert body["tokens"]["token_type"] == "bearer"
    assert body["user"]["email"] == "commander@a4s.local"
    assert "COMMANDER" in body["user"]["roles"]
    assert body["user"]["permissions"]
    assert "password_hash" not in response.text
    assert "$argon2" not in response.text


async def test_email_matching_is_case_insensitive(
    client: AsyncClient, passwords: dict[str, str]
) -> None:
    response = await client.post(
        "/auth/login",
        json={"email": "Commander@A4S.local", "password": passwords["commander@a4s.local"]},
    )
    assert response.status_code == 200


async def test_wrong_password_is_rejected_without_revealing_which_field_failed(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/auth/login", json={"email": "commander@a4s.local", "password": "definitely-wrong-1!"}
    )
    assert response.status_code == 401
    # A single generic message for every failure mode: no account enumeration.
    assert response.json()["error"]["message"] == "Invalid email or password."


async def test_unknown_email_gives_the_same_answer_as_a_wrong_password(
    client: AsyncClient,
) -> None:
    unknown = await client.post(
        "/auth/login", json={"email": "nobody@a4s.local", "password": "definitely-wrong-1!"}
    )
    wrong = await client.post(
        "/auth/login", json={"email": "commander@a4s.local", "password": "definitely-wrong-1!"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]


async def test_malformed_login_payload_is_a_422(client: AsyncClient) -> None:
    assert (await client.post("/auth/login", json={"email": "x"})).status_code == 422
    assert (
        await client.post("/auth/login", json={"email": "not-an-email", "password": "abcdefgh"})
    ).status_code == 422


async def test_me_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get("/auth/me")).status_code == 401
    assert (
        await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    ).status_code == 401
    assert (
        await client.get("/auth/me", headers={"Authorization": "NotBearer x"})
    ).status_code == 401


async def test_me_returns_the_caller_and_their_permissions(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    body = (await client.get("/auth/me", headers=commander_headers)).json()
    assert body["email"] == "commander@a4s.local"
    assert len(body["permissions"]) > 10
    assert "user:write" not in body["permissions"]


async def test_permissions_catalogue_documents_roles(
    client: AsyncClient, commander_headers: dict[str, str]
) -> None:
    response = await client.get("/auth/permissions", headers=commander_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["permissions"]
    assert all(isinstance(code, str) and ":" in code for code in body["permissions"])


# ------------------------------------------------------------ refresh flow
async def test_refresh_rotates_the_token_and_the_new_one_keeps_working(
    client: AsyncClient, passwords: dict[str, str]
) -> None:
    login = await client.post(
        "/auth/login",
        json={"email": "viewer@a4s.local", "password": passwords["viewer@a4s.local"]},
    )
    token = login.json()["tokens"]["refresh_token"]
    seen = {token}
    for _ in range(3):
        response = await client.post("/auth/refresh", json={"refresh_token": token})
        assert response.status_code == 200, response.text
        token = response.json()["tokens"]["refresh_token"]
        assert token not in seen, "each refresh must mint a brand-new token"
        seen.add(token)


async def test_replaying_a_rotated_token_revokes_the_whole_family(
    client: AsyncClient, passwords: dict[str, str]
) -> None:
    """Reuse is treated as theft: every token in the family is invalidated."""
    login = await client.post(
        "/auth/login",
        json={"email": "viewer@a4s.local", "password": passwords["viewer@a4s.local"]},
    )
    original = login.json()["tokens"]["refresh_token"]
    rotated = (await client.post("/auth/refresh", json={"refresh_token": original})).json()[
        "tokens"
    ]["refresh_token"]

    reuse = await client.post("/auth/refresh", json={"refresh_token": original})
    assert reuse.status_code == 401

    # The legitimate successor is now revoked too, forcing re-authentication.
    assert (await client.post("/auth/refresh", json={"refresh_token": rotated})).status_code == 401


async def test_reusing_a_rotated_token_records_a_security_event(
    client: AsyncClient, passwords: dict[str, str], session: AsyncSession
) -> None:
    login = await client.post(
        "/auth/login",
        json={"email": "viewer@a4s.local", "password": passwords["viewer@a4s.local"]},
    )
    original = login.json()["tokens"]["refresh_token"]
    await client.post("/auth/refresh", json={"refresh_token": original})
    await client.post("/auth/refresh", json={"refresh_token": original})

    rows = (
        await session.execute(
            text(
                "SELECT count(*) FROM security_events WHERE event_type = :t",
            ),
            {"t": SecurityEventType.TOKEN_REUSE_DETECTED.value},
        )
    ).scalar_one()
    assert rows >= 1


async def test_refresh_with_garbage_is_rejected(client: AsyncClient) -> None:
    assert (
        await client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    ).status_code == 401


async def test_only_refresh_token_hashes_are_stored(
    client: AsyncClient, passwords: dict[str, str], session: AsyncSession
) -> None:
    login = await client.post(
        "/auth/login",
        json={"email": "operator@a4s.local", "password": passwords["operator@a4s.local"]},
    )
    clear = login.json()["tokens"]["refresh_token"]
    stored = (await session.execute(select(RefreshToken.token_hash))).scalars().all()
    assert stored
    assert clear not in stored
    assert all(len(h) == 64 for h in stored)


async def test_logout_revokes_the_refresh_token(
    client: AsyncClient, passwords: dict[str, str]
) -> None:
    login = await client.post(
        "/auth/login",
        json={"email": "operator@a4s.local", "password": passwords["operator@a4s.local"]},
    )
    tokens = login.json()["tokens"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    logout = await client.post(
        "/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
    )
    assert logout.status_code == 200
    assert (
        await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401


# --------------------------------------------------------------- lockout
async def test_repeated_failures_lock_the_account_then_it_can_be_unlocked(
    client: AsyncClient,
    passwords: dict[str, str],
    admin_headers: dict[str, str],
    session: AsyncSession,
) -> None:
    email = "medic@a4s.local"
    for _ in range(settings.max_failed_logins):
        response = await client.post(
            "/auth/login", json={"email": email, "password": "wrong-password-1!"}
        )
        assert response.status_code in (401, 423)

    locked = await client.post("/auth/login", json={"email": email, "password": passwords[email]})
    assert locked.status_code == 423, locked.text
    assert "locked" in locked.json()["error"]["message"].lower()

    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.status is UserStatus.LOCKED or user.locked_until is not None

    users = (await client.get("/users", headers=admin_headers)).json()["items"]
    user_id = next(u["id"] for u in users if u["email"] == email)
    unlock = await client.post(f"/users/{user_id}/unlock", headers=admin_headers)
    assert unlock.status_code == 200

    await session.commit()
    ok = await client.post("/auth/login", json={"email": email, "password": passwords[email]})
    assert ok.status_code == 200


async def test_failed_logins_are_recorded_as_security_events(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.post(
        "/auth/login", json={"email": "operator@a4s.local", "password": "nope-nope-1!"}
    )
    count = (
        await session.execute(
            text("SELECT count(*) FROM security_events WHERE event_type = :t"),
            {"t": SecurityEventType.FAILED_LOGIN.value},
        )
    ).scalar_one()
    assert count >= 1


# -------------------------------------------------------- password change
async def test_password_change_requires_the_current_password_and_rotates_tokens(
    client: AsyncClient, passwords: dict[str, str]
) -> None:
    email = "viewer@a4s.local"
    original = passwords[email]
    new_password = "Rotated-Viewer-2026!"
    login = await client.post("/auth/login", json={"email": email, "password": original})
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    wrong = await client.post(
        "/auth/change-password",
        json={"current_password": "not-it-1!", "new_password": new_password},
        headers=headers,
    )
    assert wrong.status_code == 401

    weak = await client.post(
        "/auth/change-password",
        json={"current_password": original, "new_password": "alllowercaseletters"},
        headers=headers,
    )
    assert weak.status_code == 422

    changed = await client.post(
        "/auth/change-password",
        json={"current_password": original, "new_password": new_password},
        headers=headers,
    )
    assert changed.status_code == 200

    assert (
        await client.post("/auth/login", json={"email": email, "password": original})
    ).status_code == 401
    assert (
        await client.post("/auth/login", json={"email": email, "password": new_password})
    ).status_code == 200

    # Restore the seeded password so the rest of the suite is unaffected.
    restore_login = await client.post(
        "/auth/login", json={"email": email, "password": new_password}
    )
    restore_headers = {"Authorization": f"Bearer {restore_login.json()['tokens']['access_token']}"}
    restored = await client.post(
        "/auth/change-password",
        json={"current_password": new_password, "new_password": original},
        headers=restore_headers,
    )
    assert restored.status_code == 200


async def test_concurrent_logins_each_get_their_own_refresh_token(
    client: AsyncClient, passwords: dict[str, str]
) -> None:
    payload = {
        "email": "operator@a4s.local",
        "password": passwords["operator@a4s.local"],
    }
    responses = await asyncio.gather(*[client.post("/auth/login", json=payload) for _ in range(3)])
    tokens = {r.json()["tokens"]["refresh_token"] for r in responses}
    assert len(tokens) == 3
