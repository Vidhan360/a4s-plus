"""UAV swarm persistence: syncs the simulator with ``drones``/``drone_events``.

The simulator owns physics; this service owns the database and the event
fan-out. Keeping them separate means a real MAVLink/telemetry adapter could
replace the simulator without touching persistence or the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Topic, get_event_bus
from app.models.drones import Drone, DroneEvent
from app.models.enums import (
    CommsStatus,
    DroneStatus,
    SecurityEventOrigin,
    SecurityEventType,
)
from app.repositories import drones as drone_repo
from app.services.alert_engine import AlertEngine
from app.services.security_service import SecurityService
from app.simulation.swarm import DroneEventOut, DroneState, SwarmSimulator

#: Drone events that also belong on the security monitor.
SECURITY_EVENT_MAP = {
    "JAMMING_DETECTED": SecurityEventType.SIMULATED_JAMMING,
    "SPOOFING_DETECTED": SecurityEventType.SIMULATED_SPOOFING,
}


def grid_to_latlon(
    grid_x: float, grid_y: float, origin_lat: float, origin_lon: float, cell_size_m: float
) -> tuple[float, float]:
    """Local flat-earth projection, adequate for a small synthetic AO."""
    metres_per_deg_lat = 111_320.0
    lat = origin_lat + (grid_y * cell_size_m) / metres_per_deg_lat
    import math

    metres_per_deg_lon = max(1.0, metres_per_deg_lat * math.cos(math.radians(origin_lat)))
    lon = origin_lon + (grid_x * cell_size_m) / metres_per_deg_lon
    return round(lat, 6), round(lon, 6)


class DroneService:
    async def load_states(
        self, session: AsyncSession, *, waypoints: list[tuple[float, float]]
    ) -> list[DroneState]:
        rows = await drone_repo.list_drones(session)
        states: list[DroneState] = []
        for row in rows:
            states.append(
                DroneState(
                    drone_id=row.id,
                    call_sign=row.call_sign,
                    grid_x=row.grid_x,
                    grid_y=row.grid_y,
                    altitude_m=row.altitude_m,
                    heading_deg=row.heading_deg,
                    speed_mps=row.speed_mps or 12.0,
                    battery_pct=row.battery_pct,
                    signal_strength=row.signal_strength,
                    status=DroneStatus(row.status),
                    comms_status=CommsStatus(row.comms_status),
                    waypoints=list(waypoints),
                    waypoint_index=row.waypoint_index,
                    under_jamming=row.under_jamming,
                    under_spoofing=row.under_spoofing,
                    reported_grid_x=row.reported_grid_x,
                    reported_grid_y=row.reported_grid_y,
                    autonomous_mode=row.autonomous_mode,
                )
            )
        return states

    async def persist_states(
        self,
        session: AsyncSession,
        states: list[DroneState],
        *,
        origin_lat: float = 35.42,
        origin_lon: float = 77.11,
        cell_size_m: float = 250.0,
    ) -> int:
        now = datetime.now(timezone.utc)
        by_id = {s.drone_id: s for s in states}
        rows = await drone_repo.list_drones(session)
        updated = 0
        for row in rows:
            state = by_id.get(row.id)
            if state is None:
                continue
            lat, lon = grid_to_latlon(
                state.grid_x, state.grid_y, origin_lat, origin_lon, cell_size_m
            )
            row.grid_x = round(state.grid_x, 3)
            row.grid_y = round(state.grid_y, 3)
            row.latitude = lat
            row.longitude = lon
            row.altitude_m = round(state.altitude_m, 1)
            row.heading_deg = round(state.heading_deg % 360.0, 1)
            row.speed_mps = round(state.speed_mps, 2)
            row.battery_pct = round(state.battery_pct, 2)
            row.signal_strength = round(state.signal_strength, 1)
            row.status = state.status.value
            row.comms_status = state.comms_status.value
            row.waypoint_index = state.waypoint_index
            row.under_jamming = state.under_jamming
            row.under_spoofing = state.under_spoofing
            row.reported_grid_x = (
                None if state.reported_grid_x is None else round(state.reported_grid_x, 3)
            )
            row.reported_grid_y = (
                None if state.reported_grid_y is None else round(state.reported_grid_y, 3)
            )
            row.autonomous_mode = state.autonomous_mode
            row.last_telemetry_at = now
            updated += 1
        await session.flush()
        return updated

    async def persist_events(
        self,
        session: AsyncSession,
        events: list[DroneEventOut],
        *,
        alert_engine: AlertEngine | None = None,
        publish: bool = True,
    ) -> list[dict[str, Any]]:
        if not events:
            return []
        payloads: list[dict[str, Any]] = []
        for event in events:
            row = DroneEvent(
                drone_id=event.drone_id,
                event_type=event.event_type.value,
                severity=event.severity,
                message=event.message,
                payload={**event.payload, "call_sign": event.call_sign},
            )
            session.add(row)
            payloads.append(
                {
                    "drone_id": str(event.drone_id),
                    "call_sign": event.call_sign,
                    "event_type": event.event_type.value,
                    "severity": event.severity,
                    "message": event.message,
                    "payload": event.payload,
                }
            )

            security_type = SECURITY_EVENT_MAP.get(event.event_type.value)
            if security_type is not None:
                await SecurityService.record(
                    session,
                    event_type=security_type,
                    origin=SecurityEventOrigin.SIMULATED,
                    source=f"uav.{event.call_sign}",
                    title=event.message,
                    description=(
                        "Simulated RF/GNSS interference generated by the UAV swarm "
                        "simulator. No real radio environment is involved."
                    ),
                    drone_id=event.drone_id,
                    payload=event.payload,
                    publish=publish,
                )

            if alert_engine is not None:
                for candidate in alert_engine.from_drone_event(event, event.call_sign):
                    await alert_engine.submit(session, candidate)

        await session.flush()
        if publish:
            await get_event_bus().publish(Topic.DRONES.value, "drone.events", {"events": payloads})
        return payloads

    async def swarm_payload(
        self,
        session: AsyncSession,
        *,
        simulator: SwarmSimulator | None = None,
        event_limit: int = 25,
    ) -> dict[str, Any]:
        rows = await drone_repo.list_drones(session)
        mission = await drone_repo.active_mission(session)
        events = await drone_repo.recent_events(session, limit=event_limit)
        return {
            "drones": rows,
            "formation": (
                simulator.formation
                if simulator is not None
                else (mission.formation if mission else "LINE")
            ),
            "counts": {
                "total": len(rows),
                "active": sum(1 for r in rows if r.status == DroneStatus.ACTIVE.value),
                "jammed": sum(1 for r in rows if r.under_jamming),
                "spoofed": sum(1 for r in rows if r.under_spoofing),
                "autonomous": sum(1 for r in rows if r.autonomous_mode),
                "comms_degraded": sum(
                    1 for r in rows if r.comms_status != CommsStatus.NOMINAL.value
                ),
                "low_battery": sum(1 for r in rows if r.battery_pct < 25.0),
            },
            "mission": mission,
            "recent_events": events,
            "is_simulated": True,
        }

    async def require_drone(self, session: AsyncSession, drone_id: uuid.UUID) -> Drone:
        from app.core.errors import NotFoundError

        row = await drone_repo.get_drone(session, drone_id)
        if row is None:
            raise NotFoundError("Drone not found.")
        return row


drone_service = DroneService()
