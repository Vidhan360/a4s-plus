"""Alert data access."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.enums import AlertStatus
from app.models.personnel import HealthAlert

OPEN_STATUSES = (AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value)


async def get_alert(session: AsyncSession, alert_id: uuid.UUID) -> HealthAlert | None:
    return await session.get(HealthAlert, alert_id)


async def list_alerts(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    severity: str | None = None,
    alert_type: str | None = None,
    personnel_id: uuid.UUID | None = None,
    open_only: bool = False,
) -> tuple[list[HealthAlert], int]:
    query = select(HealthAlert)
    count_query = select(func.count()).select_from(HealthAlert)
    clauses: list[ColumnElement[bool]] = []
    if open_only:
        clauses.append(HealthAlert.status.in_(OPEN_STATUSES))
    elif status:
        clauses.append(HealthAlert.status == status)
    if severity:
        clauses.append(HealthAlert.severity == severity)
    if alert_type:
        clauses.append(HealthAlert.alert_type == alert_type)
    if personnel_id:
        clauses.append(HealthAlert.personnel_id == personnel_id)
    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)
    query = query.order_by(HealthAlert.last_triggered_at.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(query)).scalars().all())
    total = int((await session.execute(count_query)).scalar_one())
    return rows, total


async def open_alerts_for(session: AsyncSession, personnel_id: uuid.UUID) -> list[HealthAlert]:
    result = await session.execute(
        select(HealthAlert)
        .where(
            HealthAlert.personnel_id == personnel_id,
            HealthAlert.status.in_(OPEN_STATUSES),
        )
        .order_by(HealthAlert.last_triggered_at.desc())
    )
    return list(result.scalars().all())


async def open_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(HealthAlert)
                .where(HealthAlert.status.in_(OPEN_STATUSES))
            )
        ).scalar_one()
    )


async def counts_by_severity(session: AsyncSession, open_only: bool = True) -> dict[str, int]:
    query = select(HealthAlert.severity, func.count()).group_by(HealthAlert.severity)
    if open_only:
        query = query.where(HealthAlert.status.in_(OPEN_STATUSES))
    result = await session.execute(query)
    return {str(row[0]): int(row[1]) for row in result.all()}


async def counts_by_type(session: AsyncSession, hours: int = 24) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(HealthAlert.alert_type, func.count())
        .where(HealthAlert.created_at >= since)
        .group_by(HealthAlert.alert_type)
    )
    return {str(row[0]): int(row[1]) for row in result.all()}


async def critical_open(session: AsyncSession, limit: int = 10) -> list[HealthAlert]:
    result = await session.execute(
        select(HealthAlert)
        .where(
            HealthAlert.status.in_(OPEN_STATUSES),
            HealthAlert.severity.in_(("CRITICAL", "EMERGENCY")),
        )
        .order_by(HealthAlert.last_triggered_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def since(session: AsyncSession, hours: int, limit: int = 5000) -> list[HealthAlert]:
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(HealthAlert)
        .where(HealthAlert.created_at >= start)
        .order_by(HealthAlert.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())
