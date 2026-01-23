from __future__ import annotations

import os
import time
from typing import Optional, Sequence

from fastapi import Header, HTTPException, Request

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
    keys: set[str] = set()
    for env_var in env_vars:
        raw = (os.getenv(env_var) or "").strip()
        if raw:
            keys.update({k.strip() for k in raw.split(",") if k.strip()})
    return keys


def _extract_key(x_api_key: Optional[str], authorization: Optional[str]) -> str:
    provided = (x_api_key or "").strip()
    if not provided and authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            provided = auth.split(" ", 1)[1].strip()
    return provided


def _is_local_request(request: Request) -> bool:
    try:
        host = (request.client.host or "").strip()
    except Exception:
        host = ""
    return host in LOCALHOSTS


def _assert_allowed(provided: str, allowed: set[str]) -> None:
    if not provided or provided not in allowed:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


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

    # 4) If auth is ON but no keys exist -> that's a misconfiguration
    #    We fail CLOSED (secure) instead of accidentally exposing the API.
    if mode == "on" and not allowed:
        if _is_local_request(request):
            return
        raise HTTPException(
            status_code=500,
            detail="Server auth misconfigured: set AEGIS_API_KEY or set AEGIS_AUTH_MODE=off",
        )

    # 5) Otherwise, require a valid key
    provided = _extract_key(x_api_key, authorization)

    # Accept raw API key
    if provided and allowed and provided in allowed:
        return

    # Accept JWT with scope
    payload = _decode_jwt_token(provided, required_scope=required_scope)
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
    mode = AUTH_MODE

    if mode == "off":
        return

    allowed = _load_keys_from_env("FILES_API_KEY", "AEGIS_API_KEY")

    if mode == "local" and _is_local_request(request):
        return

    if mode == "on" and not allowed:
        if _is_local_request(request):
            return
        raise HTTPException(
            status_code=500,
            detail="Server auth misconfigured: set FILES_API_KEY/AEGIS_API_KEY or set AEGIS_AUTH_MODE=off",
        )

    provided = _extract_key(x_api_key, authorization)

    if provided and allowed and provided in allowed:
        return
    payload = _decode_jwt_token(provided, required_scope="files")
    if payload:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


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
        )
    return _dep


async def require_admin_scope(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias=_HEADER_ALIAS),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> None:
    """
    Admin guard: accepts ADMIN_API_KEY or JWT with scope=admin.
    """
    # If auth disabled, allow.
    if AUTH_MODE == "off":
        return

    allowed = _load_keys_from_env("ADMIN_API_KEY", "AEGIS_API_KEY")
    if AUTH_MODE == "local" and _is_local_request(request):
        return

    provided = _extract_key(x_api_key, authorization)
    if provided and allowed and provided in allowed:
        return

    payload = _decode_jwt_token(provided, required_scope="admin")
    if payload:
        return

    raise HTTPException(status_code=401, detail="Invalid or missing admin credential")





# How to run it (real-life commands)
# ✅ Production / “don’t expose my API”
# export AEGIS_AUTH_MODE=on
# export AEGIS_API_KEY="prod_super_secret_key"
# uvicorn main:app --host 0.0.0.0 --port 8000
# ✅ Local dev (no auth at all)
# export AEGIS_AUTH_MODE=off
# unset AEGIS_API_KEY
# uvicorn main:app --reload
# ✅ Best dev option (you won’t lock yourself out)
# Local requests can skip the key, but remote must have it:
# export AEGIS_AUTH_MODE=local
# export AEGIS_API_KEY="devkey123"

# TEST ALL MODES

# reuse test:

# # 1) AUTH OFF (no key required)
# export AEGIS_AUTH_MODE=off
# unset AEGIS_API_KEY
# curl -s http://localhost:8000/healthz
# curl -s -X POST http://localhost:8000/chat \
#   -H "Content-Type: application/json" \
#   -d '{"message":"hello","lang":"en","mode":"general"}'
# # 2) AUTH LOCAL (localhost bypass, remote requires key)
# export AEGIS_AUTH_MODE=local
# export AEGIS_API_KEY="devkey123"

# # localhost (no key) - should work
# curl -s -X POST http://localhost:8000/chat \
#   -H "Content-Type: application/json" \
#   -d '{"message":"hello","lang":"en","mode":"general"}'

# # with key (also works)
# curl -s -X POST http://localhost:8000/chat \
#   -H "Content-Type: application/json" \
#   -H "X-API-Key: devkey123" \
#   -d '{"message":"hello","lang":"en","mode":"general"}'
# # 3) AUTH ON (key required everywhere)
# export AEGIS_AUTH_MODE=on
# export AEGIS_API_KEY="prod_super_secret_key"

# # without key -> should fail
# curl -s -X POST http://localhost:8000/chat \
#   -H "Content-Type: application/json" \
#   -d '{"message":"hello","lang":"en","mode":"general"}'

# # with key -> should work
# curl -s -X POST http://localhost:8000/chat \
#   -H "Content-Type: application/json" \
#   -H "X-API-Key: prod_super_secret_key" \
#   -d '{"message":"hello","lang":"en","mode":"general"}'
# # 4) Conversation reuse test
# # First call gets conversation_id
# RESP=$(curl -s -X POST http://localhost:8000/chat \
#   -H "Content-Type: application/json" \
#   -d '{"message":"first","lang":"en","mode":"general"}')
# echo "$RESP"

# # Extract conversation_id (manual copy) and reuse:
# curl -s -X POST http://localhost:8000/chat \
#   -H "Content-Type: application/json" \
#   -d '{"message":"second","lang":"en","mode":"general","conversation_id":"<paste-id>","use_existing":true}'
# If curl works but the UI still hangs at “Typing…”, the LLM might be slow or stuck. Try:

# export AEGIS_FAST_MODE=1 then restart uvicorn.
