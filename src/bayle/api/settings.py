"""API settings from BAYLE_API_* environment variables; the token has no default, so start-up fails without it."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TAURI_ORIGINS = ["http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"]
VITE_ORIGINS = ["http://localhost:1420", "http://127.0.0.1:1420"]


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BAYLE_API_")

    token: str = Field(min_length=16)
    allowed_origins: list[str] = TAURI_ORIGINS
    allowed_hosts: list[str] = ["127.0.0.1"]
    dev: bool = False  # adds the Vite dev origins

    @property
    def cors_origins(self) -> list[str]:
        return [*self.allowed_origins, *VITE_ORIGINS] if self.dev else list(self.allowed_origins)
