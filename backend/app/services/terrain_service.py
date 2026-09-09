"""Terrain map generation, persistence and renderer payloads."""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy import insert as sa_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.terrain_gen import (
    GENERATOR_VERSION,
    TYPE_ORDER,
    generate_terrain,
    type_name,
)
from app.core.errors import ConflictError, NotFoundError
from app.models.terrain import TerrainCell, TerrainMap
from app.repositories import terrain as terrain_repo

#: Colour ramp shared with the frontend canvas renderer.
TERRAIN_LEGEND: dict[str, Any] = {
    "types": [
        {"code": "VALLEY", "label": "Valley floor", "colour": "#2f4b3f"},
        {"code": "SNOWFIELD", "label": "Snowfield", "colour": "#dbe7f0"},
        {"code": "GLACIER", "label": "Glacier", "colour": "#8fc7dd"},
        {"code": "SLOPE", "label": "Slope", "colour": "#7d7f74"},
        {"code": "ICEFALL", "label": "Icefall", "colour": "#5f9ecf"},
        {"code": "ROCK", "label": "Rock", "colour": "#6a5f56"},
        {"code": "RIDGE", "label": "Ridge", "colour": "#b9b1a4"},
    ],
    "hazards": [
        {"code": "avalanche", "label": "Avalanche risk", "colour": "#f97316"},
        {"code": "crevasse", "label": "Crevasse risk", "colour": "#38bdf8"},
        {"code": "weather", "label": "Weather exposure", "colour": "#a78bfa"},
        {"code": "difficulty", "label": "Traverse difficulty", "colour": "#facc15"},
    ],
    "notice": (
        "Procedurally generated synthetic terrain. Not derived from real "
        "survey, DEM or satellite data."
    ),
}


def _quantise(layer: np.ndarray, decimals: int = 3) -> list[list[float]]:
    return [[round(float(v), decimals) for v in row] for row in layer]


class TerrainService:
    async def generate_and_store(
        self,
        session: AsyncSession,
        *,
        name: str,
        description: str = "",
        width: int = 64,
        height: int = 64,
        seed: int = 20260909,
        cell_size_m: float = 250.0,
        min_elevation_m: float = 3600.0,
        max_elevation_m: float = 6800.0,
        make_default: bool = False,
        origin_lat: float = 35.42,
        origin_lon: float = 77.11,
    ) -> TerrainMap:
        existing = (
            await session.execute(select(TerrainMap).where(TerrainMap.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"A terrain map named '{name}' already exists.")

        grid = generate_terrain(
            width=width,
            height=height,
            seed=seed,
            cell_size_m=cell_size_m,
            min_elevation_m=min_elevation_m,
            max_elevation_m=max_elevation_m,
        )
        terrain_map = TerrainMap(
            id=uuid.uuid4(),
            name=name,
            description=description,
            width=width,
            height=height,
            cell_size_m=cell_size_m,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            min_elevation_m=grid.min_elevation,
            max_elevation_m=grid.max_elevation,
            seed=seed,
            generator_version=GENERATOR_VERSION,
            is_default=make_default,
            is_synthetic=True,
        )
        session.add(terrain_map)
        await session.flush()

        if make_default:
            await self._clear_other_defaults(session, terrain_map.id)

        await self._bulk_insert_cells(session, terrain_map, grid)
        return terrain_map

    async def _clear_other_defaults(self, session: AsyncSession, keep_id: uuid.UUID) -> None:
        rows = (
            (
                await session.execute(
                    select(TerrainMap).where(
                        TerrainMap.is_default.is_(True), TerrainMap.id != keep_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.is_default = False

    async def _bulk_insert_cells(
        self, session: AsyncSession, terrain_map: TerrainMap, grid: Any
    ) -> int:
        rows: list[dict[str, Any]] = []
        for y in range(terrain_map.height):
            for x in range(terrain_map.width):
                rows.append(
                    {
                        "map_id": terrain_map.id,
                        "x": x,
                        "y": y,
                        "elevation_m": round(float(grid.elevation[y, x]), 2),
                        "terrain_type": type_name(int(grid.terrain_type[y, x])),
                        "difficulty": round(float(grid.difficulty[y, x]), 4),
                        "avalanche_risk": round(float(grid.avalanche[y, x]), 4),
                        "crevasse_risk": round(float(grid.crevasse[y, x]), 4),
                        "weather_risk": round(float(grid.weather[y, x]), 4),
                        "blocked": bool(grid.blocked[y, x]),
                    }
                )
        # Chunked to keep single statements well inside driver parameter limits.
        chunk = 2000
        for start in range(0, len(rows), chunk):
            await session.execute(sa_insert(TerrainCell), rows[start : start + chunk])
        await session.flush()
        return len(rows)

    async def set_default(self, session: AsyncSession, map_id: uuid.UUID) -> TerrainMap:
        terrain_map = await terrain_repo.get_map(session, map_id)
        if terrain_map is None:
            raise NotFoundError("Terrain map not found.")
        await self._clear_other_defaults(session, map_id)
        terrain_map.is_default = True
        await session.flush()
        return terrain_map

    async def delete_map(self, session: AsyncSession, map_id: uuid.UUID) -> None:
        terrain_map = await terrain_repo.get_map(session, map_id)
        if terrain_map is None:
            raise NotFoundError("Terrain map not found.")
        await session.execute(delete(TerrainCell).where(TerrainCell.map_id == map_id))
        await session.delete(terrain_map)
        await session.flush()

    async def require_map(self, session: AsyncSession, map_id: uuid.UUID | None) -> TerrainMap:
        terrain_map = (
            await terrain_repo.get_map(session, map_id)
            if map_id is not None
            else await terrain_repo.default_map(session)
        )
        if terrain_map is None:
            raise NotFoundError(
                "No terrain map available. Seed the database or generate a map first."
            )
        return terrain_map

    async def grid_payload(self, session: AsyncSession, terrain_map: TerrainMap) -> dict[str, Any]:
        layers = await terrain_repo.load_layers(session, terrain_map)
        return {
            "map": terrain_map,
            "elevation": [[round(float(v), 1) for v in row] for row in layers.elevation],
            "avalanche": _quantise(layers.avalanche),
            "crevasse": _quantise(layers.crevasse),
            "weather": _quantise(layers.weather),
            "difficulty": _quantise(layers.difficulty),
            "blocked": [[bool(v) for v in row] for row in layers.blocked],
            "terrain_type": [[str(v) for v in row] for row in layers.terrain_type],
            "legend": {
                **TERRAIN_LEGEND,
                "type_order": list(TYPE_ORDER),
                "elevation_range": [
                    round(terrain_map.min_elevation_m, 1),
                    round(terrain_map.max_elevation_m, 1),
                ],
                "cells_loaded": int(layers.complete),
            },
            "is_synthetic": True,
        }


terrain_service = TerrainService()
