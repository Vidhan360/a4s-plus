"""Simulation engine internals: determinism, physiology and scenario shape.

Determinism is a hard requirement — the demo, the ML dataset and these tests
all depend on "same seed → same numbers". Every simulated sample must also
carry ``source=SIMULATION`` so provenance can never be lost.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from itertools import pairwise

import pytest

from app.models.enums import DataSourceKind, DroneStatus, Scenario
from app.schemas.drones import COMMANDS as API_COMMANDS
from app.simulation.environment import EnvironmentModel
from app.simulation.swarm import (
    FORMATIONS,
    DroneState,
    SwarmSimulator,
    default_patrol_waypoints,
)
from app.simulation.vitals import PersonProfile, VitalsSimulator, simulate_series

T0 = datetime(2026, 3, 1, 6, 0, tzinfo=timezone.utc)


def profile(index: int = 0) -> PersonProfile:
    return PersonProfile(
        personnel_id=uuid.UUID(int=index + 1),
        call_sign=f"TEST-{index:02d}",
        age=27,
        baseline_heart_rate=68.0,
        baseline_spo2=97.0,
        acclimatisation=0.6,
        fitness=0.65,
        start_altitude_m=4200.0,
    )


def series(scenario: Scenario, steps: int = 120, seed: int = 4242) -> list:
    return simulate_series(profile(), scenario, steps, 60.0, seed=seed, start_at=T0)


# ------------------------------------------------------------- determinism
@pytest.mark.parametrize("scenario", list(Scenario))
def test_same_seed_reproduces_the_series_exactly(scenario: Scenario) -> None:
    if scenario is Scenario.MIXED:
        pytest.skip("MIXED is an engine-level rotation, not a per-person scenario")
    a = series(scenario)
    b = series(scenario)
    assert [s.to_row() for s in a] == [s.to_row() for s in b]


def test_different_seeds_produce_different_series() -> None:
    a = series(Scenario.NORMAL, seed=1)
    b = series(Scenario.NORMAL, seed=2)
    assert [s.heart_rate for s in a] != [s.heart_rate for s in b]


def test_environment_model_is_deterministic() -> None:
    a = [EnvironmentModel(seed=9).step(i * 60.0).as_dict() for i in range(50)]
    b = [EnvironmentModel(seed=9).step(i * 60.0).as_dict() for i in range(50)]
    assert a == b


def test_environment_applies_a_lapse_rate_with_altitude() -> None:
    state = EnvironmentModel(seed=3).step(0.0)
    assert state.temp_at_altitude(6000.0) < state.temp_at_altitude(4000.0)
    assert state.visibility_km > 0
    assert 0.0 <= state.front_intensity <= 1.0


# ---------------------------------------------------------------- physiology
def test_every_sample_is_labelled_as_simulated() -> None:
    for sample in series(Scenario.NORMAL, steps=30):
        assert sample.source is DataSourceKind.SIMULATION
        assert sample.to_row()["source"] == DataSourceKind.SIMULATION.value


@pytest.mark.parametrize("scenario", [s for s in Scenario if s is not Scenario.MIXED])
def test_vitals_stay_inside_survivable_ranges(scenario: Scenario) -> None:
    for sample in series(scenario, steps=180):
        assert 30.0 <= sample.heart_rate <= 220.0
        assert 40.0 <= sample.spo2 <= 100.0
        assert 30.0 <= sample.body_temp_c <= 42.0
        assert 4.0 <= sample.respiratory_rate <= 60.0
        assert 60.0 <= sample.bp_systolic <= 230.0
        assert 0.0 <= sample.fatigue_score <= 100.0


def test_normal_scenario_stays_broadly_healthy() -> None:
    samples = series(Scenario.NORMAL, steps=180)
    mean_spo2 = sum(s.spo2 for s in samples) / len(samples)
    assert mean_spo2 > 88.0


def test_gradual_deterioration_trends_downward() -> None:
    samples = series(Scenario.GRADUAL_DETERIORATION, steps=180)
    first = sum(s.spo2 for s in samples[:20]) / 20
    last = sum(s.spo2 for s in samples[-20:]) / 20
    assert last < first - 2.0


def test_acute_event_produces_a_sharp_excursion() -> None:
    samples = series(Scenario.ACUTE_EVENT, steps=90)
    assert min(s.spo2 for s in samples) < 85.0
    assert max(s.heart_rate for s in samples) > 110.0


def test_altitude_stress_climbs() -> None:
    samples = series(Scenario.ALTITUDE_STRESS, steps=180)
    assert samples[-1].environment.altitude_m > samples[0].environment.altitude_m + 200.0


def test_recovery_scenario_improves_over_time() -> None:
    samples = series(Scenario.RECOVERY, steps=180)
    first = sum(s.spo2 for s in samples[:20]) / 20
    last = sum(s.spo2 for s in samples[-20:]) / 20
    assert last > first


def test_timestamps_are_monotonic_and_spaced_as_requested() -> None:
    samples = series(Scenario.NORMAL, steps=20)
    deltas = {(b.recorded_at - a.recorded_at).total_seconds() for a, b in pairwise(samples)}
    assert deltas == {60.0}


def test_scenario_change_takes_effect_immediately() -> None:
    sim = VitalsSimulator(profile(), Scenario.NORMAL, seed=5)
    env = EnvironmentModel(seed=5)
    for i in range(30):
        sim.step(60.0, env.step(i * 60.0))
    before = sim.state.stress
    sim.set_scenario(Scenario.RECOVERY)
    assert sim.state.scenario is Scenario.RECOVERY
    assert sim.state.stress >= before


# --------------------------------------------------------------- UAV swarm
def drones(count: int = 5) -> list[DroneState]:
    waypoints = default_patrol_waypoints(64, 64, count=6)
    return [
        DroneState(
            drone_id=uuid.UUID(int=100 + i),
            call_sign=f"EYE-{i:02d}",
            grid_x=6.0 + i,
            grid_y=6.0,
            altitude_m=4600.0,
            waypoints=list(waypoints),
        )
        for i in range(count)
    ]


def test_swarm_tick_is_deterministic() -> None:
    def run() -> list[dict]:
        sim = SwarmSimulator(drones(), seed=77)
        for _i in range(40):
            sim.tick(10.0, T0)
        return [d.as_dict() for d in sim.drones.values()]

    assert run() == run()


def test_drones_are_always_flagged_as_simulated() -> None:
    sim = SwarmSimulator(drones(), seed=1)
    assert all(d.as_dict()["is_simulated"] is True for d in sim.drones.values())


def test_drones_move_and_follow_waypoints() -> None:
    sim = SwarmSimulator(drones(3), seed=2)
    start = [(d.grid_x, d.grid_y) for d in sim.drones.values()]
    for _i in range(60):
        sim.tick(10.0, T0)
    moved = [(d.grid_x, d.grid_y) for d in sim.drones.values()]
    assert start != moved
    assert all(0 <= d.grid_x <= 64 and 0 <= d.grid_y <= 64 for d in sim.drones.values())


def test_battery_drains_monotonically() -> None:
    sim = SwarmSimulator(drones(2), seed=3)
    levels = []
    for _i in range(50):
        sim.tick(30.0, T0)
        levels.append(next(iter(sim.drones.values())).battery_pct)
    assert levels == sorted(levels, reverse=True)
    assert levels[-1] < 100.0


@pytest.mark.parametrize("formation", FORMATIONS)
def test_every_formation_assigns_distinct_offsets(formation: str) -> None:
    sim = SwarmSimulator(drones(5), seed=4, formation=formation)
    offsets = [d.formation_offset for d in sim.drones.values()]
    assert len(set(offsets)) == len(offsets)


def test_unknown_formation_is_rejected() -> None:
    sim = SwarmSimulator(drones(2), seed=4)
    with pytest.raises(ValueError):
        sim.apply_formation("SPIRAL")


def test_jamming_degrades_the_link_and_emits_an_event() -> None:
    sim = SwarmSimulator(drones(2), seed=5)
    target = next(iter(sim.drones.values()))
    before = target.signal_strength
    events = sim.inject_jamming(target.drone_id, duration_s=120.0)
    assert events
    assert target.under_jamming is True
    for _i in range(6):
        sim.tick(10.0, T0)
    assert target.signal_strength < before
    assert target.comms_status.value != "NOMINAL"


def test_jamming_expires_and_the_link_recovers() -> None:
    sim = SwarmSimulator(drones(2), seed=6)
    target = next(iter(sim.drones.values()))
    sim.inject_jamming(target.drone_id, duration_s=30.0)
    for _i in range(30):
        sim.tick(10.0, T0)
    assert target.under_jamming is False
    assert target.signal_strength > 0


def test_spoofing_makes_reported_position_diverge_from_truth() -> None:
    sim = SwarmSimulator(drones(2), seed=7)
    target = next(iter(sim.drones.values()))
    sim.inject_spoofing(target.drone_id, duration_s=200.0)
    sim.tick(10.0, T0)
    assert target.under_spoofing is True
    assert target.reported_grid_x is not None
    offset = abs(target.reported_grid_x - target.grid_x) + abs(
        (target.reported_grid_y or 0.0) - target.grid_y
    )
    assert offset > 0.0


def test_low_battery_triggers_autonomous_return_to_base() -> None:
    sim = SwarmSimulator(drones(1), seed=8)
    target = next(iter(sim.drones.values()))
    target.battery_pct = SwarmSimulator.RTB_BATTERY_PCT + 0.5
    seen = []
    for _i in range(20):
        seen.extend(sim.tick(30.0, T0))
    assert target.status in (DroneStatus.RETURNING, DroneStatus.OFFLINE)
    assert any("BATTERY" in e.event_type.value or "RTB" in e.event_type.value for e in seen)


def test_commands_are_validated() -> None:
    sim = SwarmSimulator(drones(1), seed=9)
    target = next(iter(sim.drones.values()))
    with pytest.raises(ValueError):
        sim.command(target.drone_id, "SELF_DESTRUCT")
    with pytest.raises(KeyError):
        sim.command(uuid.UUID(int=999), "HOLD")


def test_recall_command_sends_the_drone_home() -> None:
    sim = SwarmSimulator(drones(1), seed=10)
    target = next(iter(sim.drones.values()))
    events = sim.command(target.drone_id, "RETURN_TO_BASE")
    assert events
    assert target.status is DroneStatus.RETURNING


@pytest.mark.parametrize("action", API_COMMANDS)
def test_every_api_command_is_understood_by_the_simulator(action: str) -> None:
    """Guards against the transport layer and the simulator drifting apart."""
    sim = SwarmSimulator(drones(1), seed=11)
    target = next(iter(sim.drones.values()))
    if action == "LAUNCH":
        target.status = DroneStatus.OFFLINE
    assert sim.command(target.drone_id, action)


def test_launch_is_rejected_for_an_airborne_uav() -> None:
    sim = SwarmSimulator(drones(1), seed=12)
    target = next(iter(sim.drones.values()))
    with pytest.raises(ValueError):
        sim.command(target.drone_id, "LAUNCH")


def test_land_powers_the_uav_down() -> None:
    sim = SwarmSimulator(drones(1), seed=13)
    target = next(iter(sim.drones.values()))
    sim.command(target.drone_id, "LAND")
    assert target.status is DroneStatus.OFFLINE


def test_patrol_waypoints_form_a_closed_circuit_inside_the_grid() -> None:
    points = default_patrol_waypoints(64, 64, count=8)
    assert len(points) == 8
    assert all(0 < x < 64 and 0 < y < 64 for x, y in points)
