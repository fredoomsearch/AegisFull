from __future__ import annotations

"""
Outbound proxy pool helper for web providers.

Why this module exists:
- Rotate configured proxies and expose safe fallback to direct requests.
"""

import os
import time
from contextlib import contextmanager
from typing import Dict, Generator, Optional, Tuple

import requests

from app.services import search_state
from app.services.search_state import ProxyUnavailableError

PROXY_LIST_RAW = os.getenv("AEGIS_PROXY_LIST", "").strip()
PROXY_FAILURE_COOLDOWN = float(os.getenv("AEGIS_PROXY_FAILURE_COOLDOWN", "180") or "180")
PROXY_SUCCESS_COOLDOWN_RESET = float(os.getenv("AEGIS_PROXY_SUCCESS_RESET", "0") or "0")
USE_DIRECT_IF_NO_PROXY = os.getenv("AEGIS_PROXY_ALLOW_DIRECT", "1").lower() in {"1", "true", "yes", "on"}
PROXY_SESSION_UA = os.getenv("AEGIS_PROXY_UA", "Mozilla/5.0 (AegisProxy/1.0)")


def _parse_proxy_config(raw: str) -> Dict[str, str]:
    proxies: Dict[str, str] = {}
    if not raw:
        return proxies
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        name, url = entry.split("=", 1)
        name = name.strip()
        url = url.strip()
        if not name or not url:
            continue
        proxies[name] = url
    return proxies


CONFIGURED_PROXIES = _parse_proxy_config(PROXY_LIST_RAW)


def _ensure_registered() -> None:
    for name, url in CONFIGURED_PROXIES.items():
        search_state.register_proxy(name, url)


_ensure_registered()


def _available_proxies() -> list[dict]:
    now = time.time()
    rows = search_state.list_proxies()
    ready = [row for row in rows if (row.get("cooldown_until") or 0) <= now]
    return sorted(
        ready,
        key=lambda r: (r.get("fail_count", 0), -r.get("success_count", 0)),
    )


def acquire_proxy() -> Optional[dict]:
    ready = _available_proxies()
    if ready:
        return ready[0]
    if CONFIGURED_PROXIES:
        if USE_DIRECT_IF_NO_PROXY:
            return None
        raise ProxyUnavailableError("No proxies currently available (cooling down)")
    return None


@contextmanager


def proxy_session() -> Generator[Tuple[requests.Session, Optional[str]], None, None]:
    proxy_info = acquire_proxy()
    session = requests.Session()
    proxy_name: Optional[str] = None
    try:
        session.headers.setdefault("User-Agent", PROXY_SESSION_UA)
        if proxy_info:
            proxy_name = proxy_info["name"]
            proxy_url = proxy_info["proxy_url"]
            session.proxies.update({"http": proxy_url, "https": proxy_url})
        elif not USE_DIRECT_IF_NO_PROXY and CONFIGURED_PROXIES:
            raise ProxyUnavailableError("Direct connections disabled and no proxy available")
        yield session, proxy_name
        if proxy_name:
            search_state.mark_proxy_success(proxy_name)
    except Exception:
        if proxy_name:
            search_state.mark_proxy_failure(proxy_name, PROXY_FAILURE_COOLDOWN)
        raise
    finally:
        session.close()


def proxies_configured() -> bool:
    return bool(CONFIGURED_PROXIES)
