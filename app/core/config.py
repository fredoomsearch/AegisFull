from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM config
    USE_LOCAL_LLM: bool = True
    DEFAULT_LLM_MODEL: str = "wizardcoder"

    # PostgreSQL DSN. app.db.base also honors DATABASE_URL directly.
    DB_URL: str = ""

    # Memory encryption (optional - requires cryptography package)
    AEGIS_ENCRYPTION_KEY: str = os.getenv("AEGIS_ENCRYPTION_KEY", "")
    
    # Rate limiting
    AEGIS_RATE_LIMIT_REQUESTS: int = int(os.getenv("AEGIS_RATE_LIMIT_REQUESTS", "100"))
    AEGIS_RATE_LIMIT_WINDOW: int = int(os.getenv("AEGIS_RATE_LIMIT_WINDOW", "60"))

    # Message length
    AEGIS_MAX_MESSAGE_LENGTH: int = int(os.getenv("AEGIS_MAX_MESSAGE_LENGTH", "8000"))

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


BASE_DIR = Path(__file__).resolve().parent.parent
settings = Settings()
