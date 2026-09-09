"""Synthetic terrain, hazard layers, routes and A* calculation records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TerrainType, values


class TerrainMap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A procedurally generated terrain grid.

    Synthetic only: no real geographic or military data is used. ``origin_lat``
    / ``origin_lon`` anchor the grid to plausible coordinates purely so a real
    GIS provider can later replace the generator behind ``TerrainProvider``.
    """

    __tablename__ = "terrain_maps"
    __table_args__ = (
        CheckConstraint("width BETWEEN 8 AND 400", name="terrain_maps_width_range"),
        CheckConstraint("height BETWEEN 8 AND 400", name="terrain_maps_height_range"),
        CheckConstraint("cell_size_m > 0", name="terrain_maps_cell_size_positive"),
    )

    name: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_size_m: Mapped[float] = mapped_column(Float, nullable=False, default=250.0)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False, default=35.42)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False, default=77.11)
    min_elevation_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_elevation_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    generator_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    cells: Mapped[list[TerrainCell]] = relationship(
        back_populates="terrain_map", cascade="all, delete-orphan", passive_deletes=True
    )
    routes: Mapped[list[Route]] = relationship(
        back_populates="terrain_map", cascade="all, delete-orphan", passive_deletes=True
    )


class TerrainCell(Base):
    __tablename__ = "terrain_cells"
    __table_args__ = (
        CheckConstraint(
            f"terrain_type IN ({', '.join(repr(v) for v in values(TerrainType))})",
            name="terrain_cells_type_valid",
        ),
        CheckConstraint("avalanche_risk BETWEEN 0 AND 1", name="terrain_cells_avalanche_range"),
        CheckConstraint("crevasse_risk BETWEEN 0 AND 1", name="terrain_cells_crevasse_range"),
        CheckConstraint("weather_risk BETWEEN 0 AND 1", name="terrain_cells_weather_range"),
        CheckConstraint("difficulty BETWEEN 0 AND 1", name="terrain_cells_difficulty_range"),
        Index("ix_terrain_cells_map_blocked", "map_id", "blocked"),
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("terrain_maps.id", ondelete="CASCADE"), primary_key=True
    )
    x: Mapped[int] = mapped_column(Integer, primary_key=True)
    y: Mapped[int] = mapped_column(Integer, primary_key=True)
    elevation_m: Mapped[float] = mapped_column(Float, nullable=False)
    terrain_type: Mapped[str] = mapped_column(String(16), nullable=False)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avalanche_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    crevasse_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weather_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    terrain_map: Mapped[TerrainMap] = relationship(back_populates="cells")


class Route(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "routes"
    __table_args__ = (Index("ix_routes_map_created", "map_id", "created_at"),)

    map_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("terrain_maps.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    start_x: Mapped[int] = mapped_column(Integer, nullable=False)
    start_y: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_x: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_y: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )

    terrain_map: Mapped[TerrainMap] = relationship(back_populates="routes")
    calculations: Mapped[list[RouteCalculation]] = relationship(
        back_populates="route", cascade="all, delete-orphan", passive_deletes=True
    )


class RouteCalculation(UUIDPrimaryKeyMixin, Base):
    """One A* run: its cost configuration, resulting path and measured cost.

    ``nodes_expanded`` and ``compute_ms`` are recorded from the actual search,
    not estimated.
    """

    __tablename__ = "route_calculations"
    __table_args__ = (
        CheckConstraint(
            "profile IN ('SHORTEST', 'SAFEST', 'CUSTOM')",
            name="route_calculations_profile_valid",
        ),
        Index("ix_route_calculations_route_created", "route_id", "created_at"),
    )

    route_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False
    )
    profile: Mapped[str] = mapped_column(String(16), nullable=False, default="SAFEST")
    cost_config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    #: Ordered list of {x, y, elevation_m, ...} path nodes.
    path: Mapped[dict] = mapped_column(JSONType, nullable=False, default=list)
    found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ascent_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    descent_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: Total cost under the configured weights - the quantity A* minimises.
    total_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_cell_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avoided_hazards: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    nodes_expanded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compute_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    explanation: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    route: Mapped[Route] = relationship(back_populates="calculations")
