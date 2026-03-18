from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import deps as deps_api


class _Client:
    host = "10.10.10.10"


class _Request:
    client = _Client()


def test_require_admin_scope_rejects_aegis_api_key_fallback(monkeypatch):
    monkeypatch.setattr(deps_api, "AUTH_MODE", "on")
    monkeypatch.setenv("AEGIS_API_KEY", "user-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-only-key")

    with pytest.raises(HTTPException) as exc:
        deps_api._require_key(
            _Request(),
            "user-key",
            None,
            allowed_envs=("ADMIN_API_KEY",),
            required_scope="admin",
        )

    assert exc.value.status_code == 401


def test_require_admin_scope_accepts_admin_api_key(monkeypatch):
    monkeypatch.setattr(deps_api, "AUTH_MODE", "on")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")

    deps_api._require_key(
        _Request(),
        "admin-key",
        None,
        allowed_envs=("ADMIN_API_KEY",),
        required_scope="admin",
    )
