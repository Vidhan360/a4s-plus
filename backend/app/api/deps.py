"""Shared FastAPI dependencies: auth, RBAC and pagination."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.permissions import Perm
from app.core.security import decode_access_token
from app.models.auth import User
from app.models.enums import (
    SecurityEventOrigin,
    SecurityEventType,
    UserStatus,
)
from app.repositories import users as user_repo
from app.services.audit_service import audit_context
from app.services.security_service import SecurityService

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_token_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.")
    try:
        claims = decode_access_token(credentials.credentials)
    except AuthenticationError:
        await SecurityService.record_isolated(
            event_type=SecurityEventType.INVALID_TOKEN,
            origin=SecurityEventOrigin.REAL,
            source=f"{request.method} {request.url.path}",
            title="Rejected access token",
            description="An invalid, malformed or expired access token was presented.",
            **audit_context(request),
        )
        raise
    return claims


async def get_current_user(
    session: DbSession,
    claims: Annotated[dict[str, Any], Depends(get_token_claims)],
) -> User:
    import uuid

    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Malformed token subject.") from exc
    user = await user_repo.get_user(session, user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.")
    if user.status == UserStatus.DISABLED.value:
        raise AuthenticationError("Account is disabled.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def user_permissions(user: User) -> set[str]:
    from app.core.permissions import permissions_for_roles

    return permissions_for_roles([role.code for role in user.roles])


def require(*perms: Perm) -> Any:
    """Dependency factory enforcing that the caller holds every permission.

    Denials are recorded as real security events and audited, which is what
    the Security Monitor's "permission violation" feed shows.
    """
    required = {p.value for p in perms}

    async def _guard(request: Request, user: CurrentUser) -> User:
        granted = user_permissions(user)
        missing = sorted(required - granted)
        if missing:
            await SecurityService.record_isolated(
                event_type=SecurityEventType.PERMISSION_VIOLATION,
                origin=SecurityEventOrigin.REAL,
                source=f"{request.method} {request.url.path}",
                title="Permission denied",
                description=(f"{user.email} attempted an action requiring {', '.join(missing)}."),
                actor_user_id=user.id,
                subject_email=user.email,
                payload={"required": sorted(required), "missing": missing},
                **audit_context(request),
            )
            raise PermissionDeniedError(
                "You do not have permission to perform this action.",
                details={"required_permissions": sorted(required), "missing": missing},
            )
        return user

    return Depends(_guard)


class Pagination:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PageParams = Annotated[Pagination, Depends(Pagination)]
