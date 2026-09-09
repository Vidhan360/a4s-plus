"""UAV swarm simulation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.simulation.swarm import FORMATIONS

from .common import ORMModel

COMMANDS = ("RTB", "RESUME", "HOLD", "LAUNCH", "LAND")


class DroneOut(ORMModel):
    id: UUID
    call_sign: str
    model: str
    status: str
    comms_status: str
    battery_pct: float
    altitude_m: float
    heading_deg: float
    speed_mps: float
    signal_strength: float
    grid_x: float
    grid_y: float
    latitude: float
    longitude: float
    waypoint_index: int
    under_jamming: bool
    under_spoofing: bool
    reported_grid_x: float | None
    reported_grid_y: float | None
    autonomous_mode: bool
    mission_id: UUID | None
    last_telemetry_at: datetime | None
    is_simulated: bool


class DroneEventOut(ORMModel):
    id: int
    drone_id: UUID
    event_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class MissionOut(ORMModel):
    id: UUID
    name: str
    mission_type: str
    formation: str
    waypoints: Any
    status: str
    map_id: UUID | None
    created_at: datetime


class DroneCommandRequest(BaseModel):
    action: str = Field(description=f"One of {', '.join(COMMANDS)}")

    def normalised(self) -> str:
        return self.action.strip().upper()


class FormationRequest(BaseModel):
    formation: str = Field(description=f"One of {', '.join(FORMATIONS)}")


class InjectAttackRequest(BaseModel):
    drone_id: UUID
    duration_seconds: float = Field(default=300.0, ge=10.0, le=3600.0)


class SwarmStatusOut(BaseModel):
    drones: list[DroneOut]
    formation: str
    counts: dict[str, int]
    mission: MissionOut | None = None
    recent_events: list[DroneEventOut] = Field(default_factory=list)
    is_simulated: bool = True
    notice: str = "Simulated UAV telemetry. This prototype does not command real aircraft."
