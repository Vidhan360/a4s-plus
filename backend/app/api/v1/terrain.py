"""``/api/v1/terrain`` — synthetic terrain maps and dense layer payloads."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession, require
from app.core.errors import NotFoundError
from app.core.permissions import Perm
from app.repositories import terrain as terrain_repo
from app.schemas.common import MessageResponse
from app.schemas.terrain import (
    TerrainGridOut,
    TerrainMapGenerateRequest,
    TerrainMapOut,
)
from app.services.audit_service import AuditService
from app.services.terrain_service import TERRAIN_LEGEND, terrain_service

router = APIRouter(prefix="/terrain", tags=["terrain"])


@router.get("/maps", response_model=list[TerrainMapOut])
async def list_maps(
    session: DbSession,
    _user: Annotated[Any, require(Perm.TERRAIN_READ)],
) -> list[TerrainMapOut]:
    return [TerrainMapOut.model_validate(m) for m in await terrain_repo.list_maps(session)]


@router.get("/legend")
async def legend(_user: Annotated[Any, require(Perm.TERRAIN_READ)]) -> dict[str, Any]:
    return TERRAIN_LEGEND


@router.post("/maps", response_model=TerrainMapOut, status_code=status.HTTP_201_CREATED)
async def generate_map(
    request: Request,
    payload: TerrainMapGenerateRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.TERRAIN_WRITE)],
) -> TerrainMapOut:
    terrain_map = await terrain_service.generate_and_store(session, **payload.model_dump())
    await AuditService.log_from_request(
        session,
        request,
        action="terrain.generate",
        resource_type="terrain_map",
        resource_id=str(terrain_map.id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"seed": payload.seed, "size": f"{payload.width}x{payload.height}"},
    )
    return TerrainMapOut.model_validate(terrain_map)


@router.get("/grid", response_model=TerrainGridOut)
async def terrain_grid(
    session: DbSession,
    _user: Annotated[Any, require(Perm.TERRAIN_READ)],
    map_id: Annotated[uuid.UUID | None, Query()] = None,
) -> TerrainGridOut:
    """Dense layers for the canvas renderer. Defaults to the default map."""
    terrain_map = await terrain_service.require_map(session, map_id)
    payload = await terrain_service.grid_payload(session, terrain_map)
    return TerrainGridOut.model_validate(payload)


@router.get("/cell")
async def terrain_cell(
    session: DbSession,
    _user: Annotated[Any, require(Perm.TERRAIN_READ)],
    x: Annotated[int, Query(ge=0, le=4096)],
    y: Annotated[int, Query(ge=0, le=4096)],
    map_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    terrain_map = await terrain_service.require_map(session, map_id)
    cell = await terrain_repo.cell_at(session, terrain_map.id, x, y)
    if cell is None:
        raise NotFoundError(f"No terrain cell at ({x}, {y}).")
    return {
        "x": cell.x,
        "y": cell.y,
        "elevation_m": cell.elevation_m,
        "terrain_type": cell.terrain_type,
        "difficulty": cell.difficulty,
        "avalanche_risk": cell.avalanche_risk,
        "crevasse_risk": cell.crevasse_risk,
        "weather_risk": cell.weather_risk,
        "blocked": cell.blocked,
        "is_synthetic": True,
    }


@router.post("/maps/{map_id}/default", response_model=TerrainMapOut)
async def set_default_map(
    request: Request,
    map_id: uuid.UUID,
    session: DbSession,
    actor: Annotated[Any, require(Perm.TERRAIN_WRITE)],
) -> TerrainMapOut:
    terrain_map = await terrain_service.set_default(session, map_id)
    await AuditService.log_from_request(
        session,
        request,
        action="terrain.set_default",
        resource_type="terrain_map",
        resource_id=str(map_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return TerrainMapOut.model_validate(terrain_map)


@router.delete("/maps/{map_id}", response_model=MessageResponse)
async def delete_map(
    request: Request,
    map_id: uuid.UUID,
    session: DbSession,
    actor: Annotated[Any, require(Perm.TERRAIN_WRITE)],
) -> MessageResponse:
    await terrain_service.delete_map(session, map_id)
    await AuditService.log_from_request(
        session,
        request,
        action="terrain.delete",
        resource_type="terrain_map",
        resource_id=str(map_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return MessageResponse(message="Terrain map deleted.")
