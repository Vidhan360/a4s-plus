"""Aggregates every v1 router plus the WebSocket endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, WebSocket

from app.api.v1 import (
    alerts,
    audit,
    auth,
    config,
    dashboard,
    drones,
    personnel,
    predictions,
    routes,
    security,
    simulation,
    system,
    terrain,
    users,
    vitals,
)
from app.ws import manager as ws_manager

api_router = APIRouter(prefix="/api/v1")

for module in (
    system,
    auth,
    users,
    personnel,
    vitals,
    predictions,
    alerts,
    terrain,
    routes,
    drones,
    security,
    audit,
    config,
    simulation,
    dashboard,
):
    api_router.include_router(module.router)


@api_router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
    topics: Annotated[str | None, Query()] = None,
) -> None:
    """Live event stream. Authenticate with ``?token=<access token>``."""
    await ws_manager.serve(websocket, token, topics)
