"""DataSource abstraction — the hardware-integration seam.

Everything downstream of ingestion (risk engine, prediction service, alert
engine, digital twin, dashboard, WebSockets) consumes :class:`VitalSample` and
:class:`EnvironmentSample` and knows nothing about where they came from.

Today exactly one implementation exists: ``SimulationDataSource``. Future
hardware sources (wearables, UAV telemetry, edge devices) implement the same
interface and are declared in :class:`DataSourceKind`; they are intentionally
NOT implemented here, and nothing in the codebase pretends they are.

Adding one later requires no change to the risk engine, prediction service,
alert engine, twin builder or dashboard.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.models.enums import ActivityLevel, DataSourceKind


@dataclass(frozen=True)
class EnvironmentSample:
    """Ambient conditions at a location and time."""

    env_temp_c: float
    wind_kph: float
    altitude_m: float
    latitude: float
    longitude: float
    grid_x: int | None = None
    grid_y: int | None = None
    weather_risk: float = 0.0


@dataclass(frozen=True)
class VitalSample:
    """One personnel reading, independent of its origin.

    ``source`` is mandatory: provenance travels with the data all the way to
    the UI so simulated values can never be silently presented as measured.
    """

    personnel_id: UUID
    recorded_at: datetime
    heart_rate: float
    spo2: float
    body_temp_c: float
    respiratory_rate: float
    bp_systolic: float
    bp_diastolic: float
    fatigue_score: float
    activity_level: ActivityLevel
    environment: EnvironmentSample
    source: DataSourceKind = DataSourceKind.SIMULATION
    scenario: str | None = None
    simulation_run_id: UUID | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        """Flatten into ``vital_readings`` column form."""
        env = self.environment
        return {
            "personnel_id": self.personnel_id,
            "recorded_at": self.recorded_at,
            "heart_rate": round(self.heart_rate, 2),
            "spo2": round(self.spo2, 2),
            "body_temp_c": round(self.body_temp_c, 2),
            "respiratory_rate": round(self.respiratory_rate, 2),
            "bp_systolic": round(self.bp_systolic, 1),
            "bp_diastolic": round(self.bp_diastolic, 1),
            "altitude_m": round(env.altitude_m, 1),
            "fatigue_score": round(self.fatigue_score, 2),
            "activity_level": self.activity_level.value,
            "env_temp_c": round(env.env_temp_c, 2),
            "wind_kph": round(env.wind_kph, 2),
            "latitude": round(env.latitude, 6),
            "longitude": round(env.longitude, 6),
            "grid_x": env.grid_x,
            "grid_y": env.grid_y,
            "source": self.source.value,
            "scenario": self.scenario,
            "simulation_run_id": self.simulation_run_id,
        }


class DataSource(ABC):
    """Abstract provider of personnel telemetry."""

    #: Provenance stamped onto every sample this source produces.
    kind: DataSourceKind = DataSourceKind.SIMULATION

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def snapshot(self) -> list[VitalSample]:
        """Return the current reading for every tracked entity."""

    @abstractmethod
    def stream(self) -> AsyncIterator[list[VitalSample]]:
        """Yield batches of readings as they become available."""

    @property
    def is_simulated(self) -> bool:
        return self.kind is DataSourceKind.SIMULATION

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "is_simulated": self.is_simulated,
        }


# --------------------------------------------------------------------------
# Future hardware sources — declared for architectural clarity only.
#
# These are deliberately NOT implemented. They exist so the integration
# contract is explicit and reviewable. Instantiating one raises immediately
# rather than silently returning fabricated "sensor" data.
# --------------------------------------------------------------------------


class _UnimplementedHardwareSource(DataSource):
    """Base for declared-but-unimplemented hardware sources."""

    _integration_note = "Not implemented in this software-only prototype."

    def __init__(self, *_: Any, **__: Any) -> None:
        raise NotImplementedError(
            f"{type(self).__name__}: {self._integration_note} "
            "See docs/hardware-integration-roadmap.md."
        )

    @property
    def name(self) -> str:  # pragma: no cover - unreachable
        return type(self).__name__

    async def snapshot(self) -> list[VitalSample]:  # pragma: no cover
        raise NotImplementedError

    def stream(self) -> AsyncIterator[list[VitalSample]]:  # pragma: no cover
        raise NotImplementedError


class WearableDataSource(_UnimplementedHardwareSource):
    """Future: BLE/LoRa wearable vitals gateway."""

    kind = DataSourceKind.WEARABLE
    _integration_note = (
        "Future wearable integration. Would translate device frames into "
        "VitalSample and publish through the same ingestion service."
    )


class UAVDataSource(_UnimplementedHardwareSource):
    """Future: UAV telemetry and relayed personnel beacons."""

    kind = DataSourceKind.UAV
    _integration_note = (
        "Future UAV telemetry integration. Would supply position, environment "
        "and relayed personnel readings."
    )


class EdgeDataSource(_UnimplementedHardwareSource):
    """Future: on-site edge aggregator performing local inference."""

    kind = DataSourceKind.EDGE
    _integration_note = (
        "Future edge-device integration. Would batch and forward readings "
        "during connectivity windows."
    )


__all__ = [
    "DataSource",
    "EdgeDataSource",
    "EnvironmentSample",
    "UAVDataSource",
    "VitalSample",
    "WearableDataSource",
]
