"""``/api/v1/personnel`` — roster CRUD, detail, history and digital twin."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession, PageParams, require
from app.core.defaults import DATA_DISCLAIMER
from app.core.errors import NotFoundError
from app.core.permissions import Perm
from app.models.personnel import DigitalTwinState
from app.repositories import personnel as personnel_repo
from app.schemas.common import MessageResponse, page
from app.schemas.personnel import (
    AlertOut,
    DigitalTwinOut,
    HealthPredictionOut,
    PersonnelCreate,
    PersonnelOut,
    PersonnelSummary,
    PersonnelUpdate,
    RiskAssessmentOut,
    VitalReadingOut,
)
from app.services.audit_service import AuditService
from app.services.personnel_service import personnel_service, serialise_summary
from app.services.twin_service import DigitalTwinService

router = APIRouter(prefix="/personnel", tags=["personnel"])


async def _twin_payload(
    session: Any, personnel_id: uuid.UUID, state: dict[str, Any] | None
) -> DigitalTwinOut | None:
    """Wrap a raw twin state in the envelope both twin surfaces return.

    ``/personnel/{id}`` and ``/personnel/{id}/twin`` must agree on shape, so
    the envelope is built in exactly one place.
    """
    if state is None:
        return None
    row = await session.get(DigitalTwinState, personnel_id)
    return DigitalTwinOut(
        personnel_id=personnel_id,
        call_sign=(state.get("personnel") or {}).get("call_sign", ""),
        risk_score=row.risk_score if row else None,
        risk_category=row.risk_category if row else None,
        open_alert_count=row.open_alert_count if row else 0,
        is_stale=bool(state.get("is_stale")),
        updated_at=row.updated_at if row else None,
        state=state,
    )


twin_service = DigitalTwinService()


@router.get("")
async def list_personnel(
    session: DbSession,
    pagination: PageParams,
    _user: Annotated[Any, require(Perm.PERSONNEL_READ)],
    search: Annotated[str | None, Query(max_length=128)] = None,
    person_status: Annotated[str | None, Query(alias="status")] = None,
    unit: Annotated[str | None, Query(max_length=64)] = None,
    risk_category: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, Any]:
    items, total = await personnel_service.list(
        session,
        limit=pagination.limit,
        offset=pagination.offset,
        search=search,
        status=person_status,
        unit=unit,
        risk_category=risk_category,
    )
    return page(
        [PersonnelSummary.model_validate(row) for row in items],
        total,
        pagination.limit,
        pagination.offset,
    )


@router.post("", response_model=PersonnelOut, status_code=status.HTTP_201_CREATED)
async def create_personnel(
    request: Request,
    payload: PersonnelCreate,
    session: DbSession,
    actor: Annotated[Any, require(Perm.PERSONNEL_WRITE)],
) -> PersonnelOut:
    person = await personnel_service.create(session, payload.model_dump())
    await AuditService.log_from_request(
        session,
        request,
        action="personnel.create",
        resource_type="personnel",
        resource_id=str(person.id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"call_sign": person.call_sign},
    )
    return PersonnelOut.model_validate(person)


@router.get("/{personnel_id}")
async def get_personnel(
    personnel_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.PERSONNEL_READ)],
    history_limit: Annotated[int, Query(ge=1, le=500)] = 90,
) -> dict[str, Any]:
    detail = await personnel_service.detail(session, personnel_id, history_limit=history_limit)
    return {
        "personnel": PersonnelSummary.model_validate(detail["personnel"]),
        "readings": [VitalReadingOut.model_validate(r) for r in detail["readings"]],
        "risk_history": [RiskAssessmentOut.model_validate(r) for r in detail["risk_history"]],
        "predictions": [HealthPredictionOut.model_validate(p) for p in detail["predictions"]],
        "open_alerts": [AlertOut.model_validate(a) for a in detail["open_alerts"]],
        "twin": await _twin_payload(session, personnel_id, detail["twin"]),
    }


@router.patch("/{personnel_id}", response_model=PersonnelOut)
async def update_personnel(
    request: Request,
    personnel_id: uuid.UUID,
    payload: PersonnelUpdate,
    session: DbSession,
    actor: Annotated[Any, require(Perm.PERSONNEL_WRITE)],
) -> PersonnelOut:
    person = await personnel_service.update(
        session, personnel_id, payload.model_dump(exclude_unset=True)
    )
    await AuditService.log_from_request(
        session,
        request,
        action="personnel.update",
        resource_type="personnel",
        resource_id=str(personnel_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata=payload.model_dump(exclude_none=True, mode="json"),
    )
    return PersonnelOut.model_validate(person)


@router.delete("/{personnel_id}", response_model=MessageResponse)
async def delete_personnel(
    request: Request,
    personnel_id: uuid.UUID,
    session: DbSession,
    actor: Annotated[Any, require(Perm.PERSONNEL_DELETE)],
) -> MessageResponse:
    person = await personnel_service.get_or_404(session, personnel_id)
    call_sign = person.call_sign
    await personnel_service.delete(session, personnel_id)
    await AuditService.log_from_request(
        session,
        request,
        action="personnel.delete",
        resource_type="personnel",
        resource_id=str(personnel_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"call_sign": call_sign},
    )
    return MessageResponse(message=f"Personnel record {call_sign} deleted.")


@router.get("/{personnel_id}/vitals")
async def personnel_vitals(
    personnel_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.VITALS_READ)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 120,
) -> dict[str, Any]:
    await personnel_service.get_or_404(session, personnel_id)
    rows = await personnel_repo.recent_readings(session, personnel_id, limit=limit)
    return {
        "items": [VitalReadingOut.model_validate(r) for r in rows],
        "provenance": "SIMULATED",
        "notice": "All readings are generated by the simulation engine.",
    }


@router.get("/{personnel_id}/risk")
async def personnel_risk(
    personnel_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.HEALTH_READ)],
    limit: Annotated[int, Query(ge=1, le=500)] = 120,
) -> dict[str, Any]:
    await personnel_service.get_or_404(session, personnel_id)
    rows = await personnel_repo.risk_history(session, personnel_id, limit=limit)
    latest = rows[-1] if rows else None
    return {
        "items": [RiskAssessmentOut.model_validate(r) for r in rows],
        "latest": RiskAssessmentOut.model_validate(latest) if latest else None,
    }


@router.get("/{personnel_id}/twin", response_model=DigitalTwinOut)
async def personnel_twin(
    personnel_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.TWIN_READ)],
) -> DigitalTwinOut:
    await personnel_service.get_or_404(session, personnel_id)
    state = await twin_service.get(session, personnel_id)
    if state is None:
        raise NotFoundError(
            "No digital twin yet for this person. Start the simulation or "
            "ingest a reading to build one."
        )
    payload = await _twin_payload(session, personnel_id, state)
    assert payload is not None  # `state is None` was handled above
    return payload


@router.get("/summary/roster")
async def roster_summary(
    session: DbSession,
    _user: Annotated[Any, require(Perm.PERSONNEL_READ)],
) -> dict[str, Any]:
    """Compact roster for map overlays and pickers."""
    rows, total = await personnel_repo.list_personnel(session, limit=500, offset=0)
    by_status: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for person, twin in rows:
        by_status[person.status] = by_status.get(person.status, 0) + 1
        band = (twin.risk_category if twin else None) or "UNKNOWN"
        by_risk[band] = by_risk.get(band, 0) + 1
    return {
        "items": [
            {
                "id": str(p.id),
                "call_sign": p.call_sign,
                "name": p.name,
                "status": p.status,
                "unit": p.unit,
                "risk_score": t.risk_score if t else None,
                "risk_category": t.risk_category if t else None,
                "location": (((t.state or {}).get("location") or {}) if t else {}),
            }
            for p, t in rows
        ],
        "total": total,
        "by_status": by_status,
        "by_risk": by_risk,
        "disclaimer": DATA_DISCLAIMER,
    }


__all__ = ["router", "serialise_summary"]
