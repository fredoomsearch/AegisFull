from __future__ import annotations

"""
Auth token exchange endpoints.

Why this module exists:
- Exchange API-key trust into short-lived JWT tokens.
- Support access/refresh flow for UI and automation clients.
"""

import time
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import JWT_ALG, JWT_SECRET, _decode_jwt_token, require_api_key

try:
    import jwt
except Exception:  # pragma: no cover - PyJWT optional at import time
    jwt = None


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_api_key)])

DEFAULT_ACCESS_SECS = int(os.getenv("AEGIS_JWT_EXPIRES", "1800"))  # 30m
DEFAULT_REFRESH_SECS = int(os.getenv("AEGIS_JWT_REFRESH_EXPIRES", "86400"))  # 24h
FORBIDDEN_SELF_SCOPES = {"admin"}


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
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    refresh_expires_in: Optional[int] = None
    scopes: List[str] = Field(default_factory=list)


class RefreshRequest(BaseModel):
    refresh_token: str


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


@router.post("/token", response_model=TokenResponse)
async def issue_token(req: TokenRequest) -> TokenResponse:
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

    return TokenResponse(
        access_token=access_token,
        expires_in=access_ttl,
        refresh_token=refresh_token,
        refresh_expires_in=refresh_expires_in,
        scopes=scopes,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest) -> TokenResponse:
    """
    Refresh an access token using a valid refresh token.
    """
    payload = _decode_jwt_token(req.refresh_token, required_scope=None)
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

    return TokenResponse(
        access_token=access_token,
        expires_in=access_ttl,
        refresh_token=refresh_token,
        refresh_expires_in=refresh_ttl,
        scopes=scopes,
    )
