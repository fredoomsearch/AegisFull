from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM config
    USE_LOCAL_LLM: bool = True
    DEFAULT_LLM_MODEL: str = "wizardcoder"

    # PostgreSQL DSN. app.db.base also honors DATABASE_URL directly.
    DB_URL: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


BASE_DIR = Path(__file__).resolve().parent.parent
settings = Settings()
