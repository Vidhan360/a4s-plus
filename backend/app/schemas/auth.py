"""Authentication and session schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import EmailAddress, ORMModel


class LoginRequest(BaseModel):
    email: EmailAddress
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=512)
    all_sessions: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds.")


class SessionUser(ORMModel):
    id: str
    email: str
    full_name: str
    status: str
    roles: list[str]
    permissions: list[str]
    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None


class LoginResponse(BaseModel):
    tokens: TokenPair
    user: SessionUser
