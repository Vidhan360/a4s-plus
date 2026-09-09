"""Simulated UAV fleet, missions and UAV events.

Everything here is a software simulation. No real UAV is controlled, and no
telemetry link, radio or flight-control interface exists in this system.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    CommsStatus,
    DroneEventType,
    DroneStatus,
    MissionStatus,
    values,
)


def _check(column: str, enum_cls, name: str) -> CheckConstraint:
    allowed = ", ".join(repr(v) for v in values(enum_cls))
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


class DroneMission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "drone_missions"
    __table_args__ = (_check("status", MissionStatus, "drone_missions_status_valid"),)

    name: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    mission_type: Mapped[str] = mapped_column(String(32), nullable=False, default="PATROL")
    formation: Mapped[str] = mapped_column(String(32), nullable=False, default="LINE")
    #: Ordered [{x, y, altitude_m}] waypoints on the terrain grid.
    waypoints: Mapped[dict] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MissionStatus.ACTIVE.value
    )
    map_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("terrain_maps.id", ondelete="SET NULL")
    )

    drones: Mapped[list[Drone]] = relationship(back_populates="mission")


class Drone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "drones"
    __table_args__ = (
        _check("status", DroneStatus, "drones_status_valid"),
        _check("comms_status", CommsStatus, "drones_comms_status_valid"),
        CheckConstraint("battery_pct BETWEEN 0 AND 100", name="drones_battery_range"),
        CheckConstraint("signal_strength BETWEEN 0 AND 100", name="drones_signal_range"),
        CheckConstraint("heading_deg BETWEEN 0 AND 360", name="drones_heading_range"),
        Index("ix_drones_status_callsign", "status", "call_sign"),
    )

    call_sign: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="SIM-QUAD")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DroneStatus.ACTIVE.value, index=True
    )
    comms_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=CommsStatus.NOMINAL.value
    )
    battery_pct: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    altitude_m: Mapped[float] = mapped_column(Float, nullable=False, default=5200.0)
    heading_deg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    speed_mps: Mapped[float] = mapped_column(Float, nullable=False, default=12.0)
    signal_strength: Mapped[float] = mapped_column(Float, nullable=False, default=95.0)
    grid_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    grid_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latitude: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    waypoint_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: True while an injected jamming/spoofing effect is active.
    under_jamming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    under_spoofing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Reported (possibly falsified) position while spoofing is simulated.
    reported_grid_x: Mapped[float | None] = mapped_column(Float)
    reported_grid_y: Mapped[float | None] = mapped_column(Float)
    autonomous_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("drone_missions.id", ondelete="SET NULL"), index=True
    )
    last_telemetry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    mission: Mapped[DroneMission | None] = relationship(back_populates="drones")
    events: Mapped[list[DroneEvent]] = relationship(
        back_populates="drone", cascade="all, delete-orphan", passive_deletes=True
    )


class DroneEvent(Base):
    __tablename__ = "drone_events"
    __table_args__ = (
        _check("event_type", DroneEventType, "drone_events_type_valid"),
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'HIGH', 'CRITICAL')",
            name="drone_events_severity_valid",
        ),
        Index("ix_drone_events_drone_created", "drone_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    drone_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("drones.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    drone: Mapped[Drone] = relationship(back_populates="events")
