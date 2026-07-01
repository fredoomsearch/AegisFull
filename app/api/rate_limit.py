from __future__ import annotations

"""
Rate limiting dependency for API endpoints.

Provides token bucket rate limiting based on API key / user identity.
"""

import os
import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request

# Configuration
RATE_LIMIT_REQUESTS = int(os.getenv("AEGIS_RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("AEGIS_RATE_LIMIT_WINDOW", "60"))  # seconds
RATE_LIMIT_BURST = int(os.getenv("AEGIS_RATE_LIMIT_BURST", "10"))  # burst allowance

# In-memory rate limit storage (per-process)
# For production, use Redis or similar
_rate_limits: dict[str, dict] = defaultdict(lambda: {
    "tokens": RATE_LIMIT_BURST,
    "last_update": time.time()
})


def _get_client_key(request: Request) -> str:
    """
    Get rate limit key for request.
    Uses API key if present, otherwise falls back to IP.
    """
    # Check API key header
    api_key = request.headers.get("X-API-Key", "").strip()
    if api_key:
        return f"key:{api_key[:32]}"  # Truncate for privacy
    
    # Check Authorization header
    auth = request.headers.get("Authorization", "").strip()
    if auth:
        return f"auth:{auth[:32]}"
    
    # Fall back to IP
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


def _refill_tokens(client_key: str) -> None:
    """
    Refill token bucket based on elapsed time.
    """
    now = time.time()
    client_data = _rate_limits[client_key]
    elapsed = now - client_data["last_update"]
    
    # Add tokens based on rate (requests per window)
    tokens_to_add = elapsed * (RATE_LIMIT_REQUESTS / RATE_LIMIT_WINDOW)
    client_data["tokens"] = min(
        RATE_LIMIT_BURST,
        client_data["tokens"] + tokens_to_add
    )
    client_data["last_update"] = now


def _check_rate_limit(request: Request) -> None:
    """
    Check rate limit for request.
    Raises HTTPException 429 if limit exceeded.
    """
    if RATE_LIMIT_REQUESTS <= 0:
        return  # Rate limiting disabled
    
    client_key = _get_client_key(request)
    _refill_tokens(client_key)
    
    client_data = _rate_limits[client_key]
    if client_data["tokens"] < 1:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s"
        )
    
    # Consume token
    client_data["tokens"] -= 1


async def rate_limit_dependency(request: Request) -> None:
    """
    FastAPI dependency for rate limiting.
    
    Usage:
        @router.post("/chat")
        async def chat_endpoint(..., _: None = Depends(rate_limit_dependency)):
            ...
    """
    _check_rate_limit(request)


def get_rate_limit_status(request: Request) -> dict:
    """
    Get current rate limit status for client.
    """
    client_key = _get_client_key(request)
    _refill_tokens(client_key)
    
    client_data = _rate_limits[client_key]
    
    return {
        "remaining_requests": int(client_data["tokens"]),
        "limit": RATE_LIMIT_REQUESTS,
        "window_seconds": RATE_LIMIT_WINDOW,
        "reset_at": client_data["last_update"] + RATE_LIMIT_WINDOW,
    }


def reset_rate_limit(request: Optional[Request] = None, client_key: Optional[str] = None) -> None:
    """
    Reset rate limit for a client (admin function).
    """
    if client_key:
        key = client_key
    elif request:
        key = _get_client_key(request)
    else:
        return
    
    if key in _rate_limits:
        del _rate_limits[key]
