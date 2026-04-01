from __future__ import annotations

from app.db import base
from sqlalchemy.engine.url import make_url


def test_build_database_url_prefers_database_url_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://user:pass@host:5432/dbname")
    assert base._build_database_url() == "postgresql+psycopg2://user:pass@host:5432/dbname"


def test_build_database_url_can_assemble_postgres_from_parts(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(base.settings, "DB_URL", "")
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_DB", "aegis")
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.delenv("POSTGRES_DRIVER", raising=False)

    url = base._build_database_url()
    url_obj = make_url(url)

    assert url_obj.drivername == "postgresql+psycopg2"
    assert url_obj.username == "postgres"
    assert url_obj.password == "secret"
    assert url_obj.host == "db.internal"
    assert url_obj.port == 5433
    assert url_obj.database == "aegis"


def test_build_database_url_requires_postgres_config(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(base.settings, "DB_URL", "")
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.delenv("PGDATABASE", raising=False)

    try:
        base._build_database_url()
    except RuntimeError as exc:
        assert "DATABASE_URL or POSTGRES_* env vars" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError when PostgreSQL config is missing")


def test_engine_params_accept_postgres_only():
    url_obj, engine_kwargs = base._engine_params("postgresql+psycopg2://user:pass@host:5432/dbname")
    assert url_obj.get_backend_name() == "postgresql"
    assert engine_kwargs["pool_pre_ping"] is True


def test_engine_params_reject_sqlite():
    try:
        base._engine_params("sqlite:///./aegis.db")
    except ValueError as exc:
        assert "Only PostgreSQL is allowed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for sqlite backend")
