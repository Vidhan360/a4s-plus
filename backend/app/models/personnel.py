"""Personnel, vital readings, risk, prediction, alert and digital-twin models."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ActivityLevel,
    AlertSeverity,
    AlertStatus,
    AlertType,
    DataSourceKind,
    ExplanationMethod,
    PersonnelStatus,
    RiskCategory,
    RiskEngineKind,
    values,
)


def _check(column: str, enum_cls, name: str) -> CheckConstraint:
    allowed = ", ".join(repr(v) for v in values(enum_cls))
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


class Personnel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "personnel"
    __table_args__ = (
        _check("status", PersonnelStatus, "personnel_status_valid"),
        CheckConstraint("age BETWEEN 18 AND 70", name="personnel_age_range"),
        CheckConstraint(
            "baseline_heart_rate BETWEEN 35 AND 120", name="personnel_baseline_hr_range"
        ),
        CheckConstraint("baseline_spo2 BETWEEN 70 AND 100", name="personnel_baseline_spo2_range"),
        Index("ix_personnel_status_call_sign", "status", "call_sign"),
    )

    call_sign: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[str | None] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PersonnelStatus.ACTIVE.value, index=True
    )
    baseline_heart_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=64)
    baseline_spo2: Mapped[float] = mapped_column(Float, nullable=False, default=97.0)
    #: Scenario driving this person in the simulation engine.
    sim_scenario: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)

    readings: Mapped[list[VitalReading]] = relationship(
        back_populates="personnel", cascade="all, delete-orphan", passive_deletes=True
    )
    twin: Mapped[DigitalTwinState | None] = relationship(
        back_populates="personnel", cascade="all, delete-orphan", uselist=False
    )


class VitalReading(Base):
    """A single point-in-time reading.

    ``source`` records provenance. Every row produced by this prototype is
    ``SIMULATION``; the column exists so that future hardware sources are
    distinguishable in the very same table and pipeline.
    """

    __tablename__ = "vital_readings"
    __table_args__ = (
        _check("source", DataSourceKind, "vital_readings_source_valid"),
        _check("activity_level", ActivityLevel, "vital_readings_activity_valid"),
        CheckConstraint("spo2 BETWEEN 40 AND 100", name="vital_readings_spo2_range"),
        CheckConstraint("heart_rate BETWEEN 20 AND 260", name="vital_readings_hr_range"),
        CheckConstraint("fatigue_score BETWEEN 0 AND 100", name="vital_readings_fatigue_range"),
        Index(
            "ix_vital_readings_personnel_recorded",
            "personnel_id",
            "recorded_at",
            postgresql_using="btree",
        ),
        Index("ix_vital_readings_recorded_at_desc", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    personnel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("personnel.id", ondelete="CASCADE"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heart_rate: Mapped[float] = mapped_column(Float, nullable=False)
    spo2: Mapped[float] = mapped_column(Float, nullable=False)
    body_temp_c: Mapped[float] = mapped_column(Float, nullable=False)
    respiratory_rate: Mapped[float] = mapped_column(Float, nullable=False)
    bp_systolic: Mapped[float] = mapped_column(Float, nullable=False)
    bp_diastolic: Mapped[float] = mapped_column(Float, nullable=False)
    altitude_m: Mapped[float] = mapped_column(Float, nullable=False)
    fatigue_score: Mapped[float] = mapped_column(Float, nullable=False)
    activity_level: Mapped[str] = mapped_column(String(16), nullable=False)
    env_temp_c: Mapped[float] = mapped_column(Float, nullable=False)
    wind_kph: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    grid_x: Mapped[int | None] = mapped_column(Integer)
    grid_y: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataSourceKind.SIMULATION.value, index=True
    )
    scenario: Mapped[str | None] = mapped_column(String(32))
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("simulation_runs.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    personnel: Mapped[Personnel] = relationship(back_populates="readings")


class RiskAssessment(UUIDPrimaryKeyMixin, Base):
    """Output of the transparent rule-based risk engine for one reading."""

    __tablename__ = "risk_assessments"
    __table_args__ = (
        _check("category", RiskCategory, "risk_assessments_category_valid"),
        _check("engine", RiskEngineKind, "risk_assessments_engine_valid"),
        CheckConstraint("risk_score BETWEEN 0 AND 100", name="risk_assessments_score_range"),
        Index("ix_risk_assessments_personnel_created", "personnel_id", "created_at"),
    )

    personnel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("personnel.id", ondelete="CASCADE"), nullable=False
    )
    vital_reading_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vital_readings.id", ondelete="SET NULL")
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    engine: Mapped[str] = mapped_column(
        String(8), nullable=False, default=RiskEngineKind.RULE.value
    )
    #: List of {feature, label, value, weight, contribution, direction, detail}.
    factors: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class HealthPrediction(UUIDPrimaryKeyMixin, Base):
    """A model inference result with its explanation and provenance."""

    __tablename__ = "health_predictions"
    __table_args__ = (
        _check("predicted_category", RiskCategory, "health_predictions_category_valid"),
        _check(
            "explanation_method",
            ExplanationMethod,
            "health_predictions_explanation_valid",
        ),
        CheckConstraint(
            "risk_probability BETWEEN 0 AND 1",
            name="health_predictions_probability_range",
        ),
        Index("ix_health_predictions_personnel_created", "personnel_id", "created_at"),
    )

    personnel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("personnel.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    risk_probability: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_category: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Per-feature contributions actually computed at inference time.
    contributions: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    explanation_method: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Always SYNTHETIC_SIMULATION in this prototype.
    data_provenance: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SYNTHETIC_SIMULATION"
    )
    sequence_length: Mapped[int | None] = mapped_column(Integer)
    inference_ms: Mapped[float | None] = mapped_column(Float)
    #: Optional predicted forward trajectory for charting.
    trajectory: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class HealthAlert(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "health_alerts"
    __table_args__ = (
        _check("severity", AlertSeverity, "health_alerts_severity_valid"),
        _check("status", AlertStatus, "health_alerts_status_valid"),
        _check("alert_type", AlertType, "health_alerts_type_valid"),
        Index("ix_health_alerts_status_severity_created", "status", "severity", "created_at"),
        Index("ix_health_alerts_dedup_status", "dedup_key", "status"),
    )

    personnel_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("personnel.id", ondelete="CASCADE"), index=True
    )
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    triggering_data: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AlertStatus.OPEN.value, index=True
    )
    #: Stable identity of "the same problem"; drives dedup + cooldown.
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    #: How many times this condition re-fired while the alert stayed open.
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    escalated_from: Mapped[str | None] = mapped_column(String(16))
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    last_triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class DigitalTwinState(Base):
    """Denormalised read model: the current composite state of one person.

    Maintained by the ingestion pipeline so the dashboard and twin pages read a
    single row instead of joining six tables per render.
    """

    __tablename__ = "digital_twin_states"
    __table_args__ = (UniqueConstraint("personnel_id", name="uq_digital_twin_states_personnel_id"),)

    personnel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("personnel.id", ondelete="CASCADE"), primary_key=True
    )
    latest_reading_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vital_readings.id", ondelete="SET NULL")
    )
    latest_risk_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("risk_assessments.id", ondelete="SET NULL")
    )
    latest_prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("health_predictions.id", ondelete="SET NULL")
    )
    risk_score: Mapped[float | None] = mapped_column(Float, index=True)
    risk_category: Mapped[str | None] = mapped_column(String(16), index=True)
    open_alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Full serialised twin snapshot (vitals + environment + location + risk).
    state: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    personnel: Mapped[Personnel] = relationship(back_populates="twin")
