"""The one concrete :class:`DataSource` in this prototype.

It adapts the simulation engine to the same interface a wearable/UAV/edge
adapter would implement, so the ingestion pipeline has no simulation-specific
code in it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from app.datasources.base import DataSource, VitalSample
from app.models.enums import DataSourceKind


class SimulationDataSource(DataSource):
    """Reads samples out of the running :class:`SimulationEngine`."""

    kind = DataSourceKind.SIMULATION

    def __init__(self, engine: Any | None = None) -> None:
        if engine is None:
            from app.simulation.engine import simulation_engine

            engine = simulation_engine
        self._engine = engine

    @property
    def name(self) -> str:
        return "a4s-simulation-engine"

    async def snapshot(self) -> list[VitalSample]:
        """Sample every tracked person at the current simulated instant.

        This does not advance the world; it is a read-only probe used by
        ``GET /api/v1/simulation/snapshot``.
        """
        env = self._engine._env.step(self._engine.sim_clock_seconds)
        now = self._engine.sim_now()
        origin_lat, origin_lon, cell_size = self._engine._origin
        return [
            sim.sample(
                recorded_at=now,
                env=env,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                cell_size_m=cell_size,
                run_id=self._engine.run_id,
            )
            for sim in self._engine._sims.values()
        ]

    async def _iterate(self) -> AsyncIterator[list[VitalSample]]:
        while self._engine.is_running:
            yield await self.snapshot()
            await asyncio.sleep(max(0.05, self._engine.tick_seconds / max(1, self._engine.speed)))

    def stream(self) -> AsyncIterator[list[VitalSample]]:
        return self._iterate()

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "engine_status": self._engine.status.value,
            "tracked_personnel": len(self._engine._sims),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "notice": ("All samples are synthetic. No physical sensor is attached to this system."),
        }
