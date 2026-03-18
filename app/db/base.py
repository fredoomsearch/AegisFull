from __future__ import annotations

"""
SQLAlchemy engine + session factory + DB initialization helpers.

This is the low-level DB wiring. FastAPI dependencies use app.db.deps.get_db.
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.models import Base  # side-effect import to register models

logger = logging.getLogger(__name__)
DISABLE_DB = (os.getenv("AEGIS_DISABLE_DB", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------
# Configuración de la base de datos
# ---------------------------------------------------------

def _build_database_url() -> str:
    raw = (os.getenv("DATABASE_URL") or settings.DB_URL or "").strip()
    if raw:
        return raw
    if DISABLE_DB:
        # Keep imports/startup working in no-DB mode (local demos, smoke tests).
        return "sqlite+pysqlite:///:memory:"

    host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST") or ""
    db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE") or ""
    user = os.getenv("POSTGRES_USER") or os.getenv("PGUSER") or ""
    password = os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD") or ""
    port = os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or "5432"

    if host and db:
        driver = os.getenv("POSTGRES_DRIVER", "psycopg2").strip() or "psycopg2"
        url = URL.create(
            drivername=f"postgresql+{driver}",
            username=user or None,
            password=password or None,
            host=host,
            port=int(port) if port else None,
            database=db,
        )
        return str(url)

    raise RuntimeError("DATABASE_URL or POSTGRES_* env vars must be set for PostgreSQL.")


def _engine_params(db_url: str) -> tuple[URL, dict[str, Any]]:
    url_obj = make_url(db_url)
    backend = url_obj.get_backend_name()
    engine_kwargs: dict[str, Any] = {
        "future": True,
        "echo": (os.getenv("SQL_ECHO") or "").lower() in {"1", "true", "yes", "on"},
    }

    if backend in {"postgresql", "postgres"}:
        engine_kwargs["pool_pre_ping"] = True
        pool_size = int(os.getenv("AEGIS_DB_POOL_SIZE", "5") or "5")
        max_overflow = int(os.getenv("AEGIS_DB_MAX_OVERFLOW", "10") or "10")
        pool_timeout = int(os.getenv("AEGIS_DB_POOL_TIMEOUT", "30") or "30")
        pool_recycle = int(os.getenv("AEGIS_DB_POOL_RECYCLE", "1800") or "1800")

        engine_kwargs.update(
            {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_timeout": pool_timeout,
                "pool_recycle": pool_recycle,
            }
        )
        return url_obj, engine_kwargs

    if backend == "sqlite" and DISABLE_DB:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if (url_obj.database or "").strip() in {"", ":memory:"}:
            # Single in-memory connection shared across sessions.
            engine_kwargs["poolclass"] = StaticPool
        return url_obj, engine_kwargs

    raise ValueError(
        f"Unsupported backend '{backend}'. Only PostgreSQL is allowed unless AEGIS_DISABLE_DB=1."
    )


DATABASE_URL: str = _build_database_url()
_, _engine_kwargs = _engine_params(DATABASE_URL)

engine: Engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine,
    future=True,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# ---------------------------------------------------------
# Init DB
# ---------------------------------------------------------
def init_db(bind_engine: Optional[Engine] = None) -> None:
    _engine = bind_engine or engine
    try:
        Base.metadata.create_all(bind=_engine)
        _ensure_compat_columns(_engine)
        logger.info("Tablas de la base de datos creadas correctamente.")
    except Exception as e:  # noqa: BLE001
        logger.exception("Error al crear las tablas: %s", e)
        raise


def _ensure_compat_columns(bind_engine: Engine) -> None:
    try:
        inspector = inspect(bind_engine)
        columns = {col["name"] for col in inspector.get_columns("conversations")}
    except Exception:
        logger.debug("No se pudo inspeccionar la tabla conversations.", exc_info=True)
        return

    if "session_state_json" not in columns:
        logger.info("Adding missing conversations.session_state_json compatibility column.")
        with bind_engine.begin() as conn:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN session_state_json TEXT NOT NULL DEFAULT '{}'"))


def init_db_manual() -> None:
    try:
        print("Creando tablas manualmente...")
        Base.metadata.create_all(bind=engine)
        print("Tablas creadas correctamente.")
    except Exception as e:  # noqa: BLE001
        print(f"Error al crear tablas: {e}")
        raise


# ---------------------------------------------------------
# Context manager de sesión (útil para scripts/CLI)
# ---------------------------------------------------------
@contextmanager
def get_db() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            logger.exception("get_db (base): rollback failed after exception.")
        raise
    finally:
        try:
            db.close()
        except Exception:
            logger.exception("get_db (base): failed to close DB session.")


if __name__ == "__main__":
    init_db_manual()
