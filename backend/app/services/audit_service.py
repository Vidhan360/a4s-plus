"""Append-only audit logging.

The service exposes only ``log`` and read helpers — there is deliberately no
update or delete method anywhere in the application. The initial migration also
revokes UPDATE/DELETE on ``audit_logs`` from the application role on
PostgreSQL, so immutability is enforced by the database as well as by code.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.logging import get_logger
from app.models.enums import AuditResult
from app.models.system import AuditLog

logger = get_logger(__name__)

#: Header preferred for the client IP when running behind a trusted proxy.
FORWARDED_HEADER = "x-forwarded-for"


def audit_context(request: Request | None) -> dict[str, Any]:
    """Extract IP, user agent and request ID from the request, safely."""
    if request is None:
        return {"ip": None, "user_agent": None, "request_id": None}
    forwarded = request.headers.get(FORWARDED_HEADER, "")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return {
        "ip": (ip or None) if not ip or len(ip) <= 64 else ip[:64],
        "user_agent": (request.headers.get("user-agent") or "")[:255] or None,
        "request_id": getattr(request.state, "request_id", None),
    }


class AuditService:
    """Writes immutable audit records."""

    @staticmethod
    async def log(
        session: AsyncSession,
        *,
        action: str,
        resource_type: str,
        result: AuditResult | str = AuditResult.SUCCESS,
        actor_user_id: UUID | None = None,
        actor_email: str | None = None,
        resource_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            action=action[:128],
            resource_type=resource_type[:64],
            resource_id=None if resource_id is None else str(resource_id)[:64],
            result=(result.value if isinstance(result, AuditResult) else str(result)),
            ip=ip,
            user_agent=user_agent,
            request_id=request_id,
            meta=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        session.add(entry)
        await session.flush()
        return entry

    @staticmethod
    async def log_from_request(
        session: AsyncSession,
        request: Request | None,
        *,
        action: str,
        resource_type: str,
        result: AuditResult | str = AuditResult.SUCCESS,
        actor_user_id: UUID | None = None,
        actor_email: str | None = None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        ctx = audit_context(request)
        return await AuditService.log(
            session,
            action=action,
            resource_type=resource_type,
            result=result,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            resource_id=resource_id,
            metadata=metadata,
            **ctx,
        )

    @staticmethod
    async def log_background(
        *,
        actor_user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        result: str,
        ip: str | None,
        user_agent: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write an audit entry on its own session.

        Used by middleware, which runs after the request's session has already
        been committed and closed. Failures are logged and swallowed: auditing
        must never turn a successful request into an error response.
        """
        from app.core.database import SessionLocal

        try:
            async with SessionLocal() as session:
                await AuditService.log(
                    session,
                    action=action,
                    resource_type=resource_type,
                    result=result,
                    actor_user_id=actor_user_id,
                    resource_id=resource_id,
                    ip=ip,
                    user_agent=user_agent,
                    request_id=(metadata or {}).get("request_id"),
                    metadata=metadata,
                )
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("audit_write_failed", extra={"action": action})
