"""Password hashing, JWT issuing/verification and token hashing.

* Passwords: Argon2id via ``argon2-cffi``.
* Access tokens: short-lived signed JWTs carrying roles and permissions.
* Refresh tokens: opaque random strings; only a SHA-256 hash is persisted, and
  each refresh rotates the token within a family so replay is detectable.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import AuthenticationError, ValidationError

# OWASP-aligned Argon2id parameters (interactive profile).
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

TokenType = Literal["access", "refresh"]
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> None:
    """Reject weak passwords.

    Raises :class:`app.core.errors.ValidationError` so the API answers 422 with
    an actionable message instead of surfacing an internal error.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    checks = (
        (any(c.islower() for c in password), "a lowercase letter"),
        (any(c.isupper() for c in password), "an uppercase letter"),
        (any(c.isdigit() for c in password), "a digit"),
        (any(not c.isalnum() for c in password), "a symbol"),
    )
    missing = [label for ok, label in checks if not ok]
    if missing:
        raise ValidationError("Password must contain " + ", ".join(missing) + ".")


def create_access_token(
    *,
    user_id: uuid.UUID | str,
    email: str,
    roles: list[str],
    permissions: list[str],
    expires_minutes: int | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=expires_minutes or settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "roles": roles,
        "perms": sorted(permissions),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(16),
        "iss": "a4s-plus",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="a4s-plus",
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token.") from exc
    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type.")
    return payload


def generate_refresh_token() -> tuple[str, str]:
    """Return ``(clear_token, sha256_hash)``. Only the hash is persisted."""
    token = secrets.token_urlsafe(48)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)
