"""User, role and refresh-token data access."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import Permission, RefreshToken, Role, User


def _base_user_query() -> Select:
    return select(User).options(selectinload(User.roles).selectinload(Role.permissions))


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        _base_user_query().where(func.lower(User.email) == email.strip().lower())
    )
    return result.scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(_base_user_query().where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_users(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    role: str | None = None,
) -> tuple[list[User], int]:
    query = _base_user_query()
    count_query = select(func.count()).select_from(User)
    if role:
        role_filter = User.roles.any(Role.code == role)
        query = query.where(role_filter)
        count_query = count_query.where(role_filter)
    if search:
        pattern = f"%{search.strip().lower()}%"
        clause = func.lower(User.email).like(pattern) | func.lower(User.full_name).like(pattern)
        query = query.where(clause)
        count_query = count_query.where(clause)
    if status:
        query = query.where(User.status == status)
        count_query = count_query.where(User.status == status)
    query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(query)).scalars().unique().all()
    total = int((await session.execute(count_query)).scalar_one())
    return list(rows), total


async def get_roles(session: AsyncSession, codes: list[str]) -> list[Role]:
    result = await session.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.code.in_(codes))
    )
    return list(result.scalars().unique().all())


async def list_roles(session: AsyncSession) -> list[Role]:
    result = await session.execute(
        select(Role).options(selectinload(Role.permissions)).order_by(Role.code)
    )
    return list(result.scalars().unique().all())


async def list_permissions(session: AsyncSession) -> list[Permission]:
    result = await session.execute(select(Permission).order_by(Permission.code))
    return list(result.scalars().all())


async def count_active_admins(session: AsyncSession, exclude_id: uuid.UUID | None = None) -> int:
    query = (
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(User.roles)
        .where(Role.code == "ADMIN", User.status == "ACTIVE")
    )
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return int((await session.execute(query)).scalar_one())


# ---------------------------------------------------------------- refresh tokens


async def get_refresh_token(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    result = await session.execute(
        select(RefreshToken)
        .options(
            selectinload(RefreshToken.user).selectinload(User.roles).selectinload(Role.permissions)
        )
        .where(RefreshToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> int:
    """Revoke every live token in a family (reuse-detection response)."""
    now = datetime.now(timezone.utc)
    rows = (
        (
            await session.execute(
                select(RefreshToken).where(
                    RefreshToken.family_id == family_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.revoked_at = now
    return len(rows)


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        (
            await session.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.revoked_at = now
    return len(rows)
