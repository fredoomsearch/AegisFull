from __future__ import annotations

"""
Cross-layer runtime helpers (pure stdlib).

Why this module exists:
- Provide one canonical implementation for tiny helpers used across scripts,
  API, services, and DB layers.
- Reduce exact-clone helper drift without introducing behavior changes.
"""

import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Mapping


def first_csv_token(raw: str | None) -> str:
    """
    Return the first token from a comma-separated credential/header value.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    return value.split(",", 1)[0].strip().strip("\"'")


def runtime_profile_default(env_name: str = "AEGIS_RUNTIME_PROFILE", default: str = "standard") -> str:
    """
    Normalize runtime profile to the supported set.
    """
    raw = (os.getenv(env_name, default) or default).strip().lower()
    return "strict" if raw == "strict" else "standard"


def product_track_default(env_name: str = "AEGIS_PRODUCT_TRACK", default: str = "core") -> str:
    """
    Normalize commercial/runtime product track to the supported set.
    """
    raw = (os.getenv(env_name, default) or default).strip().lower()
    return "full" if raw == "full" else "core"


def env_int(name: str, default: int) -> int:
    """
    Parse integer env var with deterministic fallback.
    """
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def print_json(payload: Mapping[str, Any]) -> None:
    """
    Consistent JSON-line print for script outputs.
    """
    print(json.dumps(dict(payload), ensure_ascii=False))


def now_ms() -> int:
    return int(time.time() * 1000)


def now_ts() -> int:
    return int(time.time())


def utcnow_naive() -> datetime:
    """
    Naive UTC timestamp for DB/JSON compatibility.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def utcnow_db() -> datetime:
    """
    Alias for DB default/onupdate hooks.
    """
    return utcnow_naive()


def compact(text: str) -> str:
    """
    Collapse repeated whitespace into single spaces.
    """
    return " ".join((text or "").split())


def proxies_enabled(proxy_pool_module: Any) -> bool:
    """
    Return whether outbound proxy pool is configured/enabled.
    """
    return bool(getattr(proxy_pool_module, "proxies_configured", lambda: False)())
