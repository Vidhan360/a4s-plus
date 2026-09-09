"""Static seed content. No passwords or secrets live here."""

from __future__ import annotations

from typing import Any

from app.core.permissions import Role
from app.models.enums import PersonnelStatus, Scenario

#: Demo accounts. Passwords come from A4S_SEED_*_PASSWORD environment
#: variables; seeding aborts if any is missing.
SEED_USERS: list[dict[str, Any]] = [
    {
        "email": "admin@a4s.local",
        "full_name": "Avani Rao",
        "roles": [Role.ADMIN.value],
        "password_setting": "seed_admin_password",
        "purpose": "Full platform administration, user management, configuration.",
    },
    {
        "email": "commander@a4s.local",
        "full_name": "Maj. Ishaan Bedi",
        "roles": [Role.COMMANDER.value],
        "password_setting": "seed_commander_password",
        "purpose": "Command dashboard, simulation control, routing, UAV commands.",
    },
    {
        "email": "medic@a4s.local",
        "full_name": "Capt. Leena Marak",
        "roles": [Role.MEDICAL_OFFICER.value],
        "password_setting": "seed_medical_password",
        "purpose": "Personnel health, predictions, alert acknowledgement.",
    },
    {
        "email": "operator@a4s.local",
        "full_name": "Sgt. Rohit Kalita",
        "roles": [Role.OPERATOR.value],
        "password_setting": "seed_operator_password",
        "purpose": "Simulation operation, UAV monitoring, route planning.",
    },
    {
        "email": "viewer@a4s.local",
        "full_name": "Observer Account",
        "roles": [Role.VIEWER.value],
        "password_setting": "seed_viewer_password",
        "purpose": "Read-only access for demonstrations and reviews.",
    },
]

