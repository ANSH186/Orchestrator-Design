"""Application configuration loaded from environment variables and .env."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings.

    All settings use the ``PROCUREMENT_`` prefix.  The application is designed to
    run fully offline with ``LLM_PROVIDER=none``; the LLM is an optional
    interpretation aid, not a dependency for deterministic decisions.
    """

    model_config = SettingsConfigDict(
        env_prefix="PROCUREMENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM provider
    llm_provider: Literal["none", "mock", "openai_compatible"] = "none"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = Field(default=40.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_max_concurrency: int = Field(default=4, ge=1, le=64)
    llm_temperature: float = Field(default=0.0, ge=0, le=2)

    # Paths
    data_dir: Path = Path("data")
    playbook_dir: Path = Path("data/playbook/playbook")
    artifacts_dir: Path = Path("artifacts")
    output_dir: Path = Path("output")
    reports_dir: Path = Path("reports")

    # Batch execution
    max_workers: int = Field(default=4, ge=1, le=64)
    cache_enabled: bool = True
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper().strip()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return level

    def ensure_directories(self) -> None:
        for directory in (
            self.artifacts_dir,
            self.output_dir,
            self.reports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def validate_paths(self) -> None:
        if not self.data_dir.exists():
            raise FileNotFoundError(f"data directory not found: {self.data_dir.resolve()}")
        if not (self.data_dir / "threads.csv").exists():
            raise FileNotFoundError(
                f"threads.csv not found under {self.data_dir.resolve()}"
            )
        if not self.playbook_dir.exists():
            raise FileNotFoundError(
                f"playbook directory not found: {self.playbook_dir.resolve()}"
            )

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider in {"openai_compatible", "mock"}


def load_settings(**overrides: object) -> Settings:
    """Load settings with optional test overrides."""

    return Settings(**overrides)
