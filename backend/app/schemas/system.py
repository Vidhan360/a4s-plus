"""Security, audit, configuration, simulation, dashboard and crypto schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import Scenario
from app.services.security_service import SIMULATED_EVENT_CATALOGUE

from .common import ORMModel, SafeModel
from .personnel import AlertOut

SIM_ATTACK_KINDS = tuple(SIMULATED_EVENT_CATALOGUE.keys())


# --------------------------------------------------------------------------
# Security monitor
# --------------------------------------------------------------------------


class SecurityEventOut(ORMModel):
    id: UUID
    event_type: str
    severity: str
    origin: str
    source: str
    title: str
    description: str
    status: str
    response_action: str | None
    actor_user_id: UUID | None
    subject_email: str | None
    drone_id: UUID | None
    ip: str | None
    request_id: str | None
    payload: dict[str, Any]
    handled_by_id: UUID | None
    handled_at: datetime | None
    created_at: datetime


class SecurityInjectRequest(BaseModel):
    kind: str = Field(description=f"One of {', '.join(SIM_ATTACK_KINDS)}")
    drone_id: UUID | None = None
    payload: dict[str, Any] | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in SIMULATED_EVENT_CATALOGUE:
            raise ValueError(
                f"Unknown simulated event kind '{value}'. "
                f"Valid kinds: {', '.join(SIM_ATTACK_KINDS)}"
            )
        return value


class SecurityAcknowledgeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class SecurityPostureOut(BaseModel):
    open_events: int
    by_severity: dict[str, int]
    by_origin: dict[str, int]
    failed_logins_24h: int
    locked_accounts: int
    recent: list[SecurityEventOut]
    controls: list[dict[str, Any]]


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------


class AuditLogOut(ORMModel):
    id: int
    actor_user_id: UUID | None
    actor_email: str | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    ip: str | None
    user_agent: str | None
    request_id: str | None
    meta: dict[str, Any]
    created_at: datetime


# --------------------------------------------------------------------------
# System configuration
# --------------------------------------------------------------------------


class ConfigOut(BaseModel):
    key: str
    value: Any
    default_value: Any = None
    description: str
    version: int
    is_editable: bool
    is_customised: bool = False
    updated_at: str | None = None


class ConfigUpdateRequest(BaseModel):
    value: Any


# --------------------------------------------------------------------------
# Simulation engine
# --------------------------------------------------------------------------


class SimulationStartRequest(BaseModel):
    scenario: Scenario = Scenario.MIXED
    seed: int = Field(default=20260909, ge=0, le=2_000_000_000)
    speed: int = Field(default=1)
    tick_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    sim_seconds_per_tick: float = Field(default=60.0, ge=5.0, le=900.0)
    reset_first: bool = True

    @field_validator("speed")
    @classmethod
    def validate_speed(cls, value: int) -> int:
        if value not in (1, 2, 5, 10):
            raise ValueError("speed must be one of 1, 2, 5, 10.")
        return value


class SimulationSpeedRequest(BaseModel):
    speed: int

    @field_validator("speed")
    @classmethod
    def validate_speed(cls, value: int) -> int:
        if value not in (1, 2, 5, 10):
            raise ValueError("speed must be one of 1, 2, 5, 10.")
        return value


class SimulationScenarioRequest(BaseModel):
    scenario: Scenario
    personnel_id: UUID | None = Field(
        default=None,
        description="Apply to one person; omit to apply the profile to everyone.",
    )


class SimulationStatusOut(BaseModel):
    status: str
    run_id: UUID | None = None
    scenario: str | None = None
    seed: int | None = None
    speed: int = 1
    tick_count: int = 0
    sim_clock_seconds: float = 0.0
    sim_clock_iso: datetime | None = None
    wall_started_at: datetime | None = None
    last_tick_at: datetime | None = None
    tick_seconds: float = 5.0
    sim_seconds_per_tick: float = 60.0
    tracked_personnel: int = 0
    tracked_drones: int = 0
    readings_emitted: int = 0
    alerts_raised: int = 0
    last_tick_duration_ms: float = 0.0
    scenario_assignments: dict[str, str] = Field(default_factory=dict)
    available_scenarios: list[dict[str, str]] = Field(default_factory=list)
    is_simulated: bool = True


class SimulationRunOut(ORMModel):
    id: UUID
    scenario_profile: str
    seed: int
    speed: int
    status: str
    tick_count: int
    sim_clock_seconds: float
    config: dict[str, Any]
    started_at: datetime
    last_tick_at: datetime | None
    stopped_at: datetime | None


# --------------------------------------------------------------------------
# Dashboard / analytics
# --------------------------------------------------------------------------


class DashboardOut(BaseModel):
    generated_at: datetime
    personnel_total: int
    personnel_active: int
    risk_distribution: dict[str, int]
    average_risk: float
    highest_risk: dict[str, Any] | None
    open_alerts: int
    alerts_by_severity: dict[str, int]
    critical_alerts: list[AlertOut]
    watchlist: list[dict[str, Any]]
    drones: dict[str, Any]
    security: dict[str, Any]
    simulation: SimulationStatusOut
    environment: dict[str, Any] | None
    prediction_models: list[dict[str, Any]]
    disclaimer: dict[str, str]


class AnalyticsOut(SafeModel):
    window_hours: int
    generated_at: datetime
    readings: int
    risk_timeline: list[dict[str, Any]]
    risk_distribution: dict[str, int]
    alert_timeline: list[dict[str, Any]]
    alerts_by_type: dict[str, int]
    mean_time_to_acknowledge_seconds: float | None
    top_risk_factors: list[dict[str, Any]]
    vitals_correlation: list[dict[str, Any]]
    model_comparison: list[dict[str, Any]]
    model_metrics_source: str
    per_person: list[dict[str, Any]]
    disclaimer: dict[str, str]


# --------------------------------------------------------------------------
# Authenticated-encryption demonstration
# --------------------------------------------------------------------------


class CryptoDemoRequest(BaseModel):
    plaintext: str = Field(min_length=1, max_length=4096)
    aad: str | None = Field(
        default=None,
        max_length=256,
        description="Additional authenticated data (integrity-protected, not encrypted).",
    )


class CryptoDemoResponse(BaseModel):
    algorithm: str
    label: str
    notice: str
    key_bits: int
    nonce_bits: int
    plaintext_length: int
    ciphertext_b64: str
    nonce_b64: str
    key_b64: str
    ciphertext_length: int
    tag_bytes: int
    aad: str | None
    decrypted_matches_input: bool
    tamper_test: dict[str, Any]
    encrypt_ms: float
    decrypt_ms: float


class HealthCheckOut(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    event_bus: str
    ml_models: dict[str, Any]
    simulation: str
    uptime_seconds: float
    disclaimer: dict[str, str]
