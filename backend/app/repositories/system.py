"""Security event, audit log, configuration and simulation-run data access."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.auth import User
from app.models.enums import SecurityEventStatus, SecurityEventType, SimulationStatus
from app.models.system import AuditLog, SecurityEvent, SimulationRun, SystemConfiguration

OPEN_SECURITY_STATUSES = (
    SecurityEventStatus.NEW.value,
    SecurityEventStatus.INVESTIGATING.value,
)


async def list_security_events(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    severity: str | None = None,
    origin: str | None = None,
    status: str | None = None,
    event_type: str | None = None,
) -> tuple[list[SecurityEvent], int]:
    query = select(SecurityEvent)
    count_query = select(func.count()).select_from(SecurityEvent)
    clauses: list[ColumnElement[bool]] = []
    if severity:
        clauses.append(SecurityEvent.severity == severity)
    if origin:
        clauses.append(SecurityEvent.origin == origin)
    if status:
        clauses.append(SecurityEvent.status == status)
    if event_type:
        clauses.append(SecurityEvent.event_type == event_type)
    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)
    query = query.order_by(SecurityEvent.created_at.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(query)).scalars().all())
    total = int((await session.execute(count_query)).scalar_one())
    return rows, total


async def get_security_event(session: AsyncSession, event_id: uuid.UUID) -> SecurityEvent | None:
    return await session.get(SecurityEvent, event_id)


async def security_posture(session: AsyncSession) -> dict[str, object]:
    open_events = int(
        (
            await session.execute(
                select(func.count())
                .select_from(SecurityEvent)
                .where(SecurityEvent.status.in_(OPEN_SECURITY_STATUSES))
            )
        ).scalar_one()
    )
    by_severity = {
        str(r[0]): int(r[1])
        for r in (
            await session.execute(
                select(SecurityEvent.severity, func.count())
                .where(SecurityEvent.status.in_(OPEN_SECURITY_STATUSES))
                .group_by(SecurityEvent.severity)
            )
        ).all()
    }
    by_origin = {
        str(r[0]): int(r[1])
        for r in (
            await session.execute(
                select(SecurityEvent.origin, func.count()).group_by(SecurityEvent.origin)
            )
        ).all()
    }
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    failed_logins = int(
        (
            await session.execute(
                select(func.count())
                .select_from(SecurityEvent)
                .where(
                    SecurityEvent.event_type == SecurityEventType.FAILED_LOGIN.value,
                    SecurityEvent.created_at >= since,
                )
            )
        ).scalar_one()
    )
    locked = int(
        (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.locked_until.isnot(None),
                    User.locked_until > datetime.now(timezone.utc),
                )
            )
        ).scalar_one()
    )
    return {
        "open_events": open_events,
        "by_severity": by_severity,
        "by_origin": by_origin,
        "failed_logins_24h": failed_logins,
        "locked_accounts": locked,
    }


async def list_audit_logs(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    resource_type: str | None = None,
    result: str | None = None,
    actor_email: str | None = None,
    since: datetime | None = None,
) -> tuple[list[AuditLog], int]:
    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)
    clauses: list[ColumnElement[bool]] = []
    if action:
        clauses.append(AuditLog.action.like(f"%{action}%"))
    if resource_type:
        clauses.append(AuditLog.resource_type == resource_type)
    if result:
        clauses.append(AuditLog.result == result)
    if actor_email:
        clauses.append(func.lower(AuditLog.actor_email).like(f"%{actor_email.lower()}%"))
    if since:
        clauses.append(AuditLog.created_at >= since)
    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)
    query = query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(query)).scalars().all())
    total = int((await session.execute(count_query)).scalar_one())
    return rows, total


async def audit_action_facets(session: AsyncSession) -> dict[str, list[str]]:
    actions = [
        str(r[0])
        for r in (
            await session.execute(select(AuditLog.action).distinct().order_by(AuditLog.action))
        ).all()
    ]
    resources = [
        str(r[0])
        for r in (
            await session.execute(
                select(AuditLog.resource_type).distinct().order_by(AuditLog.resource_type)
            )
        ).all()
    ]
    return {"actions": actions, "resource_types": resources}


async def list_configs(session: AsyncSession) -> list[SystemConfiguration]:
    result = await session.execute(select(SystemConfiguration).order_by(SystemConfiguration.key))
    return list(result.scalars().all())


async def active_run(session: AsyncSession) -> SimulationRun | None:
    result = await session.execute(
        select(SimulationRun)
        .where(
            SimulationRun.status.in_(
                (SimulationStatus.RUNNING.value, SimulationStatus.PAUSED.value)
            )
        )
        .order_by(SimulationRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_runs(session: AsyncSession, limit: int = 20) -> list[SimulationRun]:
    result = await session.execute(
        select(SimulationRun).order_by(SimulationRun.started_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
