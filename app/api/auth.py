from __future__ import annotations

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


def _issue_token(sub: str, scopes: list[str], ttl_seconds: int, token_type: str) -> str:
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
    scopes = [s for s in req.scopes if s]
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

    scopes = payload.get("scopes") or payload.get("scope") or []
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
        scopes=scopes if isinstance(scopes, list) else [],
    )
