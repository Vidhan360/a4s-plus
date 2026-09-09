"""``/api/v1/alerts`` — alert feed, acknowledgement and resolution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession, PageParams, require
from app.core.errors import ConflictError, NotFoundError
from app.core.permissions import Perm
from app.models.enums import AlertSeverity, AlertStatus, AlertType
from app.repositories import alerts as alert_repo
from app.schemas.common import page
from app.schemas.personnel import (
    AlertAcknowledgeRequest,
    AlertOut,
    AlertResolveRequest,
)
from app.services.audit_service import AuditService
from app.services.config_service import config_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    session: DbSession,
    pagination: PageParams,
    _user: Annotated[Any, require(Perm.ALERT_READ)],
    alert_status: Annotated[AlertStatus | None, Query(alias="status")] = None,
    severity: Annotated[AlertSeverity | None, Query()] = None,
    alert_type: Annotated[AlertType | None, Query()] = None,
    personnel_id: uuid.UUID | None = None,
    open_only: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    rows, total = await alert_repo.list_alerts(
        session,
        limit=pagination.limit,
        offset=pagination.offset,
        status=alert_status.value if alert_status else None,
        severity=severity.value if severity else None,
        alert_type=alert_type.value if alert_type else None,
        personnel_id=personnel_id,
        open_only=open_only,
    )
    return page(
        [AlertOut.model_validate(r) for r in rows],
        total,
        pagination.limit,
        pagination.offset,
    )


@router.get("/summary")
async def alert_summary(
    session: DbSession,
    _user: Annotated[Any, require(Perm.ALERT_READ)],
) -> dict[str, Any]:
    return {
        "open": await alert_repo.open_count(session),
        "by_severity": await alert_repo.counts_by_severity(session),
        "by_type_24h": await alert_repo.counts_by_type(session, hours=24),
        "critical": [
            AlertOut.model_validate(r) for r in await alert_repo.critical_open(session, limit=10)
        ],
    }


@router.get("/rules")
async def alert_rules(
    session: DbSession,
    _user: Annotated[Any, require(Perm.ALERT_READ)],
) -> dict[str, Any]:
    """The live dedup / cooldown / escalation configuration."""
    rules = await config_service.alert_rules(session)
    return {
        "rules": rules,
        "behaviour": [
            "Candidates are keyed by a stable dedup key (person + condition).",
            "A repeat within the severity's cooldown increments occurrence_count "
            "instead of creating a new row.",
            "A repeat at a higher severity escalates the existing alert and "
            "records escalated_from.",
            "Alerts whose condition has cleared for the configured window are "
            "auto-resolved by the simulation loop.",
        ],
    }


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(
    alert_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.ALERT_READ)],
) -> AlertOut:
    row = await alert_repo.get_alert(session, alert_id)
    if row is None:
        raise NotFoundError("Alert not found.")
    return AlertOut.model_validate(row)


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    request: Request,
    alert_id: uuid.UUID,
    payload: AlertAcknowledgeRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.ALERT_ACK)],
) -> AlertOut:
    row = await alert_repo.get_alert(session, alert_id)
    if row is None:
        raise NotFoundError("Alert not found.")
    if row.status in (AlertStatus.RESOLVED.value, AlertStatus.SUPPRESSED.value):
        raise ConflictError(f"Alert is already {row.status.lower()}.")
    if row.status == AlertStatus.ACKNOWLEDGED.value:
        raise ConflictError("Alert has already been acknowledged.")
    row.status = AlertStatus.ACKNOWLEDGED.value
    row.acknowledged_by_id = actor.id
    row.acknowledged_at = datetime.now(timezone.utc)
    if payload.note:
        data = dict(row.triggering_data or {})
        data["acknowledgement_note"] = payload.note
        row.triggering_data = data
    await session.flush()
    await AuditService.log_from_request(
        session,
        request,
        action="alert.acknowledge",
        resource_type="health_alert",
        resource_id=str(alert_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"severity": row.severity, "alert_type": row.alert_type},
    )
    return AlertOut.model_validate(row)


@router.post("/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(
    request: Request,
    alert_id: uuid.UUID,
    payload: AlertResolveRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.ALERT_ACK)],
) -> AlertOut:
    row = await alert_repo.get_alert(session, alert_id)
    if row is None:
        raise NotFoundError("Alert not found.")
    if row.status == AlertStatus.RESOLVED.value:
        raise ConflictError("Alert is already resolved.")
    row.status = AlertStatus.RESOLVED.value
    row.resolved_by_id = actor.id
    row.resolved_at = datetime.now(timezone.utc)
    row.resolution_note = payload.resolution_note
    await session.flush()
    await AuditService.log_from_request(
        session,
        request,
        action="alert.resolve",
        resource_type="health_alert",
        resource_id=str(alert_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"severity": row.severity, "note": payload.resolution_note[:200]},
    )
    return AlertOut.model_validate(row)
