"""Idempotent database seeding.

Run from ``backend/``::

    python -m seeds.seed              # roles, users, config, roster, terrain, UAVs
    python -m seeds.seed --history 90 # plus 90 simulated minutes of history
    python -m seeds.seed --only users

Seeding is idempotent: existing rows are matched by natural key and updated
rather than duplicated. Demo passwords are read from ``A4S_SEED_*_PASSWORD``;
if any is missing, user seeding aborts with an explanatory error instead of
inventing a default.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import insert as sa_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import session_scope
from app.core.permissions import (
    PERMISSION_DESCRIPTIONS,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSIONS,
)
from app.core.security import hash_password
from app.datasources.base import VitalSample
from app.models.auth import Permission, User
from app.models.auth import Role as RoleRow
from app.models.drones import Drone, DroneMission
from app.models.enums import (
    CommsStatus,
    DroneStatus,
    MissionStatus,
    Scenario,
    UserStatus,
)
from app.models.personnel import Personnel, RiskAssessment, VitalReading
from app.repositories import terrain as terrain_repo
from app.services.config_service import config_service
from app.services.ingestion_service import IngestionService
from app.services.risk_engine import VitalSnapshot
from app.services.terrain_service import terrain_service
from app.simulation.environment import EnvironmentModel
from app.simulation.swarm import default_patrol_waypoints
from app.simulation.vitals import PersonProfile, VitalsSimulator
from seeds.data import (
    SEED_DRONES,
    SEED_MISSION,
    SEED_PERSONNEL,
    SEED_TERRAIN,
    SEED_USERS,
)

STEPS = ("permissions", "users", "config", "personnel", "terrain", "uav", "history")


def log(message: str) -> None:
    print(f"[seed] {message}", flush=True)


# --------------------------------------------------------------------------
# Roles and permissions
# --------------------------------------------------------------------------


async def seed_permissions(session: AsyncSession) -> dict[str, int]:
    existing_perms = {
        row.code: row for row in (await session.execute(select(Permission))).scalars().all()
    }
    created_perms = 0
    for perm, description in PERMISSION_DESCRIPTIONS.items():
        row = existing_perms.get(perm.value)
        if row is None:
            row = Permission(id=uuid.uuid4(), code=perm.value, description=description)
            session.add(row)
            existing_perms[perm.value] = row
            created_perms += 1
        else:
            row.description = description
    await session.flush()

    existing_roles = {
        row.code: row
        for row in (
            await session.execute(select(RoleRow).options(selectinload(RoleRow.permissions)))
        )
        .scalars()
        .unique()
        .all()
    }
    created_roles = 0
    for role, perms in ROLE_PERMISSIONS.items():
        # Re-attach the permission set every run so code changes propagate.
        granted = [existing_perms[p.value] for p in sorted(perms)]
        role_row = existing_roles.get(role.value)
        if role_row is None:
            role_row = RoleRow(
                id=uuid.uuid4(),
                code=role.value,
                name=role.value.replace("_", " ").title(),
                description=ROLE_DESCRIPTIONS[role],
                permissions=granted,
            )
            session.add(role_row)
            created_roles += 1
        else:
            role_row.description = ROLE_DESCRIPTIONS[role]
            role_row.permissions = granted
    await session.flush()
    log(
        f"permissions: {len(PERMISSION_DESCRIPTIONS)} total "
        f"({created_perms} new); roles: {len(ROLE_PERMISSIONS)} total "
        f"({created_roles} new)"
    )
    return {"permissions": created_perms, "roles": created_roles}


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


def resolve_seed_passwords() -> dict[str, str]:
    missing: list[str] = []
    resolved: dict[str, str] = {}
    for spec in SEED_USERS:
        setting = spec["password_setting"]
        value = getattr(settings, setting, "") or ""
        if len(value) < 12:
            missing.append(f"A4S_{setting.upper()}")
        resolved[spec["email"]] = value
    if missing:
        raise SystemExit(
            "Cannot seed demo users: the following environment variables are "
            "unset or shorter than 12 characters:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nCopy .env.example to .env and set them. Passwords are never "
            "hard-coded in this repository."
        )
    return resolved


async def seed_users(session: AsyncSession) -> dict[str, Any]:
    passwords = resolve_seed_passwords()
    roles = {
        row.code: row
        for row in (
            await session.execute(select(RoleRow).options(selectinload(RoleRow.permissions)))
        )
        .scalars()
        .unique()
        .all()
    }
    if not roles:
        raise SystemExit("Roles are not seeded yet. Run the 'permissions' step first.")

    created: list[str] = []
    updated: list[str] = []
    for spec in SEED_USERS:
        email = spec["email"]
        row = (
            await session.execute(
                select(User)
                .options(selectinload(User.roles))
                .where(func.lower(User.email) == email.lower())
            )
        ).scalar_one_or_none()
        role_rows = [roles[code] for code in spec["roles"]]
        if row is None:
            row = User(
                id=uuid.uuid4(),
                email=email,
                full_name=spec["full_name"],
                password_hash=hash_password(passwords[email]),
                status=UserStatus.ACTIVE.value,
                password_changed_at=datetime.now(timezone.utc),
                roles=role_rows,
            )
            session.add(row)
            created.append(email)
        else:
            row.full_name = spec["full_name"]
            row.roles = role_rows
            row.status = UserStatus.ACTIVE.value
            row.failed_login_count = 0
            row.locked_until = None
            # Re-apply the configured password so a rotated .env takes effect.
            row.password_hash = hash_password(passwords[email])
            row.password_changed_at = datetime.now(timezone.utc)
            updated.append(email)
    await session.flush()
    log(f"users: {len(created)} created, {len(updated)} refreshed")
    return {"created": created, "updated": updated}


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


async def seed_config(session: AsyncSession) -> int:
    count = await config_service.seed_defaults(session)
    log(f"configuration: {count} key(s) present")
    return count


# --------------------------------------------------------------------------
# Personnel
# --------------------------------------------------------------------------


async def seed_personnel(session: AsyncSession) -> dict[str, Any]:
    created: list[str] = []
    updated: list[str] = []
    for spec in SEED_PERSONNEL:
        row = (
            await session.execute(select(Personnel).where(Personnel.call_sign == spec["call_sign"]))
        ).scalar_one_or_none()
        payload = {
            "name": spec["name"],
            "age": spec["age"],
            "unit": spec["unit"],
            "rank": spec.get("rank"),
            "baseline_heart_rate": spec["baseline_heart_rate"],
            "baseline_spo2": spec["baseline_spo2"],
            "sim_scenario": spec.get("sim_scenario"),
            "notes": spec.get("notes"),
            "status": spec.get("status", "ACTIVE"),
        }
        if row is None:
            session.add(Personnel(id=uuid.uuid4(), call_sign=spec["call_sign"], **payload))
            created.append(spec["call_sign"])
        else:
            for key, value in payload.items():
                setattr(row, key, value)
            updated.append(spec["call_sign"])
    await session.flush()
    log(f"personnel: {len(created)} created, {len(updated)} refreshed")
    return {"created": created, "updated": updated}


# --------------------------------------------------------------------------
# Terrain
# --------------------------------------------------------------------------


async def seed_terrain(session: AsyncSession) -> str:
    existing = (
        await session.execute(
            select(terrain_repo.TerrainMap).where(
                terrain_repo.TerrainMap.name == SEED_TERRAIN["name"]
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        cells = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(terrain_repo.TerrainCell)
                    .where(terrain_repo.TerrainCell.map_id == existing.id)
                )
            ).scalar_one()
        )
        log(f"terrain: '{existing.name}' already present ({cells} cells)")
        return str(existing.id)
    terrain_map = await terrain_service.generate_and_store(session, **SEED_TERRAIN)  # type: ignore[arg-type]
    log(
        f"terrain: generated '{terrain_map.name}' "
        f"{terrain_map.width}x{terrain_map.height} "
        f"({terrain_map.width * terrain_map.height} cells), "
        f"elevation {terrain_map.min_elevation_m:.0f}–"
        f"{terrain_map.max_elevation_m:.0f} m"
    )
    return str(terrain_map.id)


# --------------------------------------------------------------------------
# UAV swarm
# --------------------------------------------------------------------------


async def seed_uav(session: AsyncSession) -> dict[str, Any]:
    terrain_map = await terrain_repo.default_map(session)
    width = terrain_map.width if terrain_map else 64
    height = terrain_map.height if terrain_map else 64
    waypoints = default_patrol_waypoints(width=width, height=height)

    mission = (
        await session.execute(select(DroneMission).where(DroneMission.name == SEED_MISSION["name"]))
    ).scalar_one_or_none()
    if mission is None:
        mission = DroneMission(
            id=uuid.uuid4(),
            name=SEED_MISSION["name"],
            mission_type=SEED_MISSION["mission_type"],
            formation=SEED_MISSION["formation"],
            waypoints=[{"x": x, "y": y} for x, y in waypoints],
            status=MissionStatus.ACTIVE.value,
            map_id=terrain_map.id if terrain_map else None,
        )
        session.add(mission)
        await session.flush()

    created: list[str] = []
    for index, spec in enumerate(SEED_DRONES):
        row = (
            await session.execute(select(Drone).where(Drone.call_sign == spec["call_sign"]))
        ).scalar_one_or_none()
        start_x, start_y = waypoints[0]
        if row is None:
            row = Drone(
                id=uuid.uuid4(),
                call_sign=spec["call_sign"],
                model=spec["model"],
                status=DroneStatus.ACTIVE.value,
                comms_status=CommsStatus.NOMINAL.value,
                battery_pct=96.0 - index * 3.0,
                altitude_m=spec["altitude_m"],
                heading_deg=0.0,
                speed_mps=12.0,
                signal_strength=94.0 - index * 1.5,
                grid_x=start_x + index * 0.8,
                grid_y=start_y + index * 0.6,
                waypoint_index=0,
                mission_id=mission.id,
                is_simulated=True,
            )
            session.add(row)
            created.append(spec["call_sign"])
        else:
            row.mission_id = mission.id
            row.model = spec["model"]
    await session.flush()
    log(f"uav: mission '{mission.name}', {len(SEED_DRONES)} drones ({len(created)} new)")
    return {"mission_id": str(mission.id), "created": created}


# --------------------------------------------------------------------------
# Simulated history
# --------------------------------------------------------------------------


async def seed_history(session: AsyncSession, minutes: int) -> dict[str, Any]:
    """Backfill simulated readings so charts, analytics and the LSTM have data.

    Readings and rule-engine risk scores are written in bulk (no per-row
    prediction) for speed; the final reading of each person is then pushed
    through the *real* ingestion pipeline so risk, prediction, alerts and the
    digital twin are produced exactly as they are at runtime.
    """
    if minutes <= 0:
        return {"readings": 0}

    people = (
        (await session.execute(select(Personnel).order_by(Personnel.call_sign))).scalars().all()
    )
    if not people:
        log("history: no personnel; skipping")
        return {"readings": 0}

    terrain_map = await terrain_repo.default_map(session)
    origin_lat = terrain_map.origin_lat if terrain_map else 35.42
    origin_lon = terrain_map.origin_lon if terrain_map else 77.11
    cell_size = terrain_map.cell_size_m if terrain_map else 250.0
    width = terrain_map.width if terrain_map else 64
    height = terrain_map.height if terrain_map else 64

    engine = await config_service.risk_engine(session)
    env_model = EnvironmentModel(seed=settings.sim_default_seed)
    start_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    reading_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    last_samples: list[VitalSample] = []

    for index, person in enumerate(people):
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
        scenario = Scenario(person.sim_scenario) if person.sim_scenario else Scenario.NORMAL
        sim = VitalsSimulator(
            profile=profile,
            scenario=scenario,
            seed=settings.sim_default_seed,
            index=index,
        )
        history: list[VitalSnapshot] = []
        for step in range(minutes):
            env_state = env_model.step(step * 60.0)
            sim.step(60.0, env_state)
            sample = sim.sample(
                recorded_at=start_at + timedelta(minutes=step),
                env=env_state,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                cell_size_m=cell_size,
            )
            if step == minutes - 1:
                last_samples.append(sample)
                continue
            row = sample.to_row()
            # Bulk Core inserts bypass ORM defaults, so set the audit column.
            row["created_at"] = datetime.now(timezone.utc)
            reading_rows.append(row)
            snapshot = VitalSnapshot(
                heart_rate=row["heart_rate"],
                spo2=row["spo2"],
                body_temp_c=row["body_temp_c"],
                respiratory_rate=row["respiratory_rate"],
                bp_systolic=row["bp_systolic"],
                bp_diastolic=row["bp_diastolic"],
                altitude_m=row["altitude_m"],
                fatigue_score=row["fatigue_score"],
                activity_level=row["activity_level"],
                env_temp_c=row["env_temp_c"],
                wind_kph=row["wind_kph"],
                recorded_at=row["recorded_at"],
                baseline_heart_rate=float(person.baseline_heart_rate),
                baseline_spo2=float(person.baseline_spo2),
            )
            result = engine.evaluate(snapshot, history[-30:])
            history.append(snapshot)
            risk_rows.append(
                {
                    "id": uuid.uuid4(),
                    "personnel_id": person.id,
                    "vital_reading_id": None,
                    "risk_score": result.risk_score,
                    "category": result.category.value,
                    "engine": "RULE",
                    "factors": result.factors_payload(),
                    "config_version": result.config_version,
                    "created_at": row["recorded_at"],
                }
            )

    chunk = 2000
    for start in range(0, len(reading_rows), chunk):
        await session.execute(sa_insert(VitalReading), reading_rows[start : start + chunk])
    for start in range(0, len(risk_rows), chunk):
        await session.execute(sa_insert(RiskAssessment), risk_rows[start : start + chunk])
    await session.flush()

    ingestion = IngestionService()
    results = await ingestion.ingest_many(session, last_samples, publish=False)
    alerts = sum(len(r.new_alerts) for r in results)
    log(
        f"history: {len(reading_rows) + len(results)} readings, "
        f"{len(risk_rows)} bulk risk assessments, "
        f"{len(results)} pipeline runs, {alerts} alert(s) raised"
    )
    return {
        "readings": len(reading_rows) + len(results),
        "pipeline_runs": len(results),
        "alerts": alerts,
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def run(only: list[str], history_minutes: int) -> dict[str, Any]:
    """Run each step in its own transaction so partial progress is preserved."""
    steps = only or list(STEPS)
    handlers: dict[str, Any] = {
        "permissions": seed_permissions,
        "users": seed_users,
        "config": seed_config,
        "personnel": seed_personnel,
        "terrain": seed_terrain,
        "uav": seed_uav,
    }
    summary: dict[str, Any] = {}
    for step in STEPS:
        if step not in steps:
            continue
        if step == "history":
            if history_minutes <= 0:
                continue
            async with session_scope() as session:
                summary["history"] = await seed_history(session, history_minutes)
            continue
        async with session_scope() as session:
            summary[step] = await handlers[step](session)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the A4S+ database.")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=STEPS,
        default=None,
        help="Run only the named steps.",
    )
    parser.add_argument(
        "--history",
        type=int,
        default=0,
        help=(
            "Minutes of simulated history to backfill per person "
            "(recommended: 90, which gives the LSTM a full 24-step window)."
        ),
    )
    args = parser.parse_args(argv)
    summary = asyncio.run(run(args.only or [], args.history))
    log("done")
    log(f"summary: {summary}")
    log(
        "REMINDER: every value in this database is simulated. Nothing here is "
        "measured from a person, an aircraft or a real terrain survey."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
