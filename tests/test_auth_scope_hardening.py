from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from app.api import auth as auth_api


@pytest.mark.anyio
async def test_issue_token_rejects_admin_scope(monkeypatch):
    class DummyRequest:
        cookies = {}
        headers = {}
        class Url:
            scheme = "http"
        url = Url()

    monkeypatch.setattr(
        auth_api,
        "_issue_token",
        lambda sub, scopes, ttl_seconds, token_type: f"{token_type}:{sub}:{','.join(scopes)}",
    )
    with pytest.raises(HTTPException) as exc:
        await auth_api.issue_token(auth_api.TokenRequest(scopes=["admin"], refresh=False), request=DummyRequest(), response=Response())
    assert exc.value.status_code == 403
    assert "Forbidden scopes requested" in str(exc.value.detail)


@pytest.mark.anyio
async def test_issue_token_allows_safe_scopes(monkeypatch):
    class DummyRequest:
        cookies = {}
        headers = {}
        class Url:
            scheme = "http"
        url = Url()

    monkeypatch.setattr(
        auth_api,
        "_issue_token",
        lambda sub, scopes, ttl_seconds, token_type: f"{token_type}:{sub}:{','.join(scopes)}",
    )
    response = Response()
    payload = await auth_api.issue_token(auth_api.TokenRequest(scopes=["chat", "files"], refresh=False), request=DummyRequest(), response=response)
    assert payload.scopes == ["chat", "files"]
    assert payload.cookie_auth is True
    dumped = payload.model_dump()
    assert "access_token" not in dumped
    cookies = [value.decode("latin1") for key, value in response.raw_headers if key.lower() == b"set-cookie"]
    assert any("aegis_access_token=" in cookie and "HttpOnly" in cookie for cookie in cookies)


@pytest.mark.anyio
async def test_refresh_token_rejects_admin_scope(monkeypatch):
    class DummyRequest:
        cookies = {}

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
        await auth_api.refresh_token(auth_api.RefreshRequest(refresh_token="dummy"), request=DummyRequest(), response=Response())
    assert exc.value.status_code == 403
    assert "Forbidden scopes requested" in str(exc.value.detail)
