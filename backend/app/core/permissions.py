"""Permission registry and role -> permission mapping.

Authorization is permission-code based, never role-string based, so the role
composition below can change without touching a single route handler.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    COMMANDER = "COMMANDER"
    MEDICAL_OFFICER = "MEDICAL_OFFICER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class Perm(StrEnum):
    # Personnel
    PERSONNEL_READ = "personnel:read"
    PERSONNEL_WRITE = "personnel:write"
    PERSONNEL_DELETE = "personnel:delete"
    # Health / vitals / predictions
    VITALS_READ = "vitals:read"
    VITALS_INGEST = "vitals:ingest"
    HEALTH_READ = "health:read"
    PREDICTION_READ = "prediction:read"
    PREDICTION_RUN = "prediction:run"
    TWIN_READ = "twin:read"
    # Alerts
    ALERT_READ = "alert:read"
    ALERT_ACK = "alert:ack"
    ALERT_CONFIG = "alert:config"
    # Terrain / routes
    TERRAIN_READ = "terrain:read"
    TERRAIN_WRITE = "terrain:write"
    ROUTE_READ = "route:read"
    ROUTE_PLAN = "route:plan"
    # UAV
    DRONE_READ = "drone:read"
    DRONE_COMMAND = "drone:command"
    # Security
    SECURITY_READ = "security:read"
    SECURITY_WRITE = "security:write"
    SECURITY_SIMULATE = "security:simulate"
    CRYPTO_DEMO = "crypto:demo"
    # Platform
    AUDIT_READ = "audit:read"
    DASHBOARD_READ = "dashboard:read"
    ANALYTICS_READ = "analytics:read"
    SIMULATION_READ = "simulation:read"
    SIMULATION_CONTROL = "simulation:control"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"


PERMISSION_DESCRIPTIONS: dict[Perm, str] = {
    Perm.PERSONNEL_READ: "View personnel records and profiles",
    Perm.PERSONNEL_WRITE: "Create and update personnel records",
    Perm.PERSONNEL_DELETE: "Delete personnel records",
    Perm.VITALS_READ: "Read simulated vital-sign readings",
    Perm.VITALS_INGEST: "Ingest vital-sign readings into the pipeline",
    Perm.HEALTH_READ: "Read health risk assessments",
    Perm.PREDICTION_READ: "Read model predictions and metrics",
    Perm.PREDICTION_RUN: "Trigger on-demand model inference",
    Perm.TWIN_READ: "View personnel digital twins",
    Perm.ALERT_READ: "View alerts",
    Perm.ALERT_ACK: "Acknowledge and resolve alerts",
    Perm.ALERT_CONFIG: "Change alert rules and thresholds",
    Perm.TERRAIN_READ: "View synthetic terrain and hazard layers",
    Perm.TERRAIN_WRITE: "Generate and modify terrain maps",
    Perm.ROUTE_READ: "View routes and route calculations",
    Perm.ROUTE_PLAN: "Run the A* route planner",
    Perm.DRONE_READ: "View UAV telemetry and events",
    Perm.DRONE_COMMAND: "Issue simulated UAV commands",
    Perm.SECURITY_READ: "View security events",
    Perm.SECURITY_WRITE: "Update security event status and response",
    Perm.SECURITY_SIMULATE: "Inject simulated security events",
    Perm.CRYPTO_DEMO: "Use the authenticated-encryption demonstration",
    Perm.AUDIT_READ: "Read the append-only audit log",
    Perm.DASHBOARD_READ: "View the command centre dashboard",
    Perm.ANALYTICS_READ: "View historical analytics",
    Perm.SIMULATION_READ: "View simulation state",
    Perm.SIMULATION_CONTROL: "Start, stop, pause and configure the simulation",
    Perm.USER_READ: "View user accounts",
    Perm.USER_WRITE: "Create, update, lock and unlock user accounts",
    Perm.CONFIG_READ: "Read system configuration",
    Perm.CONFIG_WRITE: "Change system configuration",
}

_READ_ONLY: set[Perm] = {
    Perm.PERSONNEL_READ,
    Perm.VITALS_READ,
    Perm.HEALTH_READ,
    Perm.PREDICTION_READ,
    Perm.TWIN_READ,
    Perm.ALERT_READ,
    Perm.TERRAIN_READ,
    Perm.ROUTE_READ,
    Perm.DRONE_READ,
    Perm.SECURITY_READ,
    Perm.DASHBOARD_READ,
    Perm.ANALYTICS_READ,
    Perm.SIMULATION_READ,
}

ROLE_PERMISSIONS: dict[Role, set[Perm]] = {
    Role.ADMIN: set(Perm),
    Role.COMMANDER: _READ_ONLY
    | {
        Perm.PERSONNEL_WRITE,
        Perm.PREDICTION_RUN,
        Perm.ALERT_ACK,
        Perm.ROUTE_PLAN,
        Perm.TERRAIN_WRITE,
        Perm.DRONE_COMMAND,
        Perm.SECURITY_WRITE,
        Perm.SECURITY_SIMULATE,
        Perm.CRYPTO_DEMO,
        Perm.SIMULATION_CONTROL,
        Perm.AUDIT_READ,
        Perm.CONFIG_READ,
    },
    Role.MEDICAL_OFFICER: {
        Perm.PERSONNEL_READ,
        Perm.PERSONNEL_WRITE,
        Perm.VITALS_READ,
        # Medical officers record manual observations for personnel in their care.
        Perm.VITALS_INGEST,
        Perm.HEALTH_READ,
        Perm.PREDICTION_READ,
        Perm.PREDICTION_RUN,
        Perm.TWIN_READ,
        Perm.ALERT_READ,
        Perm.ALERT_ACK,
        Perm.DASHBOARD_READ,
        Perm.ANALYTICS_READ,
        Perm.SIMULATION_READ,
        Perm.TERRAIN_READ,
    },
    Role.OPERATOR: {
        Perm.PERSONNEL_READ,
        Perm.TERRAIN_READ,
        Perm.ROUTE_READ,
        Perm.ROUTE_PLAN,
        Perm.DRONE_READ,
        Perm.DRONE_COMMAND,
        Perm.SECURITY_READ,
        Perm.SECURITY_SIMULATE,
        Perm.DASHBOARD_READ,
        Perm.SIMULATION_READ,
        Perm.SIMULATION_CONTROL,
        Perm.ALERT_READ,
        Perm.VITALS_READ,
        # Operators feed telemetry in from the simulation / edge gateway.
        Perm.VITALS_INGEST,
    },
    Role.VIEWER: set(_READ_ONLY),
}

ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.ADMIN: "Full platform access including user management and configuration",
    Role.COMMANDER: "Command centre oversight across all operational modules",
    Role.MEDICAL_OFFICER: "Personnel health, digital twins and health alerts",
    Role.OPERATOR: "Route planning, UAV simulation and operational events",
    Role.VIEWER: "Read-only access to operational data",
}


def permissions_for_roles(roles: list[str] | set[str]) -> set[str]:
    out: set[str] = set()
    for r in roles:
        try:
            out |= {p.value for p in ROLE_PERMISSIONS[Role(r)]}
        except (ValueError, KeyError):
            continue
    return out
