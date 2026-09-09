"""System configuration service.

Configuration is stored in ``system_configurations`` and cached briefly in
process. Every consumer (risk engine, alert engine, route planner, simulation)
reads through here rather than importing the defaults directly, so an operator
change takes effect without a restart.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.defaults import (
    ALL_DEFAULTS,
    CONFIG_ALERT_RULES,
    CONFIG_PREDICTION,
    CONFIG_RISK_CATEGORIES,
    CONFIG_RISK_SCALE,
    CONFIG_RISK_THRESHOLDS,
    CONFIG_RISK_WEIGHTS,
    CONFIG_ROUTE_COSTS,
    CONFIG_SIMULATION,
)
from app.core.errors import NotFoundError, ValidationError
from app.models.system import SystemConfiguration
from app.services.risk_engine import RiskEngine

#: Cache TTL in seconds. Short enough that a config change is visible almost
#: immediately, long enough to avoid a query per reading during simulation.
CACHE_TTL = 10.0


class ConfigService:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._loaded_at: float = 0.0

    def invalidate(self) -> None:
        self._cache = {}
        self._loaded_at = 0.0

    async def load_all(self, session: AsyncSession, force: bool = False) -> dict[str, Any]:
        if not force and self._cache and (time.monotonic() - self._loaded_at) < CACHE_TTL:
            return self._cache
        rows = (await session.execute(select(SystemConfiguration))).scalars().all()
        merged = {key: default for key, (default, _) in ALL_DEFAULTS.items()}
        for row in rows:
            merged[row.key] = row.value
        self._cache = merged
        self._loaded_at = time.monotonic()
        return merged

    async def get(self, session: AsyncSession, key: str, default: Any = None) -> Any:
        config = await self.load_all(session)
        if key in config:
            return config[key]
        if key in ALL_DEFAULTS:
            return ALL_DEFAULTS[key][0]
        return default

    async def list_all(self, session: AsyncSession) -> list[dict[str, Any]]:
        rows = {
            r.key: r for r in (await session.execute(select(SystemConfiguration))).scalars().all()
        }
        out = []
        for key, (default, description) in ALL_DEFAULTS.items():
            row = rows.get(key)
            out.append(
                {
                    "key": key,
                    "value": row.value if row else default,
                    "default_value": default,
                    "description": row.description if row else description,
                    "version": row.version if row else 0,
                    "is_editable": row.is_editable if row else True,
                    "is_customised": bool(row and row.value != default),
                    "updated_at": row.updated_at.isoformat() if row else None,
                }
            )
        for key, row in rows.items():
            if key not in ALL_DEFAULTS:
                out.append(
                    {
                        "key": key,
                        "value": row.value,
                        "default_value": None,
                        "description": row.description,
                        "version": row.version,
                        "is_editable": row.is_editable,
                        "is_customised": True,
                        "updated_at": row.updated_at.isoformat(),
                    }
                )
        return sorted(out, key=lambda e: e["key"])

    async def set(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        updated_by_id: UUID | None = None,
    ) -> SystemConfiguration:
        if key not in ALL_DEFAULTS:
            raise NotFoundError(
                f"Unknown configuration key {key!r}. Known keys: {sorted(ALL_DEFAULTS)}"
            )
        self._validate(key, value)
        row = (
            await session.execute(select(SystemConfiguration).where(SystemConfiguration.key == key))
        ).scalar_one_or_none()
        if row is None:
            _default, description = ALL_DEFAULTS[key]
            row = SystemConfiguration(key=key, value=value, description=description, version=1)
            session.add(row)
        else:
            if not row.is_editable:
                raise ValidationError(f"Configuration key {key!r} is not editable.")
            row.value = value
            row.version += 1
        row.updated_by_id = updated_by_id
        await session.flush()
        self.invalidate()
        return row

    @staticmethod
    def _validate(key: str, value: Any) -> None:
        """Structural validation against the shape of the default."""
        default = ALL_DEFAULTS[key][0]
        if not isinstance(value, type(default)):
            raise ValidationError(
                f"Configuration {key!r} must be a "
                f"{type(default).__name__}, received {type(value).__name__}."
            )
        if isinstance(default, dict):
            unknown = set(value) - set(default)
            if unknown:
                raise ValidationError(
                    f"Unknown keys for {key!r}: {sorted(unknown)}. Allowed: {sorted(default)}"
                )
            for k, v in value.items():
                expected = default[k]
                if isinstance(expected, (int, float)) and not isinstance(v, (int, float)):
                    raise ValidationError(
                        f"{key}.{k} must be numeric, received {type(v).__name__}."
                    )
                if isinstance(expected, dict) and not isinstance(v, dict):
                    raise ValidationError(f"{key}.{k} must be an object.")
                if isinstance(expected, list) and not isinstance(v, list):
                    raise ValidationError(f"{key}.{k} must be a list.")

        if key == CONFIG_RISK_CATEGORIES:
            required = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
            if set(value) != required:
                raise ValidationError(f"Risk categories must define exactly {sorted(required)}.")
            ordered = [value["LOW"], value["MODERATE"], value["HIGH"], value["CRITICAL"]]
            if ordered != sorted(ordered) or len(set(ordered)) != 4:
                raise ValidationError(
                    "Risk category cut-offs must be strictly increasing from LOW through CRITICAL."
                )
        if key == CONFIG_RISK_SCALE:
            ratio = float(value.get("score_scale_ratio", 0.8))
            if not 0.05 <= ratio <= 1.0:
                raise ValidationError("score_scale_ratio must be between 0.05 and 1.0.")
        if key == CONFIG_RISK_WEIGHTS:
            if any(float(v) < 0 for v in value.values()):
                raise ValidationError("Risk weights must be non-negative.")
            if sum(float(v) for v in value.values()) <= 0:
                raise ValidationError("At least one risk weight must be positive.")
        if key == CONFIG_ROUTE_COSTS:
            for field_name in (
                "avalanche_weight",
                "crevasse_weight",
                "weather_weight",
                "difficulty_weight",
                "base_cost",
            ):
                if field_name in value and float(value[field_name]) < 0:
                    raise ValidationError(
                        f"route.costs.{field_name} must be non-negative "
                        "(negative weights would make A* inadmissible)."
                    )
            if "base_speed_kph" in value and float(value["base_speed_kph"]) <= 0:
                raise ValidationError("base_speed_kph must be positive.")
        if (
            key == CONFIG_SIMULATION
            and "speeds" in value
            and not all(isinstance(s, int) and s > 0 for s in value["speeds"])
        ):
            raise ValidationError("simulation speeds must be positive integers.")

    # --------------------------------------------------------------- builders
    async def risk_engine(self, session: AsyncSession) -> RiskEngine:
        config = await self.load_all(session)
        return RiskEngine(
            thresholds=config[CONFIG_RISK_THRESHOLDS],
            weights=config[CONFIG_RISK_WEIGHTS],
            categories=config[CONFIG_RISK_CATEGORIES],
            scale=config.get(CONFIG_RISK_SCALE),
            config_version=1,
        )

    async def alert_rules(self, session: AsyncSession) -> dict[str, Any]:
        return await self.get(session, CONFIG_ALERT_RULES)

    async def route_costs(self, session: AsyncSession) -> dict[str, Any]:
        return await self.get(session, CONFIG_ROUTE_COSTS)

    async def simulation(self, session: AsyncSession) -> dict[str, Any]:
        return await self.get(session, CONFIG_SIMULATION)

    async def prediction(self, session: AsyncSession) -> dict[str, Any]:
        return await self.get(session, CONFIG_PREDICTION)

    async def thresholds(self, session: AsyncSession) -> dict[str, Any]:
        return await self.get(session, CONFIG_RISK_THRESHOLDS)

    async def seed_defaults(self, session: AsyncSession) -> int:
        """Insert any missing default rows. Idempotent."""
        existing = {
            r.key for r in (await session.execute(select(SystemConfiguration))).scalars().all()
        }
        created = 0
        for key, (default, description) in ALL_DEFAULTS.items():
            if key in existing:
                continue
            session.add(
                SystemConfiguration(key=key, value=default, description=description, version=1)
            )
            created += 1
        if created:
            await session.flush()
            self.invalidate()
        return created


config_service = ConfigService()
