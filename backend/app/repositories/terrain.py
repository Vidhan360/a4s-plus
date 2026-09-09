"""Terrain map, cell and route data access."""

from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.algorithms.astar import TerrainHazardField
from app.algorithms.terrain_gen import TYPE_ORDER
from app.models.terrain import Route, RouteCalculation, TerrainCell, TerrainMap


async def get_map(session: AsyncSession, map_id: uuid.UUID) -> TerrainMap | None:
    return await session.get(TerrainMap, map_id)


async def default_map(session: AsyncSession) -> TerrainMap | None:
    result = await session.execute(
        select(TerrainMap).where(TerrainMap.is_default.is_(True)).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row
    result = await session.execute(
        select(TerrainMap).order_by(TerrainMap.created_at.asc()).limit(1)
    )
    return result.scalar_one_or_none()


async def list_maps(session: AsyncSession) -> list[TerrainMap]:
    result = await session.execute(select(TerrainMap).order_by(TerrainMap.name))
    return list(result.scalars().all())


async def load_cells(session: AsyncSession, map_id: uuid.UUID) -> list[TerrainCell]:
    result = await session.execute(
        select(TerrainCell)
        .where(TerrainCell.map_id == map_id)
        .order_by(TerrainCell.y, TerrainCell.x)
    )
    return list(result.scalars().all())


class TerrainLayers:
    """Dense numpy layers rebuilt from ``terrain_cells``."""

    def __init__(self, terrain_map: TerrainMap, cells: list[TerrainCell]) -> None:
        h, w = terrain_map.height, terrain_map.width
        self.map = terrain_map
        self.elevation = np.zeros((h, w), dtype=float)
        self.avalanche = np.zeros((h, w), dtype=float)
        self.crevasse = np.zeros((h, w), dtype=float)
        self.weather = np.zeros((h, w), dtype=float)
        self.difficulty = np.zeros((h, w), dtype=float)
        self.blocked = np.zeros((h, w), dtype=bool)
        self.terrain_type = np.empty((h, w), dtype=object)
        self.terrain_type[:] = TYPE_ORDER[0]
        if len(cells) != h * w:
            self.complete = False
        else:
            self.complete = True
        for cell in cells:
            if not (0 <= cell.x < w and 0 <= cell.y < h):
                continue
            self.elevation[cell.y, cell.x] = cell.elevation_m
            self.avalanche[cell.y, cell.x] = cell.avalanche_risk
            self.crevasse[cell.y, cell.x] = cell.crevasse_risk
            self.weather[cell.y, cell.x] = cell.weather_risk
            self.difficulty[cell.y, cell.x] = cell.difficulty
            self.blocked[cell.y, cell.x] = cell.blocked
            self.terrain_type[cell.y, cell.x] = cell.terrain_type

    def hazard_field(self) -> TerrainHazardField:
        return TerrainHazardField(
            elevation=self.elevation,
            avalanche=self.avalanche,
            crevasse=self.crevasse,
            weather=self.weather,
            difficulty=self.difficulty,
            blocked=self.blocked,
            cell_size_m=self.map.cell_size_m,
        )


async def load_layers(session: AsyncSession, terrain_map: TerrainMap) -> TerrainLayers:
    cells = await load_cells(session, terrain_map.id)
    return TerrainLayers(terrain_map, cells)


async def cell_at(session: AsyncSession, map_id: uuid.UUID, x: int, y: int) -> TerrainCell | None:
    result = await session.execute(
        select(TerrainCell).where(
            TerrainCell.map_id == map_id, TerrainCell.x == x, TerrainCell.y == y
        )
    )
    return result.scalar_one_or_none()


async def list_routes(
    session: AsyncSession, *, map_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[Route], int]:
    query = select(Route).options(selectinload(Route.calculations))
    count_query = select(func.count()).select_from(Route)
    if map_id is not None:
        query = query.where(Route.map_id == map_id)
        count_query = count_query.where(Route.map_id == map_id)
    query = query.order_by(Route.created_at.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(query)).scalars().unique().all())
    total = int((await session.execute(count_query)).scalar_one())
    return rows, total


async def get_route(session: AsyncSession, route_id: uuid.UUID) -> Route | None:
    result = await session.execute(
        select(Route).options(selectinload(Route.calculations)).where(Route.id == route_id)
    )
    return result.scalar_one_or_none()


async def recent_calculations(session: AsyncSession, limit: int = 20) -> list[RouteCalculation]:
    result = await session.execute(
        select(RouteCalculation).order_by(RouteCalculation.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
