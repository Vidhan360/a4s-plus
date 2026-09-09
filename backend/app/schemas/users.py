"""User administration schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.permissions import Role

from .common import EmailAddress, ORMModel

VALID_ROLES = {r.value for r in Role}


class PermissionOut(ORMModel):
    code: str
    description: str


class RoleOut(BaseModel):
    code: str
    name: str
    description: str
    permissions: list[str]


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    status: str
    roles: list[str]
    failed_login_count: int
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


def _check_roles(value: list[str]) -> list[str]:
    unknown = sorted(set(value) - VALID_ROLES)
    if unknown:
        raise ValueError(f"Unknown role(s): {', '.join(unknown)}")
    if not value:
        raise ValueError("At least one role is required.")
    return sorted(set(value))


class UserCreate(BaseModel):
    email: EmailAddress
    full_name: str = Field(min_length=2, max_length=128)
    password: str = Field(min_length=12, max_length=256)
    roles: list[str] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: list[str]) -> list[str]:
        return _check_roles(value)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=128)
    status: str | None = None
    roles: list[str] | None = None

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _check_roles(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"ACTIVE", "DISABLED", "LOCKED"}
        if value not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return value


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)
