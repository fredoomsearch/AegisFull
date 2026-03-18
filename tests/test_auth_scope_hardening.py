from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import auth as auth_api


@pytest.mark.anyio
async def test_issue_token_rejects_admin_scope(monkeypatch):
    monkeypatch.setattr(
        auth_api,
        "_issue_token",
        lambda sub, scopes, ttl_seconds, token_type: f"{token_type}:{sub}:{','.join(scopes)}",
    )
    with pytest.raises(HTTPException) as exc:
        await auth_api.issue_token(auth_api.TokenRequest(scopes=["admin"], refresh=False))
    assert exc.value.status_code == 403
    assert "Forbidden scopes requested" in str(exc.value.detail)


@pytest.mark.anyio
async def test_issue_token_allows_safe_scopes(monkeypatch):
    monkeypatch.setattr(
        auth_api,
        "_issue_token",
        lambda sub, scopes, ttl_seconds, token_type: f"{token_type}:{sub}:{','.join(scopes)}",
    )
    payload = await auth_api.issue_token(auth_api.TokenRequest(scopes=["chat", "files"], refresh=False))
    assert payload.access_token.startswith("access:")
    assert payload.scopes == ["chat", "files"]


@pytest.mark.anyio
async def test_refresh_token_rejects_admin_scope(monkeypatch):
    monkeypatch.setattr(
        auth_api,
        "_decode_jwt_token",
        lambda token, required_scope=None: {"type": "refresh", "sub": "user", "scopes": ["chat", "admin"]},
    )
    monkeypatch.setattr(
        auth_api,
        "_issue_token",
        lambda sub, scopes, ttl_seconds, token_type: f"{token_type}:{sub}:{','.join(scopes)}",
    )
    with pytest.raises(HTTPException) as exc:
        await auth_api.refresh_token(auth_api.RefreshRequest(refresh_token="dummy"))
    assert exc.value.status_code == 403
    assert "Forbidden scopes requested" in str(exc.value.detail)
