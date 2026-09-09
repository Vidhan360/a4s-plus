"""``/api/v1/config`` — runtime configuration of thresholds, weights and rules."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Request

from app.api.deps import DbSession, require
from app.core.defaults import ALL_DEFAULTS
from app.core.errors import NotFoundError
from app.core.permissions import Perm
from app.schemas.system import ConfigOut, ConfigUpdateRequest
from app.services.audit_service import AuditService
from app.services.config_service import config_service

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=list[ConfigOut])
async def list_config(
    session: DbSession,
    _user: Annotated[Any, require(Perm.CONFIG_READ)],
) -> list[ConfigOut]:
    return [ConfigOut.model_validate(row) for row in await config_service.list_all(session)]


@router.get("/defaults")
async def config_defaults(
    _user: Annotated[Any, require(Perm.CONFIG_READ)],
) -> dict[str, Any]:
    """The shipped defaults, so the UI can offer "restore default"."""
    return {
        "defaults": {
            key: {"value": default, "description": description}
            for key, (default, description) in ALL_DEFAULTS.items()
        }
    }


@router.get("/{key}", response_model=ConfigOut)
async def get_config(
    key: str,
    session: DbSession,
    _user: Annotated[Any, require(Perm.CONFIG_READ)],
) -> ConfigOut:
    rows = await config_service.list_all(session)
    for row in rows:
        if row["key"] == key:
            return ConfigOut.model_validate(row)
    raise NotFoundError(f"Configuration key '{key}' is not recognised.")


@router.put("/{key}", response_model=ConfigOut)
async def update_config(
    request: Request,
    key: str,
    payload: ConfigUpdateRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.CONFIG_WRITE)],
) -> ConfigOut:
    row = await config_service.set(session, key, payload.value, updated_by_id=actor.id)
    await AuditService.log_from_request(
        session,
        request,
        action="config.update",
        resource_type="system_configuration",
        resource_id=key,
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"version": row.version},
    )
    return ConfigOut.model_validate(
        {
            "key": row.key,
            "value": row.value,
            "default_value": ALL_DEFAULTS.get(key, (None, ""))[0],
            "description": row.description,
            "version": row.version,
            "is_editable": row.is_editable,
            "is_customised": True,
            "updated_at": row.updated_at.isoformat(),
        }
    )


@router.post("/{key}/reset", response_model=ConfigOut)
async def reset_config(
    request: Request,
    key: str,
    session: DbSession,
    actor: Annotated[Any, require(Perm.CONFIG_WRITE)],
) -> ConfigOut:
    if key not in ALL_DEFAULTS:
        raise NotFoundError(f"Configuration key '{key}' is not recognised.")
    row = await config_service.set(session, key, ALL_DEFAULTS[key][0], updated_by_id=actor.id)
    await AuditService.log_from_request(
        session,
        request,
        action="config.reset",
        resource_type="system_configuration",
        resource_id=key,
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return ConfigOut.model_validate(
        {
            "key": row.key,
            "value": row.value,
            "default_value": ALL_DEFAULTS[key][0],
            "description": row.description,
            "version": row.version,
            "is_editable": row.is_editable,
            "is_customised": False,
            "updated_at": row.updated_at.isoformat(),
        }
    )
