"""Terrain map and safe-route planning schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.algorithms.astar import HAZARD_LAYERS

from .common import ORMModel

PROFILES = ("SAFEST", "SHORTEST")


class TerrainMapOut(ORMModel):
    id: UUID
    name: str
    description: str
    width: int
    height: int
    cell_size_m: float
    origin_lat: float
    origin_lon: float
    min_elevation_m: float
    max_elevation_m: float
    seed: int
    generator_version: str
    is_default: bool
    is_synthetic: bool
    created_at: datetime


class TerrainGridOut(BaseModel):
    """Dense terrain payload for the canvas renderer.

    Layers are row-major ``height x width`` arrays of floats, quantised to
    three decimals to keep the payload small.
    """

    map: TerrainMapOut
    elevation: list[list[float]]
    avalanche: list[list[float]]
    crevasse: list[list[float]]
    weather: list[list[float]]
    difficulty: list[list[float]]
    blocked: list[list[bool]]
    terrain_type: list[list[str]]
    legend: dict[str, Any]
    is_synthetic: bool = True


class TerrainMapGenerateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=96)
    description: str = Field(default="", max_length=255)
    width: int = Field(default=64, ge=16, le=192)
    height: int = Field(default=64, ge=16, le=192)
    seed: int = Field(default=20260909, ge=0, le=2_000_000_000)
    cell_size_m: float = Field(default=250.0, ge=10.0, le=2000.0)
    min_elevation_m: float = Field(default=3600.0, ge=0.0, le=8000.0)
    max_elevation_m: float = Field(default=6800.0, ge=100.0, le=9000.0)
    make_default: bool = False

    @model_validator(mode="after")
    def check_elevation_band(self) -> TerrainMapGenerateRequest:
        if self.max_elevation_m <= self.min_elevation_m + 100:
            raise ValueError("max_elevation_m must exceed min_elevation_m by 100 m or more.")
        return self


class RoutePlanRequest(BaseModel):
    map_id: UUID | None = None
    name: str = Field(default="Ad-hoc route", min_length=1, max_length=96)
    start_x: int = Field(ge=0, le=4096)
    start_y: int = Field(ge=0, le=4096)
    goal_x: int = Field(ge=0, le=4096)
    goal_y: int = Field(ge=0, le=4096)
    enabled_layers: list[str] = Field(default_factory=lambda: list(HAZARD_LAYERS))
    compare_shortest: bool = True
    persist: bool = True
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("enabled_layers")
    @classmethod
    def validate_layers(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(HAZARD_LAYERS))
        if unknown:
            raise ValueError(
                f"Unknown hazard layer(s): {', '.join(unknown)}. "
                f"Valid layers: {', '.join(HAZARD_LAYERS)}"
            )
        return sorted(set(value))

    @model_validator(mode="after")
    def start_differs_from_goal(self) -> RoutePlanRequest:
        if (self.start_x, self.start_y) == (self.goal_x, self.goal_y):
            raise ValueError("Start and goal must be different cells.")
        return self


class RouteCalculationOut(ORMModel):
    id: UUID
    route_id: UUID
    profile: str
    cost_config: dict[str, Any]
    path: Any
    found: bool
    distance_m: float
    ascent_m: float
    descent_m: float
    estimated_minutes: float
    total_cost: float
    risk_score: float
    max_cell_risk: float
    avoided_hazards: dict[str, Any]
    nodes_expanded: int
    compute_ms: float
    explanation: dict[str, Any]
    created_at: datetime


class RouteOut(ORMModel):
    id: UUID
    map_id: UUID
    name: str
    start_x: int
    start_y: int
    goal_x: int
    goal_y: int
    notes: str | None
    created_at: datetime
    calculations: list[RouteCalculationOut] = Field(default_factory=list)


class RoutePlanResponse(BaseModel):
    route: RouteOut | None = None
    safest: RouteCalculationOut | dict[str, Any]
    shortest: RouteCalculationOut | dict[str, Any] | None = None
    comparison: dict[str, Any]
    hazard_alerts: list[dict[str, Any]] = Field(default_factory=list)
    is_synthetic_terrain: bool = True
