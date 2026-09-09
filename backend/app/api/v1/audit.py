"""``/api/v1/audit`` — append-only audit trail viewer.

There is deliberately no update or delete endpoint. The initial migration also
revokes UPDATE/DELETE on ``audit_logs`` from the application role, so even a
compromised application process cannot rewrite history.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession, PageParams, require
from app.core.permissions import Perm
from app.repositories import system as system_repo
from app.schemas.common import page
from app.schemas.system import AuditLogOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit_logs(
    session: DbSession,
    pagination: PageParams,
    _user: Annotated[Any, require(Perm.AUDIT_READ)],
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    result: Annotated[str | None, Query(max_length=16)] = None,
    actor_email: Annotated[str | None, Query(max_length=255)] = None,
    hours: Annotated[int | None, Query(ge=1, le=8760)] = None,
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours) if hours else None
    rows, total = await system_repo.list_audit_logs(
        session,
        limit=pagination.limit,
        offset=pagination.offset,
        action=action,
        resource_type=resource_type,
        result=result,
        actor_email=actor_email,
        since=since,
    )
    payload = page(
        [AuditLogOut.model_validate(r) for r in rows],
        total,
        pagination.limit,
        pagination.offset,
    )
    payload["immutability"] = (
        "Append-only. The API exposes no mutation path, and the database role "
        "used by the application has UPDATE and DELETE revoked on this table."
    )
    return payload


@router.get("/facets")
async def facets(
    session: DbSession,
    _user: Annotated[Any, require(Perm.AUDIT_READ)],
) -> dict[str, Any]:
    data = await system_repo.audit_action_facets(session)
    return {**data, "results": ["SUCCESS", "DENIED", "ERROR"]}