#: 12 simulated personnel spanning the scenario catalogue.
SEED_PERSONNEL: list[dict[str, Any]] = [
    {
        "call_sign": "IBEX-01",
        "name": "Havildar Karan Thapa",
        "age": 31,
        "unit": "High Altitude Recon 1",
        "rank": "Havildar",
        "baseline_heart_rate": 58,
        "baseline_spo2": 97.5,
        "sim_scenario": Scenario.NORMAL.value,
        "notes": "Well acclimatised. Control case for the demo.",
    },
    {
        "call_sign": "IBEX-02",
        "name": "Naik Devendra Oraon",
        "age": 27,
        "unit": "High Altitude Recon 1",
        "rank": "Naik",
        "baseline_heart_rate": 62,
        "baseline_spo2": 97.0,
        "sim_scenario": Scenario.GRADUAL_DETERIORATION.value,
        "notes": "Shows the predictive lead time over the rule engine.",
    },
    {
        "call_sign": "IBEX-03",
        "name": "Sepoy Aman Bisht",
        "age": 23,
        "unit": "High Altitude Recon 1",
        "rank": "Sepoy",
        "baseline_heart_rate": 66,
        "baseline_spo2": 96.5,
        "sim_scenario": Scenario.ALTITUDE_STRESS.value,
        "notes": "Recent arrival; low acclimatisation.",
    },
    {
        "call_sign": "IBEX-04",
        "name": "Lance Naik Pritam Das",
        "age": 29,
        "unit": "High Altitude Recon 1",
        "rank": "Lance Naik",
        "baseline_heart_rate": 60,
        "baseline_spo2": 97.2,
        "sim_scenario": Scenario.NORMAL.value,
    },
    {
        "call_sign": "SNOWCAT-11",
        "name": "Havildar Yeshe Dorji",
        "age": 34,
        "unit": "Glacier Patrol 2",
        "rank": "Havildar",
        "baseline_heart_rate": 56,
        "baseline_spo2": 98.0,
        "sim_scenario": Scenario.NORMAL.value,
        "notes": "Local highlander; strongest acclimatisation on the roster.",
    },
    {
        "call_sign": "SNOWCAT-12",
        "name": "Sepoy Nitin Yadav",
        "age": 22,
        "unit": "Glacier Patrol 2",
        "rank": "Sepoy",
        "baseline_heart_rate": 70,
        "baseline_spo2": 96.0,
        "sim_scenario": Scenario.ACUTE_EVENT.value,
        "notes": "Acute deterioration case used for the escalation demo.",
    },
    {
        "call_sign": "SNOWCAT-13",
        "name": "Naik Bhaskar Rane",
        "age": 30,
        "unit": "Glacier Patrol 2",
        "rank": "Naik",
        "baseline_heart_rate": 64,
        "baseline_spo2": 97.0,
        "sim_scenario": Scenario.RECOVERY.value,
        "notes": "Recovering after a descent; shows alerts auto-resolving.",
    },
    {
        "call_sign": "SNOWCAT-14",
        "name": "Sepoy Mohit Verma",
        "age": 25,
        "unit": "Glacier Patrol 2",
        "rank": "Sepoy",
        "baseline_heart_rate": 68,
        "baseline_spo2": 96.8,
        "sim_scenario": Scenario.GRADUAL_DETERIORATION.value,
    },
    {
        "call_sign": "RIDGE-21",
        "name": "Subedar Anil Chauhan",
        "age": 38,
        "unit": "Ridge Post 3",
        "rank": "Subedar",
        "baseline_heart_rate": 59,
        "baseline_spo2": 97.4,
        "sim_scenario": Scenario.NORMAL.value,
    },
    {
        "call_sign": "RIDGE-22",
        "name": "Naik Farhan Qureshi",
        "age": 28,
        "unit": "Ridge Post 3",
        "rank": "Naik",
        "baseline_heart_rate": 63,
        "baseline_spo2": 96.9,
        "sim_scenario": Scenario.ALTITUDE_STRESS.value,
    },
    {
        "call_sign": "RIDGE-23",
        "name": "Sepoy Tenzing Bhutia",
        "age": 24,
        "unit": "Ridge Post 3",
        "rank": "Sepoy",
        "baseline_heart_rate": 61,
        "baseline_spo2": 97.6,
        "sim_scenario": Scenario.NORMAL.value,
    },
    {
        "call_sign": "RIDGE-24",
        "name": "Sepoy Gaurav Meena",
        "age": 26,
        "unit": "Ridge Post 3",
        "rank": "Sepoy",
        "baseline_heart_rate": 72,
        "baseline_spo2": 95.8,
        "sim_scenario": Scenario.GRADUAL_DETERIORATION.value,
        "status": PersonnelStatus.ACTIVE.value,
    },
]

#: UAV swarm. Positions are set from the patrol waypoints at seed time.
SEED_DRONES: list[dict[str, Any]] = [
    {"call_sign": "KESTREL-1", "model": "SIM-QUAD-L", "altitude_m": 5400.0},
    {"call_sign": "KESTREL-2", "model": "SIM-QUAD-L", "altitude_m": 5350.0},
    {"call_sign": "KESTREL-3", "model": "SIM-QUAD-M", "altitude_m": 5300.0},
    {"call_sign": "KESTREL-4", "model": "SIM-QUAD-M", "altitude_m": 5250.0},
    {"call_sign": "KESTREL-5", "model": "SIM-FIXED-S", "altitude_m": 5600.0},
]

SEED_MISSION = {
    "name": "Operation Third Eye — Glacier Sweep",
    "mission_type": "PATROL",
    "formation": "WEDGE",
}

SEED_TERRAIN = {
    "name": "Trishul Sector (synthetic)",
    "description": (
        "Procedurally generated high-altitude sector used for all routing and "
        "map demonstrations. Not derived from real survey or satellite data."
    ),
    "width": 64,
    "height": 64,
    "seed": 20260909,
    "cell_size_m": 250.0,
    "min_elevation_m": 3600.0,
    "max_elevation_m": 6800.0,
    "make_default": True,
}
