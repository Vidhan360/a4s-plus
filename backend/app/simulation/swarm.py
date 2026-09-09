"""UAV swarm simulation.

SOFTWARE SIMULATION ONLY. This module models UAV kinematics, battery drain,
link budget and the *effects* of jamming and spoofing on a simulated aircraft.

It contains no radio interface, no flight-control protocol, no transmitter
control and no real UAV connectivity of any kind. "Jamming" and "spoofing"
here mean: degrade the simulated link quality / falsify the simulated reported
position, so the platform's detection and response behaviour can be observed.
Nothing in this file can affect any physical device.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import numpy as np

from app.models.enums import CommsStatus, DroneEventType, DroneStatus

FORMATIONS: tuple[str, ...] = ("LINE", "WEDGE", "COLUMN", "DIAMOND")

#: Canonical operator commands the simulator understands.
SUPPORTED_COMMANDS: tuple[str, ...] = (
    "RETURN_TO_BASE",
    "RESUME_PATROL",
    "HOLD",
    "LAUNCH",
    "LAND",
)

#: Short forms accepted by the REST API, mapped onto the canonical names.
COMMAND_ALIASES: dict[str, str] = {
    "RTB": "RETURN_TO_BASE",
    "RESUME": "RESUME_PATROL",
}


@dataclass
class DroneEventOut:
    """An event emitted by the simulator, to be persisted and broadcast."""

    drone_id: UUID
    call_sign: str
    event_type: DroneEventType
    severity: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DroneState:
    drone_id: UUID
    call_sign: str
    grid_x: float
    grid_y: float
    altitude_m: float
    heading_deg: float = 0.0
    speed_mps: float = 12.0
    battery_pct: float = 100.0
    signal_strength: float = 95.0
    status: DroneStatus = DroneStatus.ACTIVE
    comms_status: CommsStatus = CommsStatus.NOMINAL
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    waypoint_index: int = 0
    #: Position within the formation, in cells, relative to the leader path.
    formation_offset: tuple[float, float] = (0.0, 0.0)
    under_jamming: bool = False
    under_spoofing: bool = False
    jam_remaining_s: float = 0.0
    spoof_remaining_s: float = 0.0
    reported_grid_x: float | None = None
    reported_grid_y: float | None = None
    autonomous_mode: bool = False
    base: tuple[float, float] = (4.0, 4.0)
    comms_lost_s: float = 0.0
    _low_battery_flagged: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.drone_id),
            "call_sign": self.call_sign,
            "grid_x": round(self.grid_x, 3),
            "grid_y": round(self.grid_y, 3),
            "altitude_m": round(self.altitude_m, 1),
            "heading_deg": round(self.heading_deg % 360.0, 1),
            "speed_mps": round(self.speed_mps, 2),
            "battery_pct": round(self.battery_pct, 2),
            "signal_strength": round(self.signal_strength, 1),
            "status": self.status.value,
            "comms_status": self.comms_status.value,
            "waypoint_index": self.waypoint_index,
            "under_jamming": self.under_jamming,
            "under_spoofing": self.under_spoofing,
            "reported_grid_x": (
                None if self.reported_grid_x is None else round(self.reported_grid_x, 3)
            ),
            "reported_grid_y": (
                None if self.reported_grid_y is None else round(self.reported_grid_y, 3)
            ),
            "autonomous_mode": self.autonomous_mode,
            "is_simulated": True,
        }


class SwarmSimulator:
    """Advances a fleet of simulated UAVs along patrol routes."""

    #: Battery level at which a UAV autonomously returns to base.
    RTB_BATTERY_PCT = 22.0
    LOW_BATTERY_PCT = 30.0
    #: Simulated seconds of continuous link loss before status goes OFFLINE.
    COMMS_LOST_TO_OFFLINE_S = 240.0

    def __init__(
        self,
        drones: list[DroneState],
        seed: int = 20260909,
        formation: str = "WEDGE",
        grid_width: int = 64,
        grid_height: int = 64,
        cell_size_m: float = 250.0,
    ) -> None:
        self.drones = {d.drone_id: d for d in drones}
        self.rng = np.random.default_rng(seed ^ 0xD8D8)
        self.formation = formation if formation in FORMATIONS else "WEDGE"
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.cell_size_m = cell_size_m
        self.apply_formation(self.formation)

    # ------------------------------------------------------------- formation
    def apply_formation(self, formation: str) -> None:
        """Assign per-drone offsets implementing the named formation."""
        if formation not in FORMATIONS:
            raise ValueError(f"Unknown formation {formation!r}. Expected one of {FORMATIONS}.")
        self.formation = formation
        order = sorted(self.drones.values(), key=lambda d: d.call_sign)
        for i, drone in enumerate(order):
            if formation == "LINE":
                drone.formation_offset = (0.0, (i - len(order) / 2) * 1.6)
            elif formation == "COLUMN":
                drone.formation_offset = (-(i * 1.6), 0.0)
            elif formation == "DIAMOND":
                ring = (i + 1) // 2
                side = 1 if i % 2 == 0 else -1
                drone.formation_offset = (-ring * 1.3, side * ring * 1.3)
            else:  # WEDGE
                rank = (i + 1) // 2
                side = 1 if i % 2 == 0 else -1
                drone.formation_offset = (-rank * 1.5, side * rank * 1.5)

    # ------------------------------------------------------------------ tick
    def tick(self, dt_seconds: float, now: datetime) -> list[DroneEventOut]:
        events: list[DroneEventOut] = []
        for drone in self.drones.values():
            events.extend(self._tick_one(drone, dt_seconds, now))
        return events

    def _tick_one(self, d: DroneState, dt: float, now: datetime) -> list[DroneEventOut]:
        events: list[DroneEventOut] = []

        if d.status is DroneStatus.OFFLINE and d.battery_pct <= 0.0:
            return events

        # --- expire injected effects ---
        if d.under_jamming:
            d.jam_remaining_s -= dt
            if d.jam_remaining_s <= 0:
                d.under_jamming = False
                d.jam_remaining_s = 0.0
                d.comms_status = CommsStatus.NOMINAL
                d.autonomous_mode = False
                if d.status is DroneStatus.JAMMED:
                    d.status = DroneStatus.ACTIVE
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.COMMS_RESTORED,
                        "INFO",
                        f"{d.call_sign}: simulated jamming ended, link restored and "
                        "operator control resumed.",
                        {"simulated": True},
                    )
                )
        if d.under_spoofing:
            d.spoof_remaining_s -= dt
            if d.spoof_remaining_s <= 0:
                d.under_spoofing = False
                d.spoof_remaining_s = 0.0
                d.reported_grid_x = None
                d.reported_grid_y = None
                if d.comms_status is CommsStatus.SPOOF_SUSPECTED:
                    d.comms_status = CommsStatus.NOMINAL
                if d.status is DroneStatus.ALERT:
                    d.status = DroneStatus.ACTIVE
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.COMMS_RESTORED,
                        "INFO",
                        f"{d.call_sign}: simulated position-spoofing ended, navigation "
                        "solution re-validated.",
                        {"simulated": True},
                    )
                )

        # --- battery ---
        drain_rate = 0.0016 * dt  # %/s at nominal cruise
        if d.status in (DroneStatus.ACTIVE, DroneStatus.RETURNING, DroneStatus.JAMMED):
            d.battery_pct = float(
                max(0.0, d.battery_pct - drain_rate * (1.0 + 0.5 * (d.speed_mps / 12.0)))
            )
        if (
            d.battery_pct <= self.LOW_BATTERY_PCT
            and not d._low_battery_flagged
            and d.status is not DroneStatus.OFFLINE
        ):
            d._low_battery_flagged = True
            events.append(
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.BATTERY_LOW,
                    "WARNING",
                    f"{d.call_sign}: battery at {d.battery_pct:.0f}% — below the "
                    f"{self.LOW_BATTERY_PCT:.0f}% advisory threshold.",
                    {"battery_pct": round(d.battery_pct, 1)},
                )
            )
        if d.battery_pct <= self.RTB_BATTERY_PCT and d.status is DroneStatus.ACTIVE:
            d.status = DroneStatus.RETURNING
            events.append(
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.RETURN_TO_BASE,
                    "WARNING",
                    f"{d.call_sign}: autonomous return-to-base triggered at "
                    f"{d.battery_pct:.0f}% battery.",
                    {"reason": "LOW_BATTERY", "battery_pct": round(d.battery_pct, 1)},
                )
            )
        if d.battery_pct <= 0.5 and d.status is not DroneStatus.OFFLINE:
            d.status = DroneStatus.OFFLINE
            d.comms_status = CommsStatus.LOST
            events.append(
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.LANDED,
                    "HIGH",
                    f"{d.call_sign}: battery exhausted — unit is offline.",
                    {"battery_pct": 0.0},
                )
            )
            return events

        # --- navigation target ---
        if d.status is DroneStatus.RETURNING:
            target = d.base
        elif d.waypoints:
            wp = d.waypoints[d.waypoint_index % len(d.waypoints)]
            target = (
                float(np.clip(wp[0] + d.formation_offset[0], 0, self.grid_width - 1)),
                float(np.clip(wp[1] + d.formation_offset[1], 0, self.grid_height - 1)),
            )
        else:
            target = (d.grid_x, d.grid_y)

        dx, dy = target[0] - d.grid_x, target[1] - d.grid_y
        dist_cells = math.hypot(dx, dy)

        if dist_cells < 0.35:
            if d.status is DroneStatus.RETURNING:
                d.status = DroneStatus.OFFLINE
                d.comms_status = CommsStatus.NOMINAL
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.LANDED,
                        "INFO",
                        f"{d.call_sign}: recovered at base and powered down.",
                        {"battery_pct": round(d.battery_pct, 1)},
                    )
                )
                return events
            if d.waypoints:
                d.waypoint_index = (d.waypoint_index + 1) % len(d.waypoints)
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.WAYPOINT_REACHED,
                        "INFO",
                        f"{d.call_sign}: reached waypoint {d.waypoint_index}.",
                        {"waypoint_index": d.waypoint_index},
                    )
                )
        else:
            # Move toward the target; jamming degrades navigation precision.
            step_cells = (d.speed_mps * dt) / self.cell_size_m
            step_cells = min(step_cells, dist_cells)
            ux, uy = dx / dist_cells, dy / dist_cells
            if d.under_jamming:
                wobble = float(self.rng.normal(0, 0.28))
                ux, uy = (
                    ux * math.cos(wobble) - uy * math.sin(wobble),
                    ux * math.sin(wobble) + uy * math.cos(wobble),
                )
            d.grid_x = float(np.clip(d.grid_x + ux * step_cells, 0, self.grid_width - 1))
            d.grid_y = float(np.clip(d.grid_y + uy * step_cells, 0, self.grid_height - 1))
            d.heading_deg = (math.degrees(math.atan2(uy, ux)) + 360.0) % 360.0

        # --- link budget ---
        base_dist = math.hypot(d.grid_x - d.base[0], d.grid_y - d.base[1])
        # Distance-dependent falloff from the base relay, plus noise. Tuned so
        # a nominal patrol circuit stays in the NOMINAL band and only genuine
        # range extension or injected jamming degrades the link.
        nominal = 100.0 - 0.52 * base_dist + float(self.rng.normal(0, 1.4))
        if d.under_jamming:
            nominal -= 62.0 + 14.0 * float(self.rng.random())
        d.signal_strength = float(np.clip(nominal, 0.0, 100.0))

        # --- comms state machine derived from link quality ---
        previous_comms = d.comms_status
        if d.under_spoofing:
            d.comms_status = CommsStatus.SPOOF_SUSPECTED
        elif d.signal_strength < 12.0:
            d.comms_status = CommsStatus.LOST
        elif d.signal_strength < 42.0:
            d.comms_status = CommsStatus.DEGRADED
        elif not d.under_jamming:
            d.comms_status = CommsStatus.NOMINAL

        if previous_comms != d.comms_status:
            if d.comms_status is CommsStatus.DEGRADED:
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.SIGNAL_DEGRADED,
                        "WARNING",
                        f"{d.call_sign}: link degraded to "
                        f"{d.signal_strength:.0f}% signal strength.",
                        {"signal_strength": round(d.signal_strength, 1)},
                    )
                )
            elif d.comms_status is CommsStatus.LOST:
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.COMMS_LOST,
                        "HIGH",
                        f"{d.call_sign}: command link lost — switching to autonomous "
                        "waypoint mode.",
                        {"signal_strength": round(d.signal_strength, 1)},
                    )
                )
                d.autonomous_mode = True
            elif d.comms_status is CommsStatus.NOMINAL and previous_comms in (
                CommsStatus.LOST,
                CommsStatus.DEGRADED,
            ):
                d.autonomous_mode = False
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.COMMS_RESTORED,
                        "INFO",
                        f"{d.call_sign}: link restored at "
                        f"{d.signal_strength:.0f}% signal strength.",
                        {"signal_strength": round(d.signal_strength, 1)},
                    )
                )

        # --- sustained loss escalates to OFFLINE ---
        if d.comms_status is CommsStatus.LOST:
            d.comms_lost_s += dt
            if d.comms_lost_s >= self.COMMS_LOST_TO_OFFLINE_S and d.status not in (
                DroneStatus.OFFLINE,
                DroneStatus.RETURNING,
            ):
                d.status = DroneStatus.RETURNING
                events.append(
                    DroneEventOut(
                        d.drone_id,
                        d.call_sign,
                        DroneEventType.RETURN_TO_BASE,
                        "HIGH",
                        f"{d.call_sign}: link lost for "
                        f"{d.comms_lost_s / 60:.0f} min — autonomous return-to-base "
                        "engaged as a lost-link contingency.",
                        {"reason": "LOST_LINK"},
                    )
                )
        else:
            d.comms_lost_s = 0.0

        # --- spoofed reported position drifts away from the true position ---
        if d.under_spoofing:
            if d.reported_grid_x is None:
                d.reported_grid_x, d.reported_grid_y = d.grid_x, d.grid_y
            d.reported_grid_x = float(
                np.clip(d.reported_grid_x + 0.02 * dt, 0, self.grid_width - 1)
            )
            d.reported_grid_y = float(
                np.clip((d.reported_grid_y or d.grid_y) + 0.014 * dt, 0, self.grid_height - 1)
            )

        d.altitude_m = float(np.clip(d.altitude_m + self.rng.normal(0, 1.1), 4600.0, 6200.0))
        return events

    # ------------------------------------------------------------- injection
    def inject_jamming(self, drone_id: UUID, duration_s: float = 300.0) -> list[DroneEventOut]:
        """Simulate a jamming effect on one UAV's command link."""
        d = self.drones.get(drone_id)
        if d is None:
            raise KeyError(f"Unknown drone {drone_id}")
        d.under_jamming = True
        d.jam_remaining_s = duration_s
        d.status = DroneStatus.JAMMED
        d.comms_status = CommsStatus.DEGRADED
        d.autonomous_mode = True
        return [
            DroneEventOut(
                d.drone_id,
                d.call_sign,
                DroneEventType.JAMMING_DETECTED,
                "CRITICAL",
                f"{d.call_sign}: simulated jamming detected — command link degraded, "
                "unit switched to autonomous waypoint mode.",
                {
                    "simulated": True,
                    "duration_s": duration_s,
                    "response": "AUTONOMOUS_MODE",
                },
            )
        ]

    def inject_spoofing(self, drone_id: UUID, duration_s: float = 300.0) -> list[DroneEventOut]:
        """Simulate falsified position reporting for one UAV."""
        d = self.drones.get(drone_id)
        if d is None:
            raise KeyError(f"Unknown drone {drone_id}")
        d.under_spoofing = True
        d.spoof_remaining_s = duration_s
        d.status = DroneStatus.ALERT
        d.comms_status = CommsStatus.SPOOF_SUSPECTED
        offset = float(self.rng.uniform(3.0, 7.0))
        d.reported_grid_x = float(np.clip(d.grid_x + offset, 0, self.grid_width - 1))
        d.reported_grid_y = float(np.clip(d.grid_y - offset * 0.6, 0, self.grid_height - 1))
        return [
            DroneEventOut(
                d.drone_id,
                d.call_sign,
                DroneEventType.SPOOFING_DETECTED,
                "CRITICAL",
                f"{d.call_sign}: simulated position spoofing detected — reported "
                "position diverges from the dead-reckoned solution; reported "
                "telemetry is being treated as untrusted.",
                {
                    "simulated": True,
                    "duration_s": duration_s,
                    "true_position": [round(d.grid_x, 2), round(d.grid_y, 2)],
                    "reported_position": [
                        round(d.reported_grid_x, 2),
                        round(d.reported_grid_y, 2),
                    ],
                    "response": "TELEMETRY_QUARANTINED",
                },
            )
        ]

    def command(self, drone_id: UUID, action: str) -> list[DroneEventOut]:
        """Apply a simulated operator command.

        The short forms used by the API (``RTB``, ``RESUME``) are accepted as
        aliases of the canonical names so the transport layer and the simulator
        can never drift apart.
        """
        d = self.drones.get(drone_id)
        if d is None:
            raise KeyError(f"Unknown drone {drone_id}")
        action = COMMAND_ALIASES.get(action.strip().upper(), action.strip().upper())
        if action == "LAUNCH":
            if d.status is not DroneStatus.OFFLINE:
                raise ValueError(
                    f"{d.call_sign} is already airborne (status {d.status.value}); "
                    "LAUNCH only applies to an OFFLINE UAV."
                )
            d.status = DroneStatus.ACTIVE
            d.autonomous_mode = False
            d.comms_status = CommsStatus.NOMINAL
            d.comms_lost_s = 0.0
            d.signal_strength = 95.0
            d.grid_x, d.grid_y = d.base
            return [
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.STATUS_CHANGE,
                    "INFO",
                    f"{d.call_sign}: launched from base under operator control.",
                    {"status": d.status.value},
                )
            ]
        if action == "LAND":
            d.status = DroneStatus.OFFLINE
            d.autonomous_mode = False
            d.speed_mps = 0.0
            return [
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.STATUS_CHANGE,
                    "INFO",
                    f"{d.call_sign}: landed and powered down.",
                    {"status": d.status.value},
                )
            ]
        if action == "RETURN_TO_BASE":
            d.status = DroneStatus.RETURNING
            return [
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.RETURN_TO_BASE,
                    "INFO",
                    f"{d.call_sign}: operator-commanded return-to-base.",
                    {"reason": "OPERATOR"},
                )
            ]
        if action == "RESUME_PATROL":
            d.status = DroneStatus.ACTIVE
            d.autonomous_mode = False
            return [
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.STATUS_CHANGE,
                    "INFO",
                    f"{d.call_sign}: patrol resumed under operator control.",
                    {"status": d.status.value},
                )
            ]
        if action == "HOLD":
            d.status = DroneStatus.ACTIVE
            d.waypoints = [(d.grid_x, d.grid_y)]
            return [
                DroneEventOut(
                    d.drone_id,
                    d.call_sign,
                    DroneEventType.STATUS_CHANGE,
                    "INFO",
                    f"{d.call_sign}: holding station at current position.",
                    {"status": "HOLD"},
                )
            ]
        raise ValueError(
            f"Unsupported command {action!r}. Expected one of: "
            f"{', '.join(sorted(SUPPORTED_COMMANDS))}."
        )


def default_patrol_waypoints(
    width: int = 64, height: int = 64, count: int = 6, inset: float = 0.16
) -> list[tuple[float, float]]:
    """A closed elliptical patrol circuit inside the grid."""
    cx, cy = width / 2.0, height / 2.0
    rx, ry = width * (0.5 - inset), height * (0.5 - inset)
    return [
        (
            round(cx + rx * math.cos(2 * math.pi * i / count), 2),
            round(cy + ry * math.sin(2 * math.pi * i / count), 2),
        )
        for i in range(count)
    ]
