"""``/api/v1/auth`` — sign-in, refresh rotation, sign-out, self-service."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import CurrentUser, DbSession, user_permissions
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.enums import AuditResult, SecurityEventOrigin, SecurityEventType
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    SessionUser,
)
from app.schemas.common import MessageResponse
from app.services.audit_service import AuditService, audit_context
from app.services.auth_service import auth_service, session_user_payload
from app.services.security_service import SecurityService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    session: DbSession,
) -> LoginResponse:
    """Exchange credentials for an access/refresh token pair."""
    context = audit_context(request)
    result = await auth_service.login(
        session,
        email=payload.email,
        password=payload.password,
        ip=context["ip"],
        user_agent=context["user_agent"],
        request_id=context["request_id"],
    )
    return LoginResponse.model_validate(result)


@router.post("/refresh", response_model=LoginResponse)
@limiter.limit(settings.rate_limit_refresh)
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest,
    session: DbSession,
) -> LoginResponse:
    """Rotate a refresh token. The presented token is single-use."""
    context = audit_context(request)
    result = await auth_service.refresh(
        session,
        token=payload.refresh_token,
        ip=context["ip"],
        user_agent=context["user_agent"],
        request_id=context["request_id"],
    )
    return LoginResponse.model_validate(result)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    payload: LogoutRequest,
    session: DbSession,
    user: CurrentUser,
) -> MessageResponse:
    revoked = await auth_service.logout(
        session, user=user, token=payload.refresh_token, all_sessions=payload.all_sessions
    )
    await AuditService.log_from_request(
        session,
        request,
        action="auth.logout",
        resource_type="user",
        resource_id=str(user.id),
        actor_user_id=user.id,
        actor_email=user.email,
        metadata={"revoked_tokens": revoked, "all_sessions": payload.all_sessions},
    )
    return MessageResponse(message="Signed out.", details={"revoked_tokens": revoked})


@router.get("/me", response_model=SessionUser)
async def me(user: CurrentUser) -> SessionUser:
    return SessionUser.model_validate(session_user_payload(user))


@router.get("/permissions")
async def my_permissions(user: CurrentUser) -> dict[str, list[str]]:
    return {
        "roles": sorted(role.code for role in user.roles),
        "permissions": sorted(user_permissions(user)),
    }


@router.post(
    "/change-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(settings.rate_limit_password_change)
async def change_password(
    request: Request,
    response: Response,
    payload: ChangePasswordRequest,
    session: DbSession,
    user: CurrentUser,
) -> MessageResponse:
    await auth_service.change_password(
        session,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    context = audit_context(request)
    await SecurityService.record(
        session,
        event_type=SecurityEventType.PASSWORD_CHANGED,
        origin=SecurityEventOrigin.REAL,
        source="auth.change_password",
        title="Password changed",
        description=f"{user.email} changed their password; all sessions revoked.",
        actor_user_id=user.id,
        subject_email=user.email,
        **context,
    )
    await AuditService.log_from_request(
        session,
        request,
        action="auth.change_password",
        resource_type="user",
        resource_id=str(user.id),
        result=AuditResult.SUCCESS,
        actor_user_id=user.id,
        actor_email=user.email,
    )
    return MessageResponse(message="Password updated. All other sessions have been signed out.")
