"""Personnel, vitals, risk, prediction and twin data access."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.personnel import (
    DigitalTwinState,
    HealthPrediction,
    Personnel,
    RiskAssessment,
    VitalReading,
)


async def get_personnel(session: AsyncSession, personnel_id: uuid.UUID) -> Personnel | None:
    return await session.get(Personnel, personnel_id)


async def get_by_call_sign(session: AsyncSession, call_sign: str) -> Personnel | None:
    result = await session.execute(
        select(Personnel).where(func.upper(Personnel.call_sign) == call_sign.upper())
    )
    return result.scalar_one_or_none()


async def list_personnel(
    session: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    unit: str | None = None,
    risk_category: str | None = None,
) -> tuple[list[tuple[Personnel, DigitalTwinState | None]], int]:
    """Roster rows joined to their digital-twin snapshot."""
    query = select(Personnel, DigitalTwinState).outerjoin(
        DigitalTwinState, DigitalTwinState.personnel_id == Personnel.id
    )
    count_query = (
        select(func.count())
        .select_from(Personnel)
        .outerjoin(DigitalTwinState, DigitalTwinState.personnel_id == Personnel.id)
    )
    clauses: list[ColumnElement[bool]] = []
    if search:
        pattern = f"%{search.strip().lower()}%"
        clauses.append(
            func.lower(Personnel.call_sign).like(pattern)
            | func.lower(Personnel.name).like(pattern)
            | func.lower(Personnel.unit).like(pattern)
        )
    if status:
        clauses.append(Personnel.status == status)
    if unit:
        clauses.append(func.lower(Personnel.unit) == unit.strip().lower())
    if risk_category:
        clauses.append(DigitalTwinState.risk_category == risk_category)
    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)
    query = (
        query.order_by(DigitalTwinState.risk_score.desc().nullslast(), Personnel.call_sign.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(query)).all()
    total = int((await session.execute(count_query)).scalar_one())
    return [(r[0], r[1]) for r in rows], total


async def all_active_personnel(session: AsyncSession) -> list[Personnel]:
    result = await session.execute(
        select(Personnel).where(Personnel.status == "ACTIVE").order_by(Personnel.call_sign)
    )
    return list(result.scalars().all())


async def recent_readings(
    session: AsyncSession,
    personnel_id: uuid.UUID,
    limit: int = 60,
    *,
    ascending: bool = True,
) -> list[VitalReading]:
    result = await session.execute(
        select(VitalReading)
        .where(VitalReading.personnel_id == personnel_id)
        .order_by(VitalReading.recorded_at.desc(), VitalReading.id.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return list(reversed(rows)) if ascending else rows


async def readings_between(
    session: AsyncSession,
    personnel_id: uuid.UUID | None,
    since: datetime,
    until: datetime | None = None,
    limit: int = 5000,
) -> list[VitalReading]:
    query = select(VitalReading).where(VitalReading.recorded_at >= since)
    if personnel_id is not None:
        query = query.where(VitalReading.personnel_id == personnel_id)
    if until is not None:
        query = query.where(VitalReading.recorded_at <= until)
    result = await session.execute(query.order_by(VitalReading.recorded_at.asc()).limit(limit))
    return list(result.scalars().all())


async def latest_reading(session: AsyncSession, personnel_id: uuid.UUID) -> VitalReading | None:
    result = await session.execute(
        select(VitalReading)
        .where(VitalReading.personnel_id == personnel_id)
        .order_by(VitalReading.recorded_at.desc(), VitalReading.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def risk_history(
    session: AsyncSession, personnel_id: uuid.UUID, limit: int = 120
) -> list[RiskAssessment]:
    result = await session.execute(
        select(RiskAssessment)
        .where(RiskAssessment.personnel_id == personnel_id)
        .order_by(RiskAssessment.created_at.desc())
        .limit(limit)
    )
    return list(reversed(list(result.scalars().all())))


async def latest_risk(session: AsyncSession, personnel_id: uuid.UUID) -> RiskAssessment | None:
    result = await session.execute(
        select(RiskAssessment)
        .where(RiskAssessment.personnel_id == personnel_id)
        .order_by(RiskAssessment.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def prediction_history(
    session: AsyncSession,
    personnel_id: uuid.UUID,
    limit: int = 50,
    model_name: str | None = None,
) -> list[HealthPrediction]:
    query = select(HealthPrediction).where(HealthPrediction.personnel_id == personnel_id)
    if model_name:
        query = query.where(HealthPrediction.model_name == model_name)
    result = await session.execute(query.order_by(HealthPrediction.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def risk_distribution(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(DigitalTwinState.risk_category, func.count())
        .where(DigitalTwinState.risk_category.isnot(None))
        .group_by(DigitalTwinState.risk_category)
    )
    return {str(row[0]): int(row[1]) for row in result.all()}


async def twin_rows(session: AsyncSession) -> list[DigitalTwinState]:
    result = await session.execute(
        select(DigitalTwinState).order_by(DigitalTwinState.risk_score.desc().nullslast())
    )
    return list(result.scalars().all())


async def counts(session: AsyncSession) -> dict[str, int]:
    total = int((await session.execute(select(func.count()).select_from(Personnel))).scalar_one())
    active = int(
        (
            await session.execute(
                select(func.count()).select_from(Personnel).where(Personnel.status == "ACTIVE")
            )
        ).scalar_one()
    )
    return {"total": total, "active": active}


async def readings_count_since(session: AsyncSession, hours: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(VitalReading)
                .where(VitalReading.recorded_at >= since)
            )
        ).scalar_one()
    )
