"""Personnel, vitals, risk, prediction, alert and digital-twin schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    ActivityLevel,
    AlertSeverity,
    AlertStatus,
    AlertType,
    PersonnelStatus,
    RiskCategory,
    Scenario,
)

from .common import ORMModel, SafeModel


class PersonnelBase(BaseModel):
    call_sign: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=128)
    age: int = Field(ge=18, le=70)
    unit: str = Field(min_length=1, max_length=64)
    rank: str | None = Field(default=None, max_length=48)
    baseline_heart_rate: int = Field(default=64, ge=35, le=110)
    baseline_spo2: float = Field(default=97.0, ge=80.0, le=100.0)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("call_sign")
    @classmethod
    def normalise_call_sign(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned.replace("-", "").replace("_", "").isalnum():
            raise ValueError("call_sign may contain letters, digits, '-' and '_' only.")
        return cleaned


class PersonnelCreate(PersonnelBase):
    status: PersonnelStatus = PersonnelStatus.ACTIVE
    sim_scenario: Scenario | None = None


class PersonnelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    age: int | None = Field(default=None, ge=18, le=70)
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    rank: str | None = Field(default=None, max_length=48)
    status: PersonnelStatus | None = None
    baseline_heart_rate: int | None = Field(default=None, ge=35, le=110)
    baseline_spo2: float | None = Field(default=None, ge=80.0, le=100.0)
    sim_scenario: Scenario | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PersonnelOut(ORMModel):
    id: UUID
    call_sign: str
    name: str
    age: int
    unit: str
    rank: str | None
    status: str
    baseline_heart_rate: int
    baseline_spo2: float
    sim_scenario: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    #: Provenance flag. Every roster entry in this prototype is synthetic; the
    #: field exists so the UI never has to infer provenance.
    is_simulated: bool = True


class PersonnelSummary(PersonnelOut):
    """Roster row enriched with the latest twin state."""

    risk_score: float | None = None
    risk_category: str | None = None
    open_alert_count: int = 0
    is_stale: bool = False
    last_reading_at: datetime | None = None
    latest_vitals: dict[str, Any] | None = None


class VitalReadingOut(ORMModel):
    id: int
    personnel_id: UUID
    recorded_at: datetime
    heart_rate: float
    spo2: float
    body_temp_c: float
    respiratory_rate: float
    bp_systolic: float
    bp_diastolic: float
    altitude_m: float
    fatigue_score: float
    activity_level: str
    env_temp_c: float
    wind_kph: float
    latitude: float
    longitude: float
    grid_x: int | None
    grid_y: int | None
    source: str
    scenario: str | None


class VitalIngestRequest(SafeModel):
    """Manual reading injection.

    Provenance is fixed server-side; a client cannot claim a reading came from
    real hardware.
    """

    personnel_id: UUID
    recorded_at: datetime | None = None
    heart_rate: float = Field(ge=20, le=260)
    spo2: float = Field(ge=40, le=100)
    body_temp_c: float = Field(ge=28.0, le=43.0)
    respiratory_rate: float = Field(ge=4, le=70)
    bp_systolic: float = Field(ge=50, le=250)
    bp_diastolic: float = Field(ge=30, le=160)
    altitude_m: float = Field(ge=0, le=9000)
    fatigue_score: float = Field(ge=0, le=100)
    activity_level: ActivityLevel = ActivityLevel.LIGHT
    env_temp_c: float = Field(default=-8.0, ge=-70.0, le=55.0)
    wind_kph: float = Field(default=15.0, ge=0.0, le=250.0)
    latitude: float = Field(default=35.42, ge=-90.0, le=90.0)
    longitude: float = Field(default=77.11, ge=-180.0, le=180.0)
    grid_x: int | None = Field(default=None, ge=0, le=4096)
    grid_y: int | None = Field(default=None, ge=0, le=4096)
    run_prediction: bool = True
    model_name: str | None = Field(default=None, max_length=48)

    @field_validator("bp_diastolic")
    @classmethod
    def diastolic_below_systolic(cls, value: float, info: Any) -> float:
        systolic = info.data.get("bp_systolic")
        if systolic is not None and value >= systolic:
            raise ValueError("bp_diastolic must be lower than bp_systolic.")
        return value


class RiskFactorOut(BaseModel):
    feature: str
    label: str
    value: float | None = None
    severity: float
    weight: float
    contribution: float
    detail: str = ""


class RiskAssessmentOut(ORMModel):
    id: UUID
    personnel_id: UUID
    vital_reading_id: int | None
    risk_score: float
    category: str
    engine: str
    factors: dict[str, Any]
    config_version: int
    created_at: datetime


class HealthPredictionOut(ORMModel):
    id: UUID
    personnel_id: UUID
    model_name: str
    model_version: str
    horizon_minutes: int
    risk_probability: float
    predicted_category: str
    contributions: dict[str, Any]
    explanation_method: str
    data_provenance: str
    sequence_length: int | None
    inference_ms: float | None
    trajectory: dict[str, Any] | None
    created_at: datetime


class ModelDescriptionOut(SafeModel):
    name: str
    version: str
    available: bool
    explanation_method: str
    horizon_minutes: int
    sequence_length: int
    data_provenance: str
    metrics: dict[str, Any] | None = None
    unavailable_reason: str | None = None


class AlertOut(ORMModel):
    id: UUID
    personnel_id: UUID | None
    alert_type: str
    severity: str
    title: str
    reason: str
    recommended_action: str
    triggering_data: dict[str, Any]
    status: str
    dedup_key: str
    occurrence_count: int
    escalated_from: str | None
    acknowledged_by_id: UUID | None
    acknowledged_at: datetime | None
    resolved_by_id: UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    last_triggered_at: datetime
    created_at: datetime


class AlertListFilters(BaseModel):
    status: AlertStatus | None = None
    severity: AlertSeverity | None = None
    alert_type: AlertType | None = None
    personnel_id: UUID | None = None


class AlertAcknowledgeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class AlertResolveRequest(BaseModel):
    resolution_note: str = Field(min_length=1, max_length=1000)


class DigitalTwinOut(BaseModel):
    personnel_id: UUID
    call_sign: str
    risk_score: float | None
    risk_category: str | None
    open_alert_count: int
    is_stale: bool
    updated_at: datetime | None = None
    state: dict[str, Any]


class RiskDistributionOut(BaseModel):
    category: RiskCategory
    count: int
