"""SQLAlchemy models. Importing this package registers every table."""

from app.models.auth import (
    Permission,
    RefreshToken,
    Role,
    User,
    role_permissions,
    user_roles,
)
from app.models.drones import Drone, DroneEvent, DroneMission
from app.models.personnel import (
    DigitalTwinState,
    HealthAlert,
    HealthPrediction,
    Personnel,
    RiskAssessment,
    VitalReading,
)
from app.models.system import (
    AuditLog,
    SecurityEvent,
    SimulationRun,
    SystemConfiguration,
)
from app.models.terrain import Route, RouteCalculation, TerrainCell, TerrainMap

__all__ = [
    "AuditLog",
    "DigitalTwinState",
    "Drone",
    "DroneEvent",
    "DroneMission",
    "HealthAlert",
    "HealthPrediction",
    "Permission",
    "Personnel",
    "RefreshToken",
    "RiskAssessment",
    "Role",
    "Route",
    "RouteCalculation",
    "SecurityEvent",
    "SimulationRun",
    "SystemConfiguration",
    "TerrainCell",
    "TerrainMap",
    "User",
    "VitalReading",
    "role_permissions",
    "user_roles",
]
