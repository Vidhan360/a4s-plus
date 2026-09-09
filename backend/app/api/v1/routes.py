"""``/api/v1/routes`` — A* safe-route planning and stored calculations."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession, PageParams, require
from app.core.permissions import Perm
from app.repositories import terrain as terrain_repo
from app.schemas.common import MessageResponse, page
from app.schemas.terrain import (
    RouteCalculationOut,
    RouteOut,
    RoutePlanRequest,
)
from app.services.audit_service import AuditService
from app.services.route_service import route_service

router = APIRouter(prefix="/routes", tags=["routes"])


@router.get("")
async def list_routes(
    session: DbSession,
    pagination: PageParams,
    _user: Annotated[Any, require(Perm.ROUTE_READ)],
    map_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    rows, total = await terrain_repo.list_routes(
        session, map_id=map_id, limit=pagination.limit, offset=pagination.offset
    )
    return page(
        [RouteOut.model_validate(r) for r in rows],
        total,
        pagination.limit,
        pagination.offset,
    )


@router.post("/plan", status_code=status.HTTP_201_CREATED)
async def plan(
    request: Request,
    payload: RoutePlanRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.ROUTE_PLAN)],
) -> dict[str, Any]:
    result = await route_service.plan(
        session,
        map_id=payload.map_id,
        name=payload.name,
        start=(payload.start_x, payload.start_y),
        goal=(payload.goal_x, payload.goal_y),
        enabled_layers=payload.enabled_layers,
        compare_shortest=payload.compare_shortest,
        persist=payload.persist,
        notes=payload.notes,
        created_by_id=actor.id,
    )
    route = result["route"]
    await AuditService.log_from_request(
        session,
        request,
        action="route.plan",
        resource_type="route",
        resource_id=str(route.id) if route is not None else None,
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={
            "start": [payload.start_x, payload.start_y],
            "goal": [payload.goal_x, payload.goal_y],
            "layers": payload.enabled_layers,
            "persisted": payload.persist,
        },
    )
    return {
        "route": RouteOut.model_validate(route) if route is not None else None,
        "safest": (
            RouteCalculationOut.model_validate(result["safest"])
            if payload.persist
            else result["safest"]
        ),
        "shortest": (
            RouteCalculationOut.model_validate(result["shortest"])
            if payload.persist and result["shortest"] is not None
            else result["shortest"]
        ),
        "comparison": result["comparison"],
        "hazard_alerts": result["hazard_alerts"],
        "is_synthetic_terrain": True,
        "map": {
            "id": str(result["terrain_map"].id),
            "name": result["terrain_map"].name,
            "width": result["terrain_map"].width,
            "height": result["terrain_map"].height,
            "cell_size_m": result["terrain_map"].cell_size_m,
        },
    }


@router.get("/verify-optimality")
async def verify_optimality(
    session: DbSession,
    _user: Annotated[Any, require(Perm.ROUTE_READ)],
    start_x: Annotated[int, Query(ge=0, le=4096)],
    start_y: Annotated[int, Query(ge=0, le=4096)],
    goal_x: Annotated[int, Query(ge=0, le=4096)],
    goal_y: Annotated[int, Query(ge=0, le=4096)],
    map_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    """Compare the A* cost against uninformed Dijkstra on the same graph.

    Exposed so the optimality claim can be checked live rather than trusted.
    """
    result = await route_service.verify_optimality(
        session, map_id=map_id, start=(start_x, start_y), goal=(goal_x, goal_y)
    )
    result["interpretation"] = (
        "Equal costs confirm the heuristic is admissible and the returned path "
        "is optimal for the configured weights."
        if result["optimal"]
        else "Costs differ — this would indicate a heuristic or graph bug."
    )
    return result


@router.get("/{route_id}", response_model=RouteOut)
async def get_route(
    route_id: uuid.UUID,
    session: DbSession,
    _user: Annotated[Any, require(Perm.ROUTE_READ)],
) -> RouteOut:
    return RouteOut.model_validate(await route_service.get_route(session, route_id))


@router.delete("/{route_id}", response_model=MessageResponse)
async def delete_route(
    request: Request,
    route_id: uuid.UUID,
    session: DbSession,
    actor: Annotated[Any, require(Perm.ROUTE_PLAN)],
) -> MessageResponse:
    await route_service.delete_route(session, route_id)
    await AuditService.log_from_request(
        session,
        request,
        action="route.delete",
        resource_type="route",
        resource_id=str(route_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return MessageResponse(message="Route deleted.")
