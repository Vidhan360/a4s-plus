"""Password hashing, JWT issuance and the permission model."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.core.config import settings
from app.core.errors import AuthenticationError
from app.core.errors import ValidationError as AppValidationError
from app.core.permissions import (
    PERMISSION_DESCRIPTIONS,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    Perm,
    Role,
    permissions_for_roles,
)
from app.core.security import (
    constant_time_compare,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    validate_password_strength,
    verify_password,
)


# ----------------------------------------------------------------- passwords
def test_hash_is_argon2id_and_salted() -> None:
    a = hash_password("Correct-Horse-Battery-9!")
    b = hash_password("Correct-Horse-Battery-9!")
    assert a.startswith("$argon2id$")
    assert a != b, "each hash must use a fresh random salt"


def test_verify_accepts_the_right_password_and_rejects_others() -> None:
    digest = hash_password("Correct-Horse-Battery-9!")
    assert verify_password("Correct-Horse-Battery-9!", digest) is True
    assert verify_password("correct-horse-battery-9!", digest) is False
    assert verify_password("", digest) is False


def test_verify_never_raises_on_a_malformed_hash() -> None:
    assert verify_password("anything", "not-a-hash") is False


def test_needs_rehash_is_false_for_a_current_hash() -> None:
    assert needs_rehash(hash_password("Correct-Horse-Battery-9!")) is False


@pytest.mark.parametrize(
    "password",
    ["short1!A", "alllowercase123!", "ALLUPPERCASE123!", "NoDigitsHere!!", "NoSymbols123abc"],
)
def test_weak_passwords_are_rejected_with_a_reason(password: str) -> None:
    with pytest.raises(AppValidationError) as excinfo:
        validate_password_strength(password)
    assert str(excinfo.value)


def test_a_strong_password_is_accepted() -> None:
    validate_password_strength("Glacier-Watch-2026!")


# ---------------------------------------------------------------------- JWT
def test_access_token_round_trips_with_all_claims() -> None:
    user_id = uuid.uuid4()
    token, expires_at = create_access_token(
        user_id=user_id,
        email="commander@a4s.local",
        roles=[Role.COMMANDER.value],
        permissions=[Perm.DASHBOARD_READ.value, Perm.ALERT_ACK.value],
    )
    claims = decode_access_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["email"] == "commander@a4s.local"
    assert claims["roles"] == [Role.COMMANDER.value]
    assert claims["perms"] == sorted([Perm.DASHBOARD_READ.value, Perm.ALERT_ACK.value])
    assert claims["type"] == "access"
    assert claims["iss"] == "a4s-plus"
    assert claims["jti"]
    assert expires_at.timestamp() == pytest.approx(claims["exp"], abs=1)


def test_each_token_has_a_unique_jti() -> None:
    args = {"user_id": uuid.uuid4(), "email": "a@b.local", "roles": [], "permissions": []}
    a = decode_access_token(create_access_token(**args)[0])
    b = decode_access_token(create_access_token(**args)[0])
    assert a["jti"] != b["jti"]


def test_expired_token_is_rejected() -> None:
    token, _ = create_access_token(
        user_id=uuid.uuid4(),
        email="a@b.local",
        roles=[],
        permissions=[],
        expires_minutes=-1,
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_token_signed_with_another_secret_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "iss": "a4s-plus",
            "exp": int(time.time()) + 600,
        },
        "an-attacker-secret",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(forged)


def test_unsigned_none_algorithm_token_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": "x", "type": "access", "iss": "a4s-plus", "exp": int(time.time()) + 600},
        key="",
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(forged)


def test_wrong_issuer_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": "x",
            "type": "access",
            "iss": "somebody-else",
            "exp": int(time.time()) + 600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(forged)


def test_a_refresh_token_is_not_accepted_as_an_access_token() -> None:
    forged = jwt.encode(
        {
            "sub": "x",
            "type": "refresh",
            "iss": "a4s-plus",
            "exp": int(time.time()) + 600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(forged)


def test_refresh_tokens_are_random_and_only_hashes_are_storable() -> None:
    clear_a, hash_a = generate_refresh_token()
    clear_b, hash_b = generate_refresh_token()
    assert clear_a != clear_b
    assert hash_a != hash_b
    assert len(hash_a) == 64
    assert hash_token(clear_a) == hash_a
    assert clear_a not in hash_a


def test_constant_time_compare_behaves_like_equality() -> None:
    assert constant_time_compare("abc", "abc") is True
    assert constant_time_compare("abc", "abd") is False


# --------------------------------------------------------------- permissions
def test_there_are_exactly_five_roles() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert len(Role) == 5


def test_every_permission_is_documented() -> None:
    for perm in Perm:
        assert PERMISSION_DESCRIPTIONS.get(perm), perm


def test_every_role_is_documented() -> None:
    for role in Role:
        assert ROLE_DESCRIPTIONS.get(role), role


def test_admin_holds_every_permission() -> None:
    assert ROLE_PERMISSIONS[Role.ADMIN] == set(Perm)


def test_viewer_is_read_only() -> None:
    for perm in ROLE_PERMISSIONS[Role.VIEWER]:
        assert perm.value.endswith((":read",)), perm


@pytest.mark.parametrize("role", [Role.COMMANDER, Role.MEDICAL_OFFICER, Role.OPERATOR, Role.VIEWER])
def test_non_admin_roles_cannot_manage_users_or_config(role: Role) -> None:
    perms = ROLE_PERMISSIONS[role]
    assert Perm.USER_WRITE not in perms
    assert Perm.CONFIG_WRITE not in perms


def test_vitals_ingestion_is_restricted_to_the_expected_roles() -> None:
    allowed = {r for r, p in ROLE_PERMISSIONS.items() if Perm.VITALS_INGEST in p}
    assert allowed == {Role.ADMIN, Role.MEDICAL_OFFICER, Role.OPERATOR}
    assert Role.VIEWER not in allowed
    assert Role.COMMANDER not in allowed


def test_permissions_for_roles_is_a_union() -> None:
    union = permissions_for_roles([Role.VIEWER.value, Role.OPERATOR.value])
    assert set(union) == {
        p.value for p in ROLE_PERMISSIONS[Role.VIEWER] | ROLE_PERMISSIONS[Role.OPERATOR]
    }


def test_unknown_roles_are_ignored_rather_than_granting_access() -> None:
    assert set(permissions_for_roles(["NOT_A_ROLE"])) == set()
