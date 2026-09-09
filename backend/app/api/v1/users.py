"""``/api/v1/users`` — administrator-only user management and the RBAC matrix."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession, PageParams, require
from app.core.permissions import PERMISSION_DESCRIPTIONS, Perm, Role
from app.schemas.common import MessageResponse, page
from app.schemas.users import (
    AdminPasswordReset,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.audit_service import AuditService
from app.services.user_service import role_catalogue, serialise_user, user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/roles")
async def list_roles(
    _user: Annotated[Any, require(Perm.USER_READ)],
) -> dict[str, Any]:
    """The full role → permission matrix, as enforced by the API."""
    return {
        "roles": role_catalogue(),
        "permissions": [
            {"code": perm.value, "description": description}
            for perm, description in PERMISSION_DESCRIPTIONS.items()
        ],
        "note": (
            "Authorisation is permission-based. Roles are bundles of "
            "permissions; every endpoint declares the permissions it requires."
        ),
    }


@router.get("")
async def list_users(
    session: DbSession,
    pagination: PageParams,
    _user: Annotated[Any, require(Perm.USER_READ)],
    search: Annotated[str | None, Query(max_length=128)] = None,
    account_status: Annotated[str | None, Query(alias="status")] = None,
    role: Role | None = None,
) -> dict[str, Any]:
    from app.repositories import users as user_repo

    rows, total = await user_repo.list_users(
        session,
        limit=pagination.limit,
        offset=pagination.offset,
        search=search,
        status=account_status,
        role=role.value if role else None,
    )
    return page(
        [UserOut.model_validate(serialise_user(u)) for u in rows],
        total,
        pagination.limit,
        pagination.offset,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    payload: UserCreate,
    session: DbSession,
    actor: Annotated[Any, require(Perm.USER_WRITE)],
) -> UserOut:
    user = await user_service.create(
        session,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        roles=payload.roles,
    )
    await AuditService.log_from_request(
        session,
        request,
        action="user.create",
        resource_type="user",
        resource_id=str(user.id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"email": user.email, "roles": payload.roles},
    )
    return UserOut.model_validate(serialise_user(user))


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.USER_READ)],
) -> UserOut:
    from app.core.errors import NotFoundError
    from app.repositories import users as user_repo

    row = await user_repo.get_user(session, user_id)
    if row is None:
        raise NotFoundError("User not found.")
    return UserOut.model_validate(serialise_user(row))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    payload: UserUpdate,
    session: DbSession,
    actor: Annotated[Any, require(Perm.USER_WRITE)],
) -> UserOut:
    user = await user_service.update(
        session,
        user_id=user_id,
        actor_id=actor.id,
        full_name=payload.full_name,
        status=payload.status,
        roles=payload.roles,
    )
    await AuditService.log_from_request(
        session,
        request,
        action="user.update",
        resource_type="user",
        resource_id=str(user_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata=payload.model_dump(exclude_none=True),
    )
    return UserOut.model_validate(serialise_user(user))


@router.post("/{user_id}/password", response_model=MessageResponse)
async def reset_password(
    request: Request,
    user_id: uuid.UUID,
    payload: AdminPasswordReset,
    session: DbSession,
    actor: Annotated[Any, require(Perm.USER_WRITE)],
) -> MessageResponse:
    await user_service.reset_password(session, user_id=user_id, new_password=payload.new_password)
    await AuditService.log_from_request(
        session,
        request,
        action="user.reset_password",
        resource_type="user",
        resource_id=str(user_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return MessageResponse(message="Password reset. The user's existing sessions were revoked.")


@router.post("/{user_id}/unlock", response_model=UserOut)
async def unlock_user(
    request: Request,
    user_id: uuid.UUID,
    session: DbSession,
    actor: Annotated[Any, require(Perm.USER_WRITE)],
) -> UserOut:
    user = await user_service.unlock(session, user_id=user_id)
    await AuditService.log_from_request(
        session,
        request,
        action="user.unlock",
        resource_type="user",
        resource_id=str(user_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return UserOut.model_validate(serialise_user(user))
