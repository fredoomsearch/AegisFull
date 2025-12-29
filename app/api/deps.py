from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, Request

_HEADER_ALIAS = "X-API-Key"

# Auth mode:
# - "on"    : always require API key
# - "off"   : disable auth completely
# - "local" : allow localhost to bypass key; require key for non-local
AUTH_MODE = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()

# If you're behind a reverse proxy, request.client.host might be the proxy IP.
# Local bypass is only safe in local dev. Do NOT use AUTH_MODE="local" in production.
LOCALHOSTS = {"127.0.0.1", "::1", "localhost"}


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


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias=_HEADER_ALIAS),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
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
    allowed = _load_keys_from_env("AEGIS_API_KEY")

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
    _assert_allowed(provided, allowed)


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
    _assert_allowed(provided, allowed)





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