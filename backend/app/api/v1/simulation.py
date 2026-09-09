"""``/api/v1/simulation`` — controls for the scenario engine."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession, require
from app.core.errors import ValidationError
from app.core.permissions import Perm
from app.repositories import system as system_repo
from app.schemas.system import (
    SimulationRunOut,
    SimulationScenarioRequest,
    SimulationSpeedRequest,
    SimulationStartRequest,
    SimulationStatusOut,
)
from app.services.audit_service import AuditService
from app.simulation.engine import SCENARIO_CATALOGUE, simulation_engine

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/status", response_model=SimulationStatusOut)
async def status(
    _user: Annotated[Any, require(Perm.SIMULATION_READ)],
) -> SimulationStatusOut:
    return SimulationStatusOut.model_validate(simulation_engine.status_payload())


@router.get("/scenarios")
async def scenarios(
    _user: Annotated[Any, require(Perm.SIMULATION_READ)],
) -> dict[str, Any]:
    return {
        "scenarios": SCENARIO_CATALOGUE,
        "speeds": [1, 2, 5, 10],
        "notice": (
            "Scenarios drive a physiological model, not recorded patient data. "
            "The same seed reproduces the same trajectory exactly."
        ),
    }


@router.get("/runs", response_model=list[SimulationRunOut])
async def runs(
    session: DbSession,
    _user: Annotated[Any, require(Perm.SIMULATION_READ)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SimulationRunOut]:
    return [
        SimulationRunOut.model_validate(r)
        for r in await system_repo.list_runs(session, limit=limit)
    ]


@router.post("/start", response_model=SimulationStatusOut)
async def start(
    request: Request,
    payload: SimulationStartRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SIMULATION_CONTROL)],
) -> SimulationStatusOut:
    await AuditService.log_from_request(
        session,
        request,
        action="simulation.start",
        resource_type="simulation_run",
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata=payload.model_dump(mode="json"),
    )
    await session.commit()
    try:
        result = await simulation_engine.start(
            scenario=payload.scenario,
            seed=payload.seed,
            speed=payload.speed,
            tick_seconds=payload.tick_seconds,
            sim_seconds_per_tick=payload.sim_seconds_per_tick,
            started_by_id=actor.id,
            reset_first=payload.reset_first,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return SimulationStatusOut.model_validate(result)


@router.post("/pause", response_model=SimulationStatusOut)
async def pause(
    request: Request,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SIMULATION_CONTROL)],
) -> SimulationStatusOut:
    await AuditService.log_from_request(
        session,
        request,
        action="simulation.pause",
        resource_type="simulation_run",
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    await session.commit()
    return SimulationStatusOut.model_validate(await simulation_engine.pause())


@router.post("/resume", response_model=SimulationStatusOut)
async def resume(
    request: Request,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SIMULATION_CONTROL)],
) -> SimulationStatusOut:
    await AuditService.log_from_request(
        session,
        request,
        action="simulation.resume",
        resource_type="simulation_run",
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    await session.commit()
    return SimulationStatusOut.model_validate(await simulation_engine.resume())


@router.post("/stop", response_model=SimulationStatusOut)
async def stop(
    request: Request,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SIMULATION_CONTROL)],
) -> SimulationStatusOut:
    await AuditService.log_from_request(
        session,
        request,
        action="simulation.stop",
        resource_type="simulation_run",
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    await session.commit()
    return SimulationStatusOut.model_validate(await simulation_engine.stop())


@router.post("/reset", response_model=SimulationStatusOut)
async def reset(
    request: Request,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SIMULATION_CONTROL)],
) -> SimulationStatusOut:
    """Stop and clear engine state. Persisted history is not deleted."""
    await AuditService.log_from_request(
        session,
        request,
        action="simulation.reset",
        resource_type="simulation_run",
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    await session.commit()
    return SimulationStatusOut.model_validate(await simulation_engine.reset())


@router.post("/speed", response_model=SimulationStatusOut)
async def set_speed(
    request: Request,
    payload: SimulationSpeedRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SIMULATION_CONTROL)],
) -> SimulationStatusOut:
    await AuditService.log_from_request(
        session,
        request,
        action="simulation.set_speed",
        resource_type="simulation_run",
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"speed": payload.speed},
    )
    await session.commit()
    try:
        result = await simulation_engine.set_speed(payload.speed)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return SimulationStatusOut.model_validate(result)


@router.post("/scenario", response_model=SimulationStatusOut)
async def set_scenario(
    request: Request,
    payload: SimulationScenarioRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SIMULATION_CONTROL)],
) -> SimulationStatusOut:
    await AuditService.log_from_request(
        session,
        request,
        action="simulation.set_scenario",
        resource_type="simulation_run",
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata=payload.model_dump(mode="json"),
    )
    await session.commit()
    try:
        result = await simulation_engine.set_scenario(payload.scenario, payload.personnel_id)
    except KeyError as exc:
        raise ValidationError(str(exc).strip("'")) from exc
    return SimulationStatusOut.model_validate(result)


@router.get("/data-source")
async def data_source(
    _user: Annotated[Any, require(Perm.SIMULATION_READ)],
) -> dict[str, Any]:
    """Describe the active data source — the hardware-integration seam."""
    from app.datasources.base import (
        EdgeDataSource,
        UAVDataSource,
        WearableDataSource,
    )
    from app.datasources.simulation import SimulationDataSource

    return {
        "active": SimulationDataSource().describe(),
        "declared_but_not_implemented": [
            {
                "name": cls.__name__,
                "kind": cls.kind.value,
                "status": "NOT_IMPLEMENTED",
                "note": (
                    "Declared so the integration contract is explicit. "
                    "Instantiating it raises NotImplementedError rather than "
                    "returning fabricated sensor data."
                ),
            }
            for cls in (WearableDataSource, UAVDataSource, EdgeDataSource)
        ],
    }


@router.get("/snapshot")
async def snapshot(
    _user: Annotated[Any, require(Perm.SIMULATION_READ)],
) -> dict[str, Any]:
    """Read-only probe of the current simulated instant (does not advance time)."""
    from app.datasources.simulation import SimulationDataSource

    samples = await SimulationDataSource().snapshot()
    return {
        "count": len(samples),
        "sim_clock_seconds": round(simulation_engine.sim_clock_seconds, 1),
        "samples": [
            {
                **{
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in s.to_row().items()
                    if k not in ("personnel_id", "simulation_run_id")
                },
                "personnel_id": str(s.personnel_id),
            }
            for s in samples
        ],
        "provenance": "SIMULATED",
    }
