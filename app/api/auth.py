from __future__ import annotations

"""
Auth token exchange endpoints.

Why this module exists:
- Exchange API-key trust into short-lived JWT tokens.
- Support access/refresh flow for UI and automation clients.
- Set those JWTs as HttpOnly cookies so the browser does not keep raw tokens.
"""

import time
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import (
    ACCESS_COOKIE_NAME,
    JWT_ALG,
    JWT_SECRET,
    REFRESH_COOKIE_NAME,
    _decode_jwt_token,
    require_api_key,
)

try:
    import jwt
except Exception:  # pragma: no cover - PyJWT optional at import time
    jwt = None


router = APIRouter(prefix="/auth", tags=["auth"])

DEFAULT_ACCESS_SECS = int(os.getenv("AEGIS_JWT_EXPIRES", "1800"))  # 30m
DEFAULT_REFRESH_SECS = int(os.getenv("AEGIS_JWT_REFRESH_EXPIRES", "86400"))  # 24h
FORBIDDEN_SELF_SCOPES = {"admin"}
AUTH_COOKIE_SECURE = (os.getenv("AEGIS_AUTH_COOKIE_SECURE", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
AUTH_COOKIE_SAMESITE = (os.getenv("AEGIS_AUTH_COOKIE_SAMESITE", "lax") or "lax").strip().lower()
AUTH_COOKIE_DOMAIN = (os.getenv("AEGIS_AUTH_COOKIE_DOMAIN") or "").strip() or None
AUTH_COOKIE_PATH = (os.getenv("AEGIS_AUTH_COOKIE_PATH") or "/").strip() or "/"


def _parse_scope_env(name: str, default: str = "") -> list[str]:
    raw = (os.getenv(name, default) or default).strip()
    if not raw:
        return []
    scopes: list[str] = []
    seen: set[str] = set()
    for token in raw.replace(",", " ").split():
        value = token.strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        scopes.append(value)
    return scopes


def _normalize_scope_list(values: list[str] | None) -> list[str]:
    scopes: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        value = str(item or "").strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        scopes.append(value)
    return scopes


SELF_ALLOWED_SCOPES = set(_parse_scope_env("AEGIS_JWT_ALLOWED_SCOPES", "chat files crypto"))
SELF_DEFAULT_SCOPES = _parse_scope_env("AEGIS_JWT_DEFAULT_SCOPES", "")


class TokenRequest(BaseModel):
    scopes: List[str] = Field(default_factory=list, description="Requested scopes")
    sub: Optional[str] = Field(default=None, description="Subject/identifier")
    refresh: bool = Field(default=True, description="Whether to issue a refresh token")


class TokenResponse(BaseModel):
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: Optional[int] = None
    scopes: List[str] = Field(default_factory=list)
    cookie_auth: bool = True


class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = None


def _sanitize_self_scopes(values: list[str] | None) -> list[str]:
    """
    Normalize and enforce self-issuable scopes for auth token flows.
    """
    requested_scopes = _normalize_scope_list(values)
    disallowed_scopes = sorted(
        {
            s
            for s in requested_scopes
            if (s in FORBIDDEN_SELF_SCOPES) or (SELF_ALLOWED_SCOPES and s not in SELF_ALLOWED_SCOPES)
        }
    )
    if disallowed_scopes:
        raise HTTPException(status_code=403, detail=f"Forbidden scopes requested: {', '.join(disallowed_scopes)}")
    return [s for s in requested_scopes if not SELF_ALLOWED_SCOPES or s in SELF_ALLOWED_SCOPES]


def _issue_token(sub: str, scopes: list[str], ttl_seconds: int, token_type: str) -> str:
    """Create signed JWT payload with consistent claims and expiration."""
    if not JWT_SECRET or jwt is None:
        raise HTTPException(status_code=500, detail="JWT not configured")
    now = int(time.time())
    payload = {
        "sub": sub or "user",
        "type": token_type,
        "scopes": scopes,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _cookie_kwargs(max_age: int) -> dict:
    same_site = AUTH_COOKIE_SAMESITE if AUTH_COOKIE_SAMESITE in {"lax", "strict", "none"} else "lax"
    return {
        "httponly": True,
        "samesite": same_site,
        "path": AUTH_COOKIE_PATH,
        "domain": AUTH_COOKIE_DOMAIN,
        "max_age": max(0, int(max_age or 0)),
    }


def _cookie_secure_for_request(request: Optional[Request]) -> bool:
    if AUTH_COOKIE_SECURE:
        return True
    try:
        scheme = str(getattr(getattr(request, "url", None), "scheme", "") or "").strip().lower()
    except Exception:
        scheme = ""
    if scheme == "https":
        return True
    try:
        proto = str(request.headers.get("x-forwarded-proto", "") or "").split(",")[0].strip().lower() if request else ""
    except Exception:
        proto = ""
    return proto == "https"


def _set_auth_cookies(request: Optional[Request], response: Response, access_token: str, refresh_token: Optional[str], access_ttl: int, refresh_ttl: Optional[int]) -> None:
    access_cookie_kwargs = dict(_cookie_kwargs(access_ttl))
    refresh_cookie_kwargs = dict(_cookie_kwargs(refresh_ttl or DEFAULT_REFRESH_SECS))
    access_cookie_kwargs["secure"] = _cookie_secure_for_request(request)
    refresh_cookie_kwargs["secure"] = _cookie_secure_for_request(request)
    response.set_cookie(ACCESS_COOKIE_NAME, access_token, **access_cookie_kwargs)
    if refresh_token:
        response.set_cookie(REFRESH_COOKIE_NAME, refresh_token, **refresh_cookie_kwargs)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path=AUTH_COOKIE_PATH, domain=AUTH_COOKIE_DOMAIN)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=AUTH_COOKIE_PATH, domain=AUTH_COOKIE_DOMAIN)


async def require_refresh_permission(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> None:
    """
    Refresh endpoint guard.

    Accepts:
    - valid refresh cookie
    - valid access cookie / bearer token / API key via normal auth guard
    """
    refresh_cookie = str(request.cookies.get(REFRESH_COOKIE_NAME, "") or "").strip()
    if refresh_cookie:
        payload = _decode_jwt_token(refresh_cookie, required_scope=None)
        if payload and payload.get("type") == "refresh":
            return
    await require_api_key(request, x_api_key=x_api_key, authorization=authorization)


@router.post("/token", response_model=TokenResponse, response_model_exclude_none=True, dependencies=[Depends(require_api_key)])
async def issue_token(req: TokenRequest, request: Request, response: Response) -> TokenResponse:
    """
    Exchange an API key for a short-lived access token (and optional refresh token).
    """
    requested_scopes = _normalize_scope_list(req.scopes)
    if not requested_scopes and SELF_DEFAULT_SCOPES:
        requested_scopes = list(SELF_DEFAULT_SCOPES)
    scopes = _sanitize_self_scopes(requested_scopes)
    access_ttl = DEFAULT_ACCESS_SECS
    refresh_ttl = DEFAULT_REFRESH_SECS

    access_token = _issue_token(req.sub or "user", scopes, access_ttl, token_type="access")
    refresh_token = None
    refresh_expires_in = None
    if req.refresh:
        refresh_token = _issue_token(req.sub or "user", scopes, refresh_ttl, token_type="refresh")
        refresh_expires_in = refresh_ttl

    _set_auth_cookies(request, response, access_token, refresh_token, access_ttl, refresh_expires_in)
    response.headers["Cache-Control"] = "no-store"

    return TokenResponse(
        expires_in=access_ttl,
        refresh_expires_in=refresh_expires_in,
        scopes=scopes,
        cookie_auth=True,
    )


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True, dependencies=[Depends(require_refresh_permission)])
async def refresh_token(req: RefreshRequest, request: Request, response: Response) -> TokenResponse:
    """
    Refresh an access token using a valid refresh token.
    """
    refresh_token_raw = str(req.refresh_token or "").strip()
    if not refresh_token_raw:
        refresh_token_raw = str(request.cookies.get(REFRESH_COOKIE_NAME, "") or "").strip()
    payload = _decode_jwt_token(refresh_token_raw, required_scope=None)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    raw_scopes = payload.get("scopes") or payload.get("scope") or []
    if isinstance(raw_scopes, str):
        scope_values = [raw_scopes]
    elif isinstance(raw_scopes, list):
        scope_values = [str(s) for s in raw_scopes]
    else:
        scope_values = []
    scopes = _sanitize_self_scopes(scope_values)
    sub = payload.get("sub") or "user"

    access_ttl = DEFAULT_ACCESS_SECS
    refresh_ttl = DEFAULT_REFRESH_SECS

    access_token = _issue_token(sub, scopes, access_ttl, token_type="access")
    refresh_token = _issue_token(sub, scopes, refresh_ttl, token_type="refresh")
    _set_auth_cookies(request, response, access_token, refresh_token, access_ttl, refresh_ttl)
    response.headers["Cache-Control"] = "no-store"

    return TokenResponse(
        expires_in=access_ttl,
        refresh_expires_in=refresh_ttl,
        scopes=scopes,
        cookie_auth=True,
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear auth cookies for the current browser session."""
    _clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "cookie_auth": False}
