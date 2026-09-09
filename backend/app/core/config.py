"""Application configuration.

All configuration comes from the environment. There are no hard-coded secrets,
credentials or API keys anywhere in the codebase. In non-development
environments the application refuses to start when a required secret is
missing or still holds a placeholder value.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_MARKERS = ("CHANGE_ME", "changeme", "your-secret", "placeholder")


class Settings(BaseSettings):
    """Runtime settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_prefix="A4S_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"
    app_name: str = "A4S+ — AI-Assisted Altitude Safety System"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"

    # --- Database ---
    database_url: str | None = None
    test_database_url: str | None = None
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Redis ---
    redis_url: str | None = None

    # --- Security ---
    jwt_secret: str = Field(default="", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    cors_origins: str = "http://localhost:3000"
    rate_limit_default: str = "200/minute"
    rate_limit_login: str = "10/minute"
    rate_limit_refresh: str = "30/minute"
    rate_limit_password_change: str = "5/minute"

    # --- Simulation ---
    sim_tick_seconds: float = 2.0
    sim_default_seed: int = 20260909
    sim_autostart: bool = False

    # --- Seed accounts (development/demo only) ---
    # Seeding refuses to run unless these are set, so no password is ever
    # hard-coded in the repository.
    seed_admin_password: str = Field(default="", repr=False)
    seed_commander_password: str = Field(default="", repr=False)
    seed_medical_password: str = Field(default="", repr=False)
    seed_operator_password: str = Field(default="", repr=False)
    seed_viewer_password: str = Field(default="", repr=False)

    # --- ML ---
    ml_artifact_dir: str = "ml/artifacts"
    ml_active_model: str = "lstm"

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _assemble_and_validate(self) -> Settings:
        if not self.database_url:
            user = os.getenv("POSTGRES_USER", "a4s")
            password = os.getenv("POSTGRES_PASSWORD", "")
            host = os.getenv("POSTGRES_HOST", "localhost")
            port = os.getenv("POSTGRES_PORT", "5432")
            name = os.getenv("POSTGRES_DB", "a4s")
            auth = f"{user}:{password}@" if password else f"{user}@"
            self.database_url = f"postgresql+asyncpg://{auth}{host}:{port}/{name}"

        if not self.redis_url:
            host = os.getenv("REDIS_HOST", "localhost")
            port = os.getenv("REDIS_PORT", "6379")
            self.redis_url = f"redis://{host}:{port}/0"

        if not self.jwt_secret:
            if self.env in ("development", "test"):
                # Ephemeral per-process secret: tokens simply do not survive a
                # restart. Never used outside development/test.
                import secrets

                self.jwt_secret = secrets.token_urlsafe(64)
            else:
                raise ValueError(
                    "A4S_JWT_SECRET must be set outside development/test. "
                    'Generate one with: python -c "import secrets;'
                    'print(secrets.token_urlsafe(64))"'
                )

        if self.env in ("staging", "production"):
            if any(m in self.jwt_secret for m in PLACEHOLDER_MARKERS):
                raise ValueError("A4S_JWT_SECRET still contains a placeholder value.")
            if len(self.jwt_secret) < 32:
                raise ValueError("A4S_JWT_SECRET must be at least 32 characters.")
            if self.debug:
                raise ValueError("A4S_DEBUG must be false in staging/production.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
