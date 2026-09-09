"""``/api/v1/drones`` — simulated UAV swarm telemetry, commands and injections."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession, require
from app.core.errors import ValidationError
from app.core.permissions import Perm
from app.repositories import drones as drone_repo
from app.schemas.drones import (
    COMMANDS,
    DroneCommandRequest,
    DroneEventOut,
    DroneOut,
    FormationRequest,
    InjectAttackRequest,
    MissionOut,
    SwarmStatusOut,
)
from app.services.audit_service import AuditService
from app.services.drone_service import drone_service
from app.simulation.engine import simulation_engine
from app.simulation.swarm import FORMATIONS

router = APIRouter(prefix="/drones", tags=["uav"])


@router.get("", response_model=SwarmStatusOut)
async def swarm_status(
    session: DbSession,
    _user: Annotated[Any, require(Perm.DRONE_READ)],
) -> SwarmStatusOut:
    payload = await drone_service.swarm_payload(session, simulator=simulation_engine.swarm)
    return SwarmStatusOut.model_validate(payload)


@router.get("/missions", response_model=list[MissionOut])
async def list_missions(
    session: DbSession,
    _user: Annotated[Any, require(Perm.DRONE_READ)],
) -> list[MissionOut]:
    return [MissionOut.model_validate(m) for m in await drone_repo.list_missions(session)]


@router.get("/events", response_model=list[DroneEventOut])
async def list_events(
    session: DbSession,
    _user: Annotated[Any, require(Perm.DRONE_READ)],
    drone_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=300)] = 60,
) -> list[DroneEventOut]:
    rows = await drone_repo.recent_events(session, limit=limit, drone_id=drone_id)
    return [DroneEventOut.model_validate(r) for r in rows]


@router.get("/{drone_id}", response_model=DroneOut)
async def get_drone(
    drone_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.DRONE_READ)],
) -> DroneOut:
    return DroneOut.model_validate(await drone_service.require_drone(session, drone_id))


@router.post("/{drone_id}/command")
async def command_drone(
    request: Request,
    drone_id: uuid.UUID,
    payload: DroneCommandRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.DRONE_COMMAND)],
) -> dict[str, Any]:
    """Issue a command to a **simulated** UAV.

    This does not and cannot control real aircraft.
    """
    await drone_service.require_drone(session, drone_id)
    action = payload.normalised()
    if action not in COMMANDS:
        raise ValidationError(f"Unsupported command '{action}'. Supported: {', '.join(COMMANDS)}")
    try:
        events = await simulation_engine.command_drone(drone_id, action)
    except RuntimeError as exc:
        raise ValidationError(str(exc)) from exc
    await AuditService.log_from_request(
        session,
        request,
        action="drone.command",
        resource_type="drone",
        resource_id=str(drone_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"command": action, "events": len(events)},
    )
    return {
        "accepted": bool(events),
        "command": action,
        "events": events,
        "notice": "Simulated UAV command. No real aircraft is involved.",
    }


@router.post("/formation")
async def set_formation(
    request: Request,
    payload: FormationRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.DRONE_COMMAND)],
) -> dict[str, Any]:
    formation = payload.formation.strip().upper()
    if formation not in FORMATIONS:
        raise ValidationError(
            f"Unsupported formation '{formation}'. Supported: {', '.join(FORMATIONS)}"
        )
    try:
        result = await simulation_engine.set_formation(formation)
    except (RuntimeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    await AuditService.log_from_request(
        session,
        request,
        action="drone.formation",
        resource_type="drone_mission",
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"formation": formation},
    )
    return result


@router.post("/inject/jamming")
async def inject_jamming(
    request: Request,
    payload: InjectAttackRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SECURITY_SIMULATE)],
) -> dict[str, Any]:
    await drone_service.require_drone(session, payload.drone_id)
    try:
        events = await simulation_engine.inject_jamming(
            payload.drone_id, payload.duration_seconds, actor_user_id=actor.id
        )
    except RuntimeError as exc:
        raise ValidationError(str(exc)) from exc
    await AuditService.log_from_request(
        session,
        request,
        action="security.inject_jamming",
        resource_type="drone",
        resource_id=str(payload.drone_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"duration_seconds": payload.duration_seconds},
    )
    return {
        "events": events,
        "notice": (
            "Simulated RF jamming. No radio signal is transmitted and no real spectrum is affected."
        ),
    }


@router.post("/inject/spoofing")
async def inject_spoofing(
    request: Request,
    payload: InjectAttackRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SECURITY_SIMULATE)],
) -> dict[str, Any]:
    await drone_service.require_drone(session, payload.drone_id)
    try:
        events = await simulation_engine.inject_spoofing(
            payload.drone_id, payload.duration_seconds, actor_user_id=actor.id
        )
    except RuntimeError as exc:
        raise ValidationError(str(exc)) from exc
    await AuditService.log_from_request(
        session,
        request,
        action="security.inject_spoofing",
        resource_type="drone",
        resource_id=str(payload.drone_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"duration_seconds": payload.duration_seconds},
    )
    return {
        "events": events,
        "notice": (
            "Simulated GNSS spoofing. Reported position diverges from true "
            "simulated position so the detection logic can be demonstrated."
        ),
    }
