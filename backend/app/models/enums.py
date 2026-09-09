"""Domain enumerations shared by models, schemas and services.

Stored as short strings with database CHECK constraints rather than native
PostgreSQL ENUM types: this keeps migrations simple (adding a value is a
constraint change, not a type rewrite) while still enforcing validity in the
database.
"""

from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"


class PersonnelStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESTING = "RESTING"
    EVACUATED = "EVACUATED"
    OFFLINE = "OFFLINE"


class RiskCategory(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}[self.value]


class DataSourceKind(StrEnum):
    """Provenance of a reading. Only SIMULATION is produced today."""

    SIMULATION = "SIMULATION"
    WEARABLE = "WEARABLE"  # reserved for future hardware
    UAV = "UAV"  # reserved for future hardware
    EDGE = "EDGE"  # reserved for future hardware
    MANUAL = "MANUAL"


class RiskEngineKind(StrEnum):
    RULE = "RULE"
    MODEL = "MODEL"


class ExplanationMethod(StrEnum):
    TRANSPARENT_WEIGHTS = "TRANSPARENT_WEIGHTS"
    OCCLUSION_SENSITIVITY = "OCCLUSION_SENSITIVITY"
    IMPURITY_IMPORTANCE = "IMPURITY_IMPORTANCE"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return {"INFO": 0, "WARNING": 1, "HIGH": 2, "CRITICAL": 3}[self.value]


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


class AlertType(StrEnum):
    VITAL_THRESHOLD = "VITAL_THRESHOLD"
    TREND_DETERIORATION = "TREND_DETERIORATION"
    RISK_ESCALATION = "RISK_ESCALATION"
    PREDICTED_RISK = "PREDICTED_RISK"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    ROUTE_HAZARD = "ROUTE_HAZARD"
    UAV_EVENT = "UAV_EVENT"
    SECURITY_EVENT = "SECURITY_EVENT"


class TerrainType(StrEnum):
    VALLEY = "VALLEY"
    SLOPE = "SLOPE"
    RIDGE = "RIDGE"
    GLACIER = "GLACIER"
    ICEFALL = "ICEFALL"
    ROCK = "ROCK"
    SNOWFIELD = "SNOWFIELD"


class DroneStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETURNING = "RETURNING"
    OFFLINE = "OFFLINE"
    JAMMED = "JAMMED"
    ALERT = "ALERT"


class CommsStatus(StrEnum):
    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"
    LOST = "LOST"
    SPOOF_SUSPECTED = "SPOOF_SUSPECTED"


class MissionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class DroneEventType(StrEnum):
    TAKEOFF = "TAKEOFF"
    WAYPOINT_REACHED = "WAYPOINT_REACHED"
    BATTERY_LOW = "BATTERY_LOW"
    SIGNAL_DEGRADED = "SIGNAL_DEGRADED"
    COMMS_LOST = "COMMS_LOST"
    COMMS_RESTORED = "COMMS_RESTORED"
    JAMMING_DETECTED = "JAMMING_DETECTED"
    SPOOFING_DETECTED = "SPOOFING_DETECTED"
    RETURN_TO_BASE = "RETURN_TO_BASE"
    LANDED = "LANDED"
    STATUS_CHANGE = "STATUS_CHANGE"


class SecuritySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityEventOrigin(StrEnum):
    """Distinguishes genuine application security events from injected demos."""

    REAL = "REAL"
    SIMULATED = "SIMULATED"


class SecurityEventType(StrEnum):
    FAILED_LOGIN = "FAILED_LOGIN"
    ACCOUNT_LOCKOUT = "ACCOUNT_LOCKOUT"
    PERMISSION_VIOLATION = "PERMISSION_VIOLATION"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_REUSE_DETECTED = "TOKEN_REUSE_DETECTED"
    SUSPICIOUS_API_ACTIVITY = "SUSPICIOUS_API_ACTIVITY"
    RATE_LIMIT_TRIPPED = "RATE_LIMIT_TRIPPED"
    SIMULATED_JAMMING = "SIMULATED_JAMMING"
    SIMULATED_SPOOFING = "SIMULATED_SPOOFING"
    SIMULATED_INTRUSION = "SIMULATED_INTRUSION"
    ENCRYPTION_DEMO = "ENCRYPTION_DEMO"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"


class SecurityEventStatus(StrEnum):
    NEW = "NEW"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    CLOSED = "CLOSED"


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    ERROR = "ERROR"


class SimulationStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class Scenario(StrEnum):
    """Per-person physiological scenario, plus one roster-level profile.

    ``MIXED`` is not a physiology profile: it is a deployment profile that
    assigns a deterministic spread of the other five across the roster.
    """

    NORMAL = "NORMAL"
    GRADUAL_DETERIORATION = "GRADUAL_DETERIORATION"
    ACUTE_EVENT = "ACUTE_EVENT"
    ALTITUDE_STRESS = "ALTITUDE_STRESS"
    RECOVERY = "RECOVERY"
    MIXED = "MIXED"


class ActivityLevel(StrEnum):
    RESTING = "RESTING"
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"
    EXTREME = "EXTREME"


SIM_SPEEDS: tuple[int, ...] = (1, 2, 5, 10)


def values(enum_cls: type[StrEnum]) -> list[str]:
    return [e.value for e in enum_cls]
