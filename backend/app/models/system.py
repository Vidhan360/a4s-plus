"""Security events, append-only audit log, configuration and simulation runs."""

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
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AuditResult,
    SecurityEventOrigin,
    SecurityEventStatus,
    SecurityEventType,
    SecuritySeverity,
    SimulationStatus,
    values,
)


def _check(column: str, enum_cls, name: str) -> CheckConstraint:
    allowed = ", ".join(repr(v) for v in values(enum_cls))
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


class SecurityEvent(UUIDPrimaryKeyMixin, Base):
    """A security-relevant occurrence.

    ``origin`` separates genuine application events (failed logins, permission
    violations, invalid tokens) from events deliberately injected for the
    demonstration. The two are never conflated in the UI or the API.
    """

    __tablename__ = "security_events"
    __table_args__ = (
        _check("event_type", SecurityEventType, "security_events_type_valid"),
        _check("severity", SecuritySeverity, "security_events_severity_valid"),
        _check("origin", SecurityEventOrigin, "security_events_origin_valid"),
        _check("status", SecurityEventStatus, "security_events_status_valid"),
        Index("ix_security_events_severity_created", "severity", "created_at"),
        Index("ix_security_events_origin_created", "origin", "created_at"),
    )

    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SecurityEventStatus.NEW.value, index=True
    )
    response_action: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    subject_email: Mapped[str | None] = mapped_column(String(255))
    drone_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("drones.id", ondelete="SET NULL")
    )
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class AuditLog(Base):
    """Append-only audit record.

    The application exposes no update or delete path for this table, and the
    migration additionally revokes UPDATE/DELETE from the application role on
    PostgreSQL so immutability is enforced by the database, not just by code.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        _check("result", AuditResult, "audit_logs_result_valid"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class SystemConfiguration(TimestampMixin, Base):
    """Versioned key/value configuration (risk thresholds, weights, cooldowns)."""

    __tablename__ = "system_configurations"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )


class SimulationRun(UUIDPrimaryKeyMixin, Base):
    """One simulation session, including its seed for reproducibility."""

    __tablename__ = "simulation_runs"
    __table_args__ = (
        _check("status", SimulationStatus, "simulation_runs_status_valid"),
        CheckConstraint("speed IN (1, 2, 5, 10)", name="simulation_runs_speed_valid"),
    )

    scenario_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    speed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SimulationStatus.RUNNING.value, index=True
    )
    tick_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sim_clock_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    started_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
