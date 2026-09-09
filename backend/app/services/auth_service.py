"""Authentication: login, lockout, refresh-token rotation, password changes.

Security properties implemented here (all verified by tests in
``tests/test_auth.py``):

* Passwords are hashed with Argon2id; hashes are transparently upgraded when
  the configured cost parameters change.
* Failed logins increment a counter and lock the account for a configurable
  window. Responses are identical for "unknown email" and "wrong password" so
  the endpoint is not a user-enumeration oracle.
* Refresh tokens are opaque 256-bit secrets stored only as SHA-256 hashes,
  single-use, and rotated on every refresh. Tokens are grouped into a
  *family*; presenting an already-rotated token revokes the whole family and
  raises a security event (stolen-token detection).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AccountLockedError, AuthenticationError, ValidationError
from app.core.permissions import permissions_for_roles
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.models.auth import RefreshToken, User
from app.models.enums import (
    AuditResult,
    SecurityEventOrigin,
    SecurityEventType,
    UserStatus,
)
from app.repositories import users as user_repo
from app.services.audit_service import AuditService
from app.services.security_service import SecurityService

#: Deliberately identical for every failure mode.
GENERIC_FAILURE = "Invalid email or password."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def session_user_payload(user: User) -> dict[str, Any]:
    roles = sorted(role.code for role in user.roles)
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status,
        "roles": roles,
        "permissions": sorted(permissions_for_roles(roles)),
        "last_login_at": _aware(user.last_login_at),
        "password_changed_at": _aware(user.password_changed_at),
    }


class AuthService:
    """Stateless helper; every method takes the request-scoped session."""

    # ------------------------------------------------------------------ login

    async def login(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        ip: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        user = await user_repo.get_user_by_email(session, email)
        now = _now()

        async def fail(reason: str, subject: str | None) -> None:
            await SecurityService.record(
                session,
                event_type=SecurityEventType.FAILED_LOGIN,
                origin=SecurityEventOrigin.REAL,
                source="auth.login",
                title="Failed sign-in attempt",
                description=reason,
                subject_email=subject,
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
                actor_user_id=user.id if user else None,
            )
            await AuditService.log(
                session,
                action="auth.login",
                resource_type="user",
                resource_id=str(user.id) if user else None,
                result=AuditResult.DENIED,
                actor_user_id=user.id if user else None,
                actor_email=subject,
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
                metadata={"reason": reason},
            )
            # The caller raises AuthenticationError, which rolls the request
            # transaction back. The failed-attempt counter, the security event
            # and the audit record must survive that, so commit them here.
            await session.commit()

        if user is None:
            await fail("Unknown email address.", email)
            raise AuthenticationError(GENERIC_FAILURE)

        locked_until = _aware(user.locked_until)
        if locked_until and locked_until > now:
            await SecurityService.record(
                session,
                event_type=SecurityEventType.ACCOUNT_LOCKOUT,
                origin=SecurityEventOrigin.REAL,
                source="auth.login",
                title="Sign-in attempt on locked account",
                description=f"Account locked until {locked_until.isoformat()}.",
                subject_email=user.email,
                actor_user_id=user.id,
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
            )
            await AuditService.log(
                session,
                action="auth.login",
                resource_type="user",
                resource_id=str(user.id),
                result=AuditResult.DENIED,
                actor_user_id=user.id,
                actor_email=user.email,
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
                metadata={"reason": "account_locked"},
            )
            await session.commit()
            raise AccountLockedError(
                "Account temporarily locked after repeated failed sign-in attempts. "
                "Try again later or contact an administrator.",
                {"locked_until": locked_until.isoformat()},
            )

        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            reason = "Incorrect password."
            if user.failed_login_count >= settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.status = UserStatus.LOCKED.value
                reason = (
                    f"Incorrect password; account locked after "
                    f"{user.failed_login_count} failed attempts."
                )
            await fail(reason, user.email)
            raise AuthenticationError(GENERIC_FAILURE)

        if user.status == UserStatus.DISABLED.value:
            await fail("Account disabled.", user.email)
            raise AuthenticationError("This account is disabled. Contact an administrator.")

        # Success.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        if user.status == UserStatus.LOCKED.value:
            user.status = UserStatus.ACTIVE.value
        user.last_login_at = now

        tokens = await self._issue_tokens(
            session, user, family_id=None, ip=ip, user_agent=user_agent
        )
        await SecurityService.record(
            session,
            event_type=SecurityEventType.LOGIN_SUCCESS,
            origin=SecurityEventOrigin.REAL,
            source="auth.login",
            title="Successful sign-in",
            description=f"{user.email} signed in.",
            subject_email=user.email,
            actor_user_id=user.id,
            ip=ip,
            user_agent=user_agent,
            request_id=request_id,
        )
        await AuditService.log(
            session,
            action="auth.login",
            resource_type="user",
            resource_id=str(user.id),
            result=AuditResult.SUCCESS,
            actor_user_id=user.id,
            actor_email=user.email,
            ip=ip,
            user_agent=user_agent,
            request_id=request_id,
        )
        return {"tokens": tokens, "user": session_user_payload(user)}

    # ---------------------------------------------------------------- refresh

    async def refresh(
        self,
        session: AsyncSession,
        *,
        token: str,
        ip: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        row = await user_repo.get_refresh_token(session, hash_token(token))
        now = _now()
        if row is None:
            await SecurityService.record(
                session,
                event_type=SecurityEventType.TOKEN_REUSE_DETECTED,
                origin=SecurityEventOrigin.REAL,
                source="auth.refresh",
                title="Unknown refresh token presented",
                description="A refresh token was presented that does not exist.",
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
            )
            await session.commit()
            raise AuthenticationError("Invalid refresh token.")

        expires_at = _aware(row.expires_at)
        if row.revoked_at is not None or row.rotated_to_id is not None:
            revoked = await user_repo.revoke_family(session, row.family_id)
            await SecurityService.record(
                session,
                event_type=SecurityEventType.TOKEN_REUSE_DETECTED,
                origin=SecurityEventOrigin.REAL,
                source="auth.refresh",
                title="Refresh-token reuse detected",
                description=(
                    "An already-rotated or revoked refresh token was replayed. "
                    f"The entire token family was revoked ({revoked} token(s))."
                ),
                actor_user_id=row.user_id,
                subject_email=row.user.email if row.user else None,
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
                response_action="Token family revoked; re-authentication required.",
                payload={"family_id": str(row.family_id), "revoked": revoked},
            )
            await AuditService.log(
                session,
                action="auth.refresh",
                resource_type="refresh_token",
                resource_id=str(row.id),
                result=AuditResult.DENIED,
                actor_user_id=row.user_id,
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
                metadata={"reason": "token_reuse"},
            )
            await session.commit()
            raise AuthenticationError(
                "Refresh token already used. All sessions have been revoked; please sign in again."
            )

        if expires_at is None or expires_at <= now:
            row.revoked_at = now
            await session.commit()
            raise AuthenticationError("Refresh token expired. Please sign in again.")

        user = row.user
        if user is None or user.status == UserStatus.DISABLED.value:
            raise AuthenticationError("Account is not permitted to sign in.")

        tokens = await self._issue_tokens(
            session, user, family_id=row.family_id, ip=ip, user_agent=user_agent
        )
        row.revoked_at = now
        row.rotated_to_id = tokens["_row_id"]
        await AuditService.log(
            session,
            action="auth.refresh",
            resource_type="refresh_token",
            resource_id=str(row.id),
            result=AuditResult.SUCCESS,
            actor_user_id=user.id,
            actor_email=user.email,
            ip=ip,
            user_agent=user_agent,
            request_id=request_id,
        )
        public = {k: v for k, v in tokens.items() if not k.startswith("_")}
        return {"tokens": public, "user": session_user_payload(user)}

    # ----------------------------------------------------------------- logout

    async def logout(
        self,
        session: AsyncSession,
        *,
        user: User,
        token: str | None,
        all_sessions: bool = False,
    ) -> int:
        if all_sessions or token is None:
            return await user_repo.revoke_all_for_user(session, user.id)
        row = await user_repo.get_refresh_token(session, hash_token(token))
        if row is None or row.user_id != user.id:
            return 0
        if row.revoked_at is None:
            row.revoked_at = _now()
            return 1
        return 0

    # -------------------------------------------------------- password change

    async def change_password(
        self,
        session: AsyncSession,
        *,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise AuthenticationError("Current password is incorrect.")
        if current_password == new_password:
            raise ValidationError("New password must differ from the current password.")
        validate_password_strength(new_password)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = _now()
        await user_repo.revoke_all_for_user(session, user.id)

    # ---------------------------------------------------------------- helpers

    async def _issue_tokens(
        self,
        session: AsyncSession,
        user: User,
        *,
        family_id: uuid.UUID | None,
        ip: str | None,
        user_agent: str | None,
    ) -> dict[str, Any]:
        roles = sorted(role.code for role in user.roles)
        permissions = sorted(permissions_for_roles(roles))
        access, _access_expires_at = create_access_token(
            user_id=user.id,
            email=user.email,
            roles=roles,
            permissions=permissions,
        )
        raw_refresh, refresh_hash = generate_refresh_token()
        row = RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=refresh_hash,
            family_id=family_id or uuid.uuid4(),
            expires_at=_now() + timedelta(days=settings.refresh_token_days),
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
        )
        session.add(row)
        await session.flush()
        return {
            "access_token": access,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "expires_in": settings.access_token_minutes * 60,
            "_row_id": row.id,
        }


auth_service = AuthService()
