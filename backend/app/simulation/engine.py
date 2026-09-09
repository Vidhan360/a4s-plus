"""The simulation engine: a single background loop that drives the prototype.

Responsibilities
----------------
* Owns one :class:`VitalsSimulator` per active person and one
  :class:`SwarmSimulator` for the UAV flight, plus the shared
  :class:`EnvironmentModel`.
* On every tick it advances simulated time, produces :class:`VitalSample`
  objects, and hands them to :class:`IngestionService` — the *same* code path a
  real hardware data source would use. The engine never writes vitals,
  risk scores, predictions or alerts itself.
* Supports START / PAUSE / RESUME / STOP / RESET, speed multipliers
  1x / 2x / 5x / 10x, per-person or global scenario changes, and fault
  injection (jamming, spoofing).
* Fully seeded: the same ``(seed, scenario, tick count)`` triple reproduces
  identical output, which ``tests/test_simulation.py`` asserts.

Wall-clock decoupling: one tick advances ``sim_seconds_per_tick`` of simulated
time and sleeps ``tick_seconds / speed`` seconds of real time. Speed therefore
changes how fast the world evolves in real time without changing the physics.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import session_scope
from app.core.events import Topic, get_event_bus
from app.core.logging import get_logger
from app.datasources.base import VitalSample
from app.models.enums import (
    Scenario,
    SecurityEventOrigin,
    SecurityEventType,
    SimulationStatus,
)
from app.models.system import SimulationRun
from app.repositories import drones as drone_repo
from app.repositories import personnel as personnel_repo
from app.repositories import system as system_repo
from app.services.alert_engine import AlertEngine
from app.services.config_service import config_service
from app.services.drone_service import drone_service
from app.services.ingestion_service import IngestionService
from app.services.security_service import SecurityService
from app.simulation.environment import EnvironmentModel
from app.simulation.swarm import FORMATIONS, SwarmSimulator, default_patrol_waypoints
from app.simulation.vitals import PersonProfile, VitalsSimulator

logger = get_logger(__name__)

VALID_SPEEDS = (1, 2, 5, 10)

SCENARIO_CATALOGUE: list[dict[str, str]] = [
    {
        "code": Scenario.NORMAL.value,
        "label": "Normal patrol",
        "description": (
            "Acclimatised personnel on a routine patrol. Vitals stay inside "
            "individual baselines; risk should remain LOW."
        ),
    },
    {
        "code": Scenario.GRADUAL_DETERIORATION.value,
        "label": "Gradual deterioration",
        "description": (
            "Slow-onset hypoxia and fatigue over hours. Designed to show the "
            "LSTM flagging elevated risk before the rule engine crosses its "
            "threshold."
        ),
    },
    {
        "code": Scenario.ACUTE_EVENT.value,
        "label": "Acute emergency",
        "description": (
            "Sudden collapse: SpO2 falls sharply with tachycardia and elevated "
            "respiratory rate. Escalates to CRITICAL within a few ticks."
        ),
    },
    {
        "code": Scenario.ALTITUDE_STRESS.value,
        "label": "Altitude sickness (AMS-like)",
        "description": (
            "Rapid ascent above acclimatisation, producing headache-pattern "
            "vitals: rising HR and respiratory rate with falling SpO2."
        ),
    },
    {
        "code": Scenario.RECOVERY.value,
        "label": "Recovery after descent",
        "description": (
            "Starts elevated, then improves following descent and rest — shows "
            "risk decreasing and alerts auto-resolving."
        ),
    },
    {
        "code": Scenario.MIXED.value,
        "label": "Mixed deployment",
        "description": (
            "Assigns a spread of the above profiles across the roster. This is "
            "the recommended demo scenario."
        ),
    },
]

#: Deterministic scenario spread used by the MIXED profile.
MIXED_ROTATION: tuple[Scenario, ...] = (
    Scenario.NORMAL,
    Scenario.GRADUAL_DETERIORATION,
    Scenario.NORMAL,
    Scenario.ALTITUDE_STRESS,
    Scenario.NORMAL,
    Scenario.ACUTE_EVENT,
    Scenario.RECOVERY,
    Scenario.NORMAL,
)


class SimulationEngine:
    """Single-instance orchestrator. Not safe to run two of these at once."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._resume_event = asyncio.Event()
        self._resume_event.set()

        self.status: SimulationStatus = SimulationStatus.IDLE
        self.run_id: uuid.UUID | None = None
        self.scenario_profile: Scenario = Scenario.MIXED
        self.seed: int = 20260909
        self.speed: int = 1
        self.tick_seconds: float = 5.0
        self.sim_seconds_per_tick: float = 60.0

        self.tick_count: int = 0
        self.sim_clock_seconds: float = 0.0
        self.sim_epoch: datetime = datetime.now(timezone.utc)
        self.wall_started_at: datetime | None = None
        self.last_tick_at: datetime | None = None
        self.last_tick_duration_ms: float = 0.0
        self.readings_emitted: int = 0
        self.alerts_raised: int = 0
        self.last_error: str | None = None

        self._env = EnvironmentModel(seed=self.seed)
        self._sims: dict[uuid.UUID, VitalsSimulator] = {}
        self._swarm: SwarmSimulator | None = None
        self._ingestion = IngestionService()
        self._origin = (35.42, 77.11, 250.0)

    # ------------------------------------------------------------------ state

    @property
    def is_running(self) -> bool:
        return self.status is SimulationStatus.RUNNING

    @property
    def swarm(self) -> SwarmSimulator | None:
        return self._swarm

    def sim_now(self) -> datetime:
        return self.sim_epoch + timedelta(seconds=self.sim_clock_seconds)

    def status_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "run_id": self.run_id,
            "scenario": self.scenario_profile.value,
            "seed": self.seed,
            "speed": self.speed,
            "tick_count": self.tick_count,
            "sim_clock_seconds": round(self.sim_clock_seconds, 1),
            "sim_clock_iso": self.sim_now(),
            "wall_started_at": self.wall_started_at,
            "last_tick_at": self.last_tick_at,
            "tick_seconds": self.tick_seconds,
            "sim_seconds_per_tick": self.sim_seconds_per_tick,
            "tracked_personnel": len(self._sims),
            "tracked_drones": len(self._swarm.drones) if self._swarm else 0,
            "readings_emitted": self.readings_emitted,
            "alerts_raised": self.alerts_raised,
            "last_tick_duration_ms": round(self.last_tick_duration_ms, 2),
            "scenario_assignments": {
                str(pid): sim.state.scenario.value for pid, sim in self._sims.items()
            },
            "available_scenarios": SCENARIO_CATALOGUE,
            "is_simulated": True,
        }

    # ------------------------------------------------------------- lifecycle

    async def start(
        self,
        *,
        scenario: Scenario = Scenario.MIXED,
        seed: int = 20260909,
        speed: int = 1,
        tick_seconds: float = 5.0,
        sim_seconds_per_tick: float = 60.0,
        started_by_id: uuid.UUID | None = None,
        reset_first: bool = True,
    ) -> dict[str, Any]:
        async with self._lock:
            if self.status is SimulationStatus.RUNNING:
                return self.status_payload()
            if self.status is SimulationStatus.PAUSED and not reset_first:
                self.status = SimulationStatus.RUNNING
                self._resume_event.set()
                return self.status_payload()

            if speed not in VALID_SPEEDS:
                raise ValueError(f"speed must be one of {VALID_SPEEDS}")

            await self._teardown_task()

            self.scenario_profile = scenario
            self.seed = seed
            self.speed = speed
            self.tick_seconds = tick_seconds
            self.sim_seconds_per_tick = sim_seconds_per_tick
            if reset_first:
                self.tick_count = 0
                self.sim_clock_seconds = 0.0
                self.readings_emitted = 0
                self.alerts_raised = 0
            self.sim_epoch = datetime.now(timezone.utc)
            self.wall_started_at = self.sim_epoch
            self.last_error = None
            self._env = EnvironmentModel(seed=seed)

            async with session_scope() as session:
                await self._build_world(session, scenario, seed)
                run = SimulationRun(
                    id=uuid.uuid4(),
                    scenario_profile=scenario.value,
                    seed=seed,
                    speed=speed,
                    status=SimulationStatus.RUNNING.value,
                    config={
                        "tick_seconds": tick_seconds,
                        "sim_seconds_per_tick": sim_seconds_per_tick,
                        "personnel": len(self._sims),
                        "drones": len(self._swarm.drones) if self._swarm else 0,
                    },
                    started_by_id=started_by_id,
                )
                session.add(run)
                await session.flush()
                self.run_id = run.id

            self.status = SimulationStatus.RUNNING
            self._stop_event = asyncio.Event()
            self._resume_event = asyncio.Event()
            self._resume_event.set()
            self._task = asyncio.create_task(self._loop(), name="a4s-simulation")
            logger.info(
                "simulation started",
                extra={
                    "extra": {
                        "run_id": str(self.run_id),
                        "scenario": scenario.value,
                        "seed": seed,
                        "speed": speed,
                    }
                },
            )
        await self._publish_status("simulation.started")
        return self.status_payload()

    async def pause(self) -> dict[str, Any]:
        async with self._lock:
            if self.status is not SimulationStatus.RUNNING:
                return self.status_payload()
            self.status = SimulationStatus.PAUSED
            self._resume_event.clear()
            await self._update_run_status(SimulationStatus.PAUSED)
        await self._publish_status("simulation.paused")
        return self.status_payload()

    async def resume(self) -> dict[str, Any]:
        async with self._lock:
            if self.status is not SimulationStatus.PAUSED:
                return self.status_payload()
            self.status = SimulationStatus.RUNNING
            self._resume_event.set()
            await self._update_run_status(SimulationStatus.RUNNING)
        await self._publish_status("simulation.resumed")
        return self.status_payload()

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if self.status in (SimulationStatus.IDLE, SimulationStatus.STOPPED):
                return self.status_payload()
            self.status = SimulationStatus.STOPPED
            self._resume_event.set()
            await self._teardown_task()
            await self._update_run_status(SimulationStatus.STOPPED, stopped=True)
        await self._publish_status("simulation.stopped")
        return self.status_payload()

    async def reset(self) -> dict[str, Any]:
        """Stop the loop, clear engine state and mark all twins stale.

        Persisted history is intentionally kept: the audit trail and analytics
        must not be erasable from the simulation controls.
        """
        async with self._lock:
            self.status = SimulationStatus.IDLE
            self._resume_event.set()
            await self._teardown_task()
            await self._update_run_status(SimulationStatus.STOPPED, stopped=True)
            self.run_id = None
            self.tick_count = 0
            self.sim_clock_seconds = 0.0
            self.readings_emitted = 0
            self.alerts_raised = 0
            self.last_tick_duration_ms = 0.0
            self.last_tick_at = None
            self.wall_started_at = None
            self._sims.clear()
            self._swarm = None
            self._env = EnvironmentModel(seed=self.seed)
            from app.services.twin_service import DigitalTwinService

            async with session_scope() as session:
                await DigitalTwinService().mark_all_stale(session)
        await self._publish_status("simulation.reset")
        return self.status_payload()

    async def set_speed(self, speed: int) -> dict[str, Any]:
        if speed not in VALID_SPEEDS:
            raise ValueError(f"speed must be one of {VALID_SPEEDS}")
        self.speed = speed
        async with session_scope() as session:
            run = await self._current_run(session)
            if run is not None:
                run.speed = speed
        await self._publish_status("simulation.speed_changed")
        return self.status_payload()

    async def set_scenario(
        self, scenario: Scenario, personnel_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        if personnel_id is not None:
            sim = self._sims.get(personnel_id)
            if sim is None:
                raise KeyError("Personnel is not tracked by the running simulation.")
            sim.set_scenario(scenario)
        else:
            self.scenario_profile = scenario
            if scenario is Scenario.MIXED:
                for index, sim in enumerate(self._sims.values()):
                    sim.set_scenario(MIXED_ROTATION[index % len(MIXED_ROTATION)])
            else:
                for sim in self._sims.values():
                    sim.set_scenario(scenario)
        async with session_scope() as session:
            run = await self._current_run(session)
            if run is not None and personnel_id is None:
                run.scenario_profile = scenario.value
        await self._publish_status("simulation.scenario_changed")
        return self.status_payload()

    # -------------------------------------------------------- fault injection

    async def inject_jamming(
        self,
        drone_id: uuid.UUID,
        duration_seconds: float = 300.0,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        return await self._inject(drone_id, "jamming", duration_seconds, actor_user_id)

    async def inject_spoofing(
        self,
        drone_id: uuid.UUID,
        duration_seconds: float = 300.0,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        return await self._inject(drone_id, "spoofing", duration_seconds, actor_user_id)

    async def _inject(
        self,
        drone_id: uuid.UUID,
        kind: str,
        duration_seconds: float,
        actor_user_id: uuid.UUID | None,
    ) -> list[dict[str, Any]]:
        if self._swarm is None:
            raise RuntimeError("The UAV swarm is not initialised. Start the simulation first.")
        events = (
            self._swarm.inject_jamming(drone_id, duration_seconds)
            if kind == "jamming"
            else self._swarm.inject_spoofing(drone_id, duration_seconds)
        )
        async with session_scope() as session:
            payloads = await drone_service.persist_events(
                session, events, alert_engine=await self._alert_engine(session)
            )
            await drone_service.persist_states(
                session,
                list(self._swarm.drones.values()),
                origin_lat=self._origin[0],
                origin_lon=self._origin[1],
                cell_size_m=self._origin[2],
            )
            await SecurityService.record(
                session,
                event_type=(
                    SecurityEventType.SIMULATED_JAMMING
                    if kind == "jamming"
                    else SecurityEventType.SIMULATED_SPOOFING
                ),
                origin=SecurityEventOrigin.SIMULATED,
                source="simulation.inject",
                title=f"Operator injected simulated {kind}",
                description=(
                    f"A {kind} scenario was injected against a simulated UAV for "
                    f"{duration_seconds:.0f} s of simulated time. This is a "
                    "demonstration of detection and response logic only."
                ),
                drone_id=drone_id,
                actor_user_id=actor_user_id,
                payload={"kind": kind, "duration_seconds": duration_seconds},
            )
        return payloads

    async def command_drone(self, drone_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
        if self._swarm is None:
            raise RuntimeError("The UAV swarm is not initialised. Start the simulation first.")
        events = self._swarm.command(drone_id, action)
        async with session_scope() as session:
            payloads = await drone_service.persist_events(session, events)
            await drone_service.persist_states(
                session,
                list(self._swarm.drones.values()),
                origin_lat=self._origin[0],
                origin_lon=self._origin[1],
                cell_size_m=self._origin[2],
            )
        return payloads

    async def set_formation(self, formation: str) -> dict[str, Any]:
        if self._swarm is None:
            raise RuntimeError("The UAV swarm is not initialised. Start the simulation first.")
        if formation not in FORMATIONS:
            raise ValueError(f"formation must be one of {FORMATIONS}")
        self._swarm.apply_formation(formation)
        return {"formation": self._swarm.formation}

    # ------------------------------------------------------------- world build

    async def _build_world(self, session: AsyncSession, scenario: Scenario, seed: int) -> None:
        from app.repositories import terrain as terrain_repo

        terrain_map = await terrain_repo.default_map(session)
        width = terrain_map.width if terrain_map else 64
        height = terrain_map.height if terrain_map else 64
        if terrain_map is not None:
            self._origin = (
                terrain_map.origin_lat,
                terrain_map.origin_lon,
                terrain_map.cell_size_m,
            )

        people = await personnel_repo.all_active_personnel(session)
        self._sims = {}
        for index, person in enumerate(people):
            assigned = (
                Scenario(person.sim_scenario)
                if person.sim_scenario
                else (
                    MIXED_ROTATION[index % len(MIXED_ROTATION)]
                    if scenario is Scenario.MIXED
                    else scenario
                )
            )
            if scenario is not Scenario.MIXED:
                assigned = scenario
            profile = PersonProfile(
                personnel_id=person.id,
                call_sign=person.call_sign,
                age=person.age,
                baseline_heart_rate=float(person.baseline_heart_rate),
                baseline_spo2=float(person.baseline_spo2),
                acclimatisation=0.35 + 0.5 * (((index * 37) % 13) / 12.0),
                fitness=0.4 + 0.5 * (((index * 53) % 11) / 10.0),
                start_altitude_m=4200.0 + 120.0 * (index % 7),
                grid_x=8 + (index * 5) % max(1, width - 16),
                grid_y=8 + (index * 7) % max(1, height - 16),
            )
            self._sims[person.id] = VitalsSimulator(
                profile=profile, scenario=assigned, seed=seed, index=index
            )

        waypoints = default_patrol_waypoints(width=width, height=height)
        states = await drone_service.load_states(session, waypoints=waypoints)
        mission = await drone_repo.active_mission(session)
        if states:
            self._swarm = SwarmSimulator(
                drones=states,
                seed=seed,
                formation=(mission.formation if mission else "WEDGE"),
                grid_width=width,
                grid_height=height,
                cell_size_m=self._origin[2],
            )
        else:
            self._swarm = None

    async def _alert_engine(self, session: AsyncSession) -> AlertEngine:
        return AlertEngine(await config_service.alert_rules(session))

    # -------------------------------------------------------------- main loop

    async def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                await self._resume_event.wait()
                if self._stop_event.is_set():
                    break
                started = time.perf_counter()
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    logger.exception("simulation tick failed")
                self.last_tick_duration_ms = (time.perf_counter() - started) * 1000.0
                delay = max(0.05, self.tick_seconds / max(1, self.speed))
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            pass

    async def _tick(self) -> None:
        dt = self.sim_seconds_per_tick
        self.sim_clock_seconds += dt
        self.tick_count += 1
        env_state = self._env.step(self.sim_clock_seconds)
        now = self.sim_now()

        samples: list[VitalSample] = []
        for sim in self._sims.values():
            sim.step(dt, env_state)
            samples.append(
                sim.sample(
                    recorded_at=now,
                    env=env_state,
                    origin_lat=self._origin[0],
                    origin_lon=self._origin[1],
                    cell_size_m=self._origin[2],
                    run_id=self.run_id,
                )
            )

        async with session_scope() as session:
            results = await self._ingestion.ingest_many(session, samples)
            self.readings_emitted += len(results)
            new_alerts = sum(len(r.new_alerts) for r in results)
            self.alerts_raised += new_alerts

            drone_payloads: list[dict[str, Any]] = []
            if self._swarm is not None:
                events = self._swarm.tick(dt, now)
                drone_payloads = await drone_service.persist_events(
                    session, events, alert_engine=await self._alert_engine(session)
                )
                await drone_service.persist_states(
                    session,
                    list(self._swarm.drones.values()),
                    origin_lat=self._origin[0],
                    origin_lon=self._origin[1],
                    cell_size_m=self._origin[2],
                )

            engine = await self._alert_engine(session)
            resolved = await engine.auto_resolve_stale(session, now)

            run = await self._current_run(session)
            if run is not None:
                run.tick_count = self.tick_count
                run.sim_clock_seconds = self.sim_clock_seconds
                run.last_tick_at = datetime.now(timezone.utc)

        self.last_tick_at = datetime.now(timezone.utc)
        await get_event_bus().publish(
            Topic.SIMULATION.value,
            "simulation.tick",
            {
                "tick": self.tick_count,
                "sim_clock_seconds": round(self.sim_clock_seconds, 1),
                "sim_clock_iso": now.isoformat(),
                "speed": self.speed,
                "readings": len(samples),
                "new_alerts": new_alerts,
                "auto_resolved": resolved,
                "drone_events": len(drone_payloads),
                "environment": env_state.as_dict(),
                "summaries": [r.summary() for r in results],
                "is_simulated": True,
            },
        )

    # ---------------------------------------------------------------- helpers

    async def _current_run(self, session: AsyncSession) -> SimulationRun | None:
        if self.run_id is None:
            return await system_repo.active_run(session)
        return await session.get(SimulationRun, self.run_id)

    async def _update_run_status(self, status: SimulationStatus, *, stopped: bool = False) -> None:
        async with session_scope() as session:
            run = await self._current_run(session)
            if run is None:
                return
            run.status = status.value
            run.tick_count = self.tick_count
            run.sim_clock_seconds = self.sim_clock_seconds
            if stopped:
                run.stopped_at = datetime.now(timezone.utc)

    async def _teardown_task(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        self._stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def _publish_status(self, event: str) -> None:
        payload = self.status_payload()
        payload["run_id"] = str(payload["run_id"]) if payload["run_id"] else None
        payload["sim_clock_iso"] = payload["sim_clock_iso"].isoformat()
        for key in ("wall_started_at", "last_tick_at"):
            value = payload.get(key)
            payload[key] = value.isoformat() if value else None
        await get_event_bus().publish(Topic.SIMULATION.value, event, payload)

    async def shutdown(self) -> None:
        self._resume_event.set()
        await self._teardown_task()


simulation_engine = SimulationEngine()
