"""User administration. Enforces the "never lock yourself out" invariants."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.permissions import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS, permissions_for_roles
from app.core.security import hash_password, validate_password_strength
from app.models.auth import User
from app.models.enums import UserStatus
from app.repositories import users as user_repo


def serialise_user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status,
        "roles": sorted(role.code for role in user.roles),
        "failed_login_count": user.failed_login_count,
        "locked_until": user.locked_until,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def role_catalogue() -> list[dict[str, Any]]:
    return [
        {
            "code": role.value,
            "name": role.value.replace("_", " ").title(),
            "description": ROLE_DESCRIPTIONS[role],
            "permissions": sorted(p.value for p in perms),
        }
        for role, perms in ROLE_PERMISSIONS.items()
    ]


class UserService:
    async def create(
        self,
        session: AsyncSession,
        *,
        email: str,
        full_name: str,
        password: str,
        roles: list[str],
    ) -> User:
        existing = await user_repo.get_user_by_email(session, email)
        if existing is not None:
            raise ConflictError(f"A user with email '{email}' already exists.")
        validate_password_strength(password)
        role_rows = await user_repo.get_roles(session, roles)
        found = {r.code for r in role_rows}
        missing = sorted(set(roles) - found)
        if missing:
            raise ValidationError(f"Role(s) not provisioned in the database: {', '.join(missing)}")
        user = User(
            id=uuid.uuid4(),
            email=email.strip().lower(),
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            status=UserStatus.ACTIVE.value,
            password_changed_at=datetime.now(timezone.utc),
        )
        user.roles = role_rows
        session.add(user)
        await session.flush()
        return user

    async def update(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        actor_id: uuid.UUID,
        full_name: str | None = None,
        status: str | None = None,
        roles: list[str] | None = None,
    ) -> User:
        user = await user_repo.get_user(session, user_id)
        if user is None:
            raise NotFoundError("User not found.")

        if full_name is not None:
            user.full_name = full_name.strip()

        if roles is not None:
            role_rows = await user_repo.get_roles(session, roles)
            missing = sorted(set(roles) - {r.code for r in role_rows})
            if missing:
                raise ValidationError(
                    f"Role(s) not provisioned in the database: {', '.join(missing)}"
                )
            losing_admin = "ADMIN" in {r.code for r in user.roles} and "ADMIN" not in roles
            if losing_admin:
                await self._assert_another_admin_remains(session, user_id, actor_id)
            user.roles = role_rows

        if status is not None and status != user.status:
            if status != UserStatus.ACTIVE.value:
                await self._assert_another_admin_remains(session, user_id, actor_id)
            user.status = status
            if status == UserStatus.ACTIVE.value:
                user.locked_until = None
                user.failed_login_count = 0

        await session.flush()
        return await user_repo.get_user(session, user_id) or user

    async def reset_password(
        self, session: AsyncSession, *, user_id: uuid.UUID, new_password: str
    ) -> User:
        user = await user_repo.get_user(session, user_id)
        if user is None:
            raise NotFoundError("User not found.")
        validate_password_strength(new_password)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        user.failed_login_count = 0
        user.locked_until = None
        if user.status == UserStatus.LOCKED.value:
            user.status = UserStatus.ACTIVE.value
        await user_repo.revoke_all_for_user(session, user.id)
        await session.flush()
        return user

    async def unlock(self, session: AsyncSession, *, user_id: uuid.UUID) -> User:
        user = await user_repo.get_user(session, user_id)
        if user is None:
            raise NotFoundError("User not found.")
        user.locked_until = None
        user.failed_login_count = 0
        if user.status == UserStatus.LOCKED.value:
            user.status = UserStatus.ACTIVE.value
        await session.flush()
        return user

    async def _assert_another_admin_remains(
        self, session: AsyncSession, user_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        remaining = await user_repo.count_active_admins(session, exclude_id=user_id)
        if remaining == 0:
            raise ConflictError(
                "This change would leave the workspace with no active administrator."
            )
        if user_id == actor_id:
            raise ConflictError(
                "Administrators cannot remove their own admin access or disable "
                "their own account. Ask another administrator."
            )


user_service = UserService()

__all__ = [
    "UserService",
    "permissions_for_roles",
    "role_catalogue",
    "serialise_user",
    "user_service",
]
