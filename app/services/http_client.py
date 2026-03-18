from __future__ import annotations

"""
Shared HTTP client helpers with optional proxy-pool fallback.

Why this module exists:
- Keep proxy-aware GET request behavior consistent across services.
- Avoid duplicate `_http_get` implementations drifting over time.
"""

import logging
from typing import Any

import requests

from app.services.search_state import ProxyUnavailableError
from app.utils.runtime_helpers import proxies_enabled as _proxies_enabled

try:
    from app.services import proxy_pool
except Exception:  # pragma: no cover
    proxy_pool = None

logger = logging.getLogger(__name__)


def http_get(url: str, **kwargs: Any) -> requests.Response:
    """
    Perform GET with proxy pool when enabled, otherwise direct requests.
    """
    if proxy_pool and _proxies_enabled(proxy_pool):
        try:
            with proxy_pool.proxy_session() as (session, _):
                return session.get(url, **kwargs)
        except ProxyUnavailableError:
            logger.debug("Proxy unavailable; falling back to direct request for %s", url)
    return requests.get(url, **kwargs)
