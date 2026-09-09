"""Personnel roster CRUD and detail assembly."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.personnel import DigitalTwinState, Personnel
from app.repositories import alerts as alert_repo
from app.repositories import personnel as personnel_repo
from app.services.twin_service import DigitalTwinService


def _twin_extras(twin: DigitalTwinState | None) -> dict[str, Any]:
    if twin is None:
        return {
            "risk_score": None,
            "risk_category": None,
            "open_alert_count": 0,
            "is_stale": False,
            "last_reading_at": None,
            "latest_vitals": None,
        }
    state = twin.state or {}
    vitals = state.get("vitals") or {}
    return {
        "risk_score": twin.risk_score,
        "risk_category": twin.risk_category,
        "open_alert_count": twin.open_alert_count,
        "is_stale": twin.is_stale,
        "last_reading_at": vitals.get("recorded_at"),
        "latest_vitals": vitals or None,
    }


def serialise_summary(person: Personnel, twin: DigitalTwinState | None) -> dict[str, Any]:
    base = {
        "id": person.id,
        "call_sign": person.call_sign,
        "name": person.name,
        "age": person.age,
        "unit": person.unit,
        "rank": person.rank,
        "status": person.status,
        "baseline_heart_rate": person.baseline_heart_rate,
        "baseline_spo2": person.baseline_spo2,
        "sim_scenario": person.sim_scenario,
        "notes": person.notes,
        "created_at": person.created_at,
        "updated_at": person.updated_at,
    }
    base.update(_twin_extras(twin))
    return base


class PersonnelService:
    def __init__(self, twin_service: DigitalTwinService | None = None) -> None:
        self.twins = twin_service or DigitalTwinService()

    async def list(self, session: AsyncSession, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        rows, total = await personnel_repo.list_personnel(session, **filters)
        return [serialise_summary(p, t) for p, t in rows], total

    async def get_or_404(self, session: AsyncSession, personnel_id: uuid.UUID) -> Personnel:
        person = await personnel_repo.get_personnel(session, personnel_id)
        if person is None:
            raise NotFoundError("Personnel record not found.")
        return person

    async def create(self, session: AsyncSession, data: dict[str, Any]) -> Personnel:
        call_sign = data["call_sign"]
        if await personnel_repo.get_by_call_sign(session, call_sign) is not None:
            raise ConflictError(f"Call sign '{call_sign}' is already in use.")
        payload = dict(data)
        status = payload.pop("status", None)
        scenario = payload.pop("sim_scenario", None)
        person = Personnel(
            id=uuid.uuid4(),
            status=getattr(status, "value", status) or "ACTIVE",
            sim_scenario=getattr(scenario, "value", scenario),
            **payload,
        )
        session.add(person)
        await session.flush()
        return person

    async def update(
        self, session: AsyncSession, personnel_id: uuid.UUID, data: dict[str, Any]
    ) -> Personnel:
        person = await self.get_or_404(session, personnel_id)
        for key, value in data.items():
            if value is None:
                continue
            setattr(person, key, getattr(value, "value", value))
        await session.flush()
        return person

    async def delete(self, session: AsyncSession, personnel_id: uuid.UUID) -> None:
        person = await self.get_or_404(session, personnel_id)
        await session.delete(person)
        await session.flush()

    async def detail(
        self, session: AsyncSession, personnel_id: uuid.UUID, *, history_limit: int = 90
    ) -> dict[str, Any]:
        person = await self.get_or_404(session, personnel_id)
        readings = await personnel_repo.recent_readings(session, personnel_id, limit=history_limit)
        risk_rows = await personnel_repo.risk_history(session, personnel_id, limit=history_limit)
        predictions = await personnel_repo.prediction_history(session, personnel_id, limit=30)
        open_alerts = await alert_repo.open_alerts_for(session, personnel_id)
        twin = await self.twins.get(session, personnel_id)
        return {
            "personnel": serialise_summary(
                person, await session.get(DigitalTwinState, personnel_id)
            ),
            "readings": readings,
            "risk_history": risk_rows,
            "predictions": predictions,
            "open_alerts": open_alerts,
            "twin": twin,
        }


personnel_service = PersonnelService()
