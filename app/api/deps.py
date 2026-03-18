from __future__ import annotations

"""
Central auth dependencies/guards.

Why this module exists:
- Enforce API key/JWT auth consistently across routers.
- Support scope-aware guards (`files`, `admin`, etc.).
"""

import os
from typing import Optional, Sequence

from fastapi import Header, HTTPException, Request
from app.utils.runtime_helpers import first_csv_token as _first_csv_token

try:
    import jwt  # PyJWT
except Exception:
    jwt = None

_HEADER_ALIAS = "X-API-Key"

# Auth mode:
# - "on"    : always require API key
# - "off"   : disable auth completely
# - "local" : allow localhost to bypass key; require key for non-local
AUTH_MODE = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()

# If you're behind a reverse proxy, request.client.host might be the proxy IP.
# Local bypass is only safe in local dev. Do NOT use AUTH_MODE="local" in production.
LOCALHOSTS = {"127.0.0.1", "::1", "localhost"}
JWT_SECRET = os.getenv("AEGIS_JWT_SECRET") or (os.getenv("AEGIS_API_KEY") or "").split(",")[0].strip()
JWT_ALG = os.getenv("AEGIS_JWT_ALG", "HS256")
JWT_LEEWAY = int(os.getenv("AEGIS_JWT_LEEWAY", "30"))


def _load_keys_from_env(*env_vars: str) -> set[str]:
    """Load comma-separated key lists from one or more env vars."""
    keys: set[str] = set()
    for env_var in env_vars:
        raw = (os.getenv(env_var) or "").strip()
        if raw:
            keys.update({k.strip() for k in raw.split(",") if k.strip()})
    return keys


def _extract_api_key(x_api_key: Optional[str]) -> str:
    """Normalize X-API-Key header to a single credential token."""
    return _first_csv_token(x_api_key)


def _extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract bearer token from Authorization header when present."""
    auth = _first_csv_token(authorization)
    if not auth:
        return ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


def _is_local_request(request: Request) -> bool:
    try:
        host = (request.client.host or "").strip()
    except Exception:
        host = ""
    return host in LOCALHOSTS


def _normalize_scopes(scopes: Optional[Sequence[str] | str]) -> list[str]:
    if not scopes:
        return []
    if isinstance(scopes, str):
        return [s.strip() for s in scopes.replace(",", " ").split() if s.strip()]
    return [s for s in scopes if isinstance(s, str) and s.strip()]


def _decode_jwt_token(token: str, required_scope: Optional[str] = None) -> Optional[dict]:
    """
    Best-effort JWT decode. Returns payload or None if invalid/missing.
    Raises 403 if token is valid but lacks required scope.
    """
    if not token or not JWT_SECRET or jwt is None:
        return None
    try:
        payload = jwt.decode(
          token,
          JWT_SECRET,
          algorithms=[JWT_ALG],
          options={"verify_aud": False},
          leeway=JWT_LEEWAY,
        )
    except Exception:
        return None

    scopes = _normalize_scopes(payload.get("scopes") or payload.get("scope"))
    if required_scope and required_scope not in scopes:
        raise HTTPException(status_code=403, detail="Forbidden: missing scope")
    # exp check is handled by jwt.decode; if expired, decode raises.
    return payload


def _require_key(
    request: Request,
    x_api_key: Optional[str],
    authorization: Optional[str],
    *,
    allowed_envs: tuple[str, ...],
    required_scope: Optional[str] = None,
    misconfig_detail: str = "Server auth misconfigured: set AEGIS_API_KEY or set AEGIS_AUTH_MODE=off",
) -> None:
    """
    API key guard.

    Env:
      - AEGIS_AUTH_MODE = on | off | local
      - AEGIS_API_KEY   = comma-separated keys, e.g. "devkey123,prodkey456"

    Headers supported:
      - X-API-Key: <key>
      - Authorization: Bearer <key>
    """
    mode = AUTH_MODE

    # 1) Auth disabled completely
    if mode == "off":
        return

    # 2) Load allowed keys
    allowed = _load_keys_from_env(*allowed_envs)

    # 3) In local mode, allow localhost without a key (dev convenience)
    if mode == "local" and _is_local_request(request):
        return

    # 4) If auth is ON but there are no static keys and no JWT secret, fail closed.
    #    If JWT secret exists, allow JWT-only auth mode.
    if mode == "on" and not allowed and not JWT_SECRET:
        if _is_local_request(request):
            return
        raise HTTPException(
            status_code=500,
            detail=misconfig_detail,
        )

    # 5) Otherwise, require a valid key/token
    api_key = _extract_api_key(x_api_key)
    bearer_token = _extract_bearer_token(authorization)

    # Accept raw API key
    if allowed and ((api_key and api_key in allowed) or (bearer_token and bearer_token in allowed)):
        return

    # Accept JWT with scope (Authorization bearer token preferred).
    payload = _decode_jwt_token(bearer_token, required_scope=required_scope)
    if payload:
        return

    # Compatibility: allow JWT passed via X-API-Key.
    if api_key and api_key != bearer_token:
        payload = _decode_jwt_token(api_key, required_scope=required_scope)
        if payload:
            return

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias=_HEADER_ALIAS),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> None:
    _require_key(
        request,
        x_api_key,
        authorization,
        allowed_envs=("AEGIS_API_KEY",),
        required_scope=None,
        misconfig_detail="Server auth misconfigured: set AEGIS_API_KEY or set AEGIS_AUTH_MODE=off",
    )


async def require_files_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias=_HEADER_ALIAS),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> None:
    """
    API key guard for file uploads/ingest.

    Env:
      - FILES_API_KEY  = comma-separated keys (optional)
      - AEGIS_API_KEY  = fallback keys
      - AEGIS_AUTH_MODE = on | off | local
    """
    _require_key(
        request,
        x_api_key,
        authorization,
        allowed_envs=("FILES_API_KEY", "AEGIS_API_KEY", ),
        required_scope="files",
        misconfig_detail="Server auth misconfigured: set FILES_API_KEY/AEGIS_API_KEY or set AEGIS_AUTH_MODE=off",
    )


async def require_admin_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias=_HEADER_ALIAS),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> None:
    """
    Admin-only API key guard.

    Env:
      - ADMIN_API_KEY = comma-separated keys

    Headers supported:
      - X-API-Key: <key>
      - Authorization: Bearer <key> (raw key or JWT)

    For JWT, require scope "admin".
    """
    _require_key(
        request,
        x_api_key,
        authorization,
        allowed_envs=("ADMIN_API_KEY",),
        required_scope="admin",
        misconfig_detail="Server admin auth misconfigured: set ADMIN_API_KEY or set AEGIS_AUTH_MODE=off",
    )


def require_scope(scope: str):
    async def _dep(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias=_HEADER_ALIAS),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> None:
        _require_key(
            request,
            x_api_key,
            authorization,
            allowed_envs=("AEGIS_API_KEY",),
            required_scope=scope,
            misconfig_detail="Server auth misconfigured: set AEGIS_API_KEY or set AEGIS_AUTH_MODE=off",
        )
    return _dep


async def require_admin_scope(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias=_HEADER_ALIAS),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> None:
    """
    Admin guard: accepts ADMIN_API_KEY or JWT with scope=admin.
    Never falls back to AEGIS_API_KEY for admin routes.
    """
    _require_key(
        request,
        x_api_key,
        authorization,
        allowed_envs=("ADMIN_API_KEY",),
        required_scope="admin",
        misconfig_detail="Server auth misconfigured: set ADMIN_API_KEY or set AEGIS_AUTH_MODE=off",
    )
