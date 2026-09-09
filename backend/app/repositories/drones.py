"""UAV data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drones import Drone, DroneEvent, DroneMission


async def list_drones(session: AsyncSession) -> list[Drone]:
    result = await session.execute(select(Drone).order_by(Drone.call_sign))
    return list(result.scalars().all())


async def get_drone(session: AsyncSession, drone_id: uuid.UUID) -> Drone | None:
    return await session.get(Drone, drone_id)


async def active_mission(session: AsyncSession) -> DroneMission | None:
    result = await session.execute(
        select(DroneMission)
        .where(DroneMission.status.in_(("ACTIVE", "PLANNED")))
        .order_by(DroneMission.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_missions(session: AsyncSession) -> list[DroneMission]:
    result = await session.execute(select(DroneMission).order_by(DroneMission.created_at.desc()))
    return list(result.scalars().all())


async def recent_events(
    session: AsyncSession, *, limit: int = 50, drone_id: uuid.UUID | None = None
) -> list[DroneEvent]:
    query = select(DroneEvent)
    if drone_id is not None:
        query = query.where(DroneEvent.drone_id == drone_id)
    result = await session.execute(
        query.order_by(DroneEvent.created_at.desc(), DroneEvent.id.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def status_counts(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(select(Drone.status, func.count()).group_by(Drone.status))
    return {str(row[0]): int(row[1]) for row in result.all()}


async def comms_counts(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(Drone.comms_status, func.count()).group_by(Drone.comms_status)
    )
    return {str(row[0]): int(row[1]) for row in result.all()}
