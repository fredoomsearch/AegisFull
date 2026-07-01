from __future__ import annotations

"""
Web search service for AEGIS.

Public API:
    web_search_structured(query: str, num_results: int = 3, lang: Optional[str] = None) -> list[WebSearchResult]

Why this module exists:
- Orchestrate multiple providers with cooldown/rotation.
- Return explicit source metadata (`live/cache/unavailable`) to avoid fake success.
"""

import html as _html
import hashlib
import logging
import os
import re
import time
from threading import Event, RLock, Thread
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.core.types import WebSearchResult
from app.services import search_state
from app.services.http_client import http_get
from app.services.search_state import (
    ProviderCooldownError,
    ProviderLimitError,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    from duckduckgo_search import DDGS  # type: ignore
    _HAS_DDGS = True
except Exception:  # noqa: BLE001
    DDGS = None  # type: ignore[assignment]
    _HAS_DDGS = False
    logger.info("duckduckgo_search not installed; web search will use HTTP fallbacks.")

DEFAULT_RESULTS = 8
MAX_RESULTS = 10

DDG_REGION = os.getenv("AEGIS_SEARCH_REGION", "us-en")
DDG_SAFESRCH = os.getenv("AEGIS_SEARCH_SAFE", "off")
DDG_LANG = (os.getenv("AEGIS_SEARCH_LANG", "en-us") or "en-us").lower()
HTTP_TIMEOUT = float(os.getenv("AEGIS_SEARCH_TIMEOUT", "8.0") or "8.0")

MAX_QUERY_CHARS = int(os.getenv("AEGIS_SEARCH_QUERY_MAX_CHARS", "220") or "220")

CACHE_TTL_SECONDS = float(os.getenv("AEGIS_SEARCH_CACHE_TTL", "60") or "60")
DISK_CACHE_TTL_SECONDS = float(os.getenv("AEGIS_SEARCH_CACHE_DISK_TTL", "300") or "300")
PROVIDER_ORDER = [
    p.strip()
    for p in (
        os.getenv("AEGIS_SEARCH_PROVIDERS")
        or "brave_html,startpage_html,qwant_html,ddg_html,ddg_json,ddgs"
    ).split(",")
    if p.strip()
]
if not PROVIDER_ORDER:
    PROVIDER_ORDER = ["brave_html", "startpage_html", "qwant_html", "ddg_html", "ddg_json", "ddgs"]

ROTATION_MODE = (os.getenv("AEGIS_SEARCH_ROTATION_MODE", "auto") or "auto").strip().lower()
QUERY_SHARD_ROTATION = (os.getenv("AEGIS_SEARCH_QUERY_SHARD_ROTATION", "1") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

WARMUP_ON_START = os.getenv("AEGIS_SEARCH_WARMUP_ON_START", "1").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WARMUP_INTERVAL_SECONDS = float(os.getenv("AEGIS_SEARCH_WARMUP_INTERVAL", "0") or "0")
WARMUP_QUERIES = [
    q.strip()
    for q in (os.getenv("AEGIS_SEARCH_WARMUP_QUERIES") or "test connection,python news").split(
        ","
    )
    if q.strip()
]

_cache: dict[Tuple[str, int, str], Tuple[float, Tuple[WebSearchResult, ...]]] = {}
_cache_lock = RLock()


def _resolve_lang(lang: Optional[str]) -> str:
    if not lang:
        return DDG_LANG
    raw = lang.strip().lower().replace("_", "-")
    if raw in {"es", "es-es", "es-mx", "es-419", "spanish"}:
        return "es-es"
    if raw in {"en", "en-us", "en-gb", "english"}:
        return "en-us"
    if "-" not in raw and len(raw) == 2:
        return f"{raw}-{raw}"
    return raw


def _accept_language_header(lang_code: str) -> str:
    base = (lang_code or "en").split("-", 1)[0]
    if base == "es":
        return "es-ES,es;q=0.9,en;q=0.7"
    if base == "en":
        return "en-US,en;q=0.9,es;q=0.6"
    return f"{lang_code},{base};q=0.9,en;q=0.7"


def _startpage_lang(lang_code: str) -> str:
    base = (lang_code or "en").split("-", 1)[0]
    return "spanish" if base == "es" else "english"


class ProviderConfig(Tuple):
    name: str
    func: Callable[[str, int, str], List[WebSearchResult]]
    limits: Sequence[tuple[int, int]]
    cooldown_seconds: int
    error_cooldown_seconds: int


def _limit_from_env(env_name: str, default: str) -> int:
    raw = os.getenv(env_name)
    if raw is None or raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


_PROVIDERS: Dict[str, Dict[str, object]] = {
    "ddgs": {
        "func": lambda query, n, lang=None: _search_with_ddgs(query, n, lang),
        "limits": [
            (60, _limit_from_env("AEGIS_SEARCH_DDGS_PER_MIN", "40")),
            (86400, _limit_from_env("AEGIS_SEARCH_DDGS_PER_DAY", "2000")),
        ],
        "cooldown_seconds": _limit_from_env("AEGIS_SEARCH_DDGS_COOLDOWN", "60"),
        "error_cooldown_seconds": _limit_from_env("AEGIS_SEARCH_DDGS_ERROR_COOLDOWN", "30"),
    },
    "ddg_html": {
        "func": lambda query, n, lang=None: _search_with_ddg_html(query, n, lang),
        "limits": [
            (60, _limit_from_env("AEGIS_SEARCH_DDGHTML_PER_MIN", "30")),
            (86400, _limit_from_env("AEGIS_SEARCH_DDGHTML_PER_DAY", "1500")),
        ],
        "cooldown_seconds": _limit_from_env("AEGIS_SEARCH_DDGHTML_COOLDOWN", "90"),
        "error_cooldown_seconds": _limit_from_env("AEGIS_SEARCH_DDGHTML_ERROR_COOLDOWN", "45"),
    },
    "ddg_json": {
        "func": lambda query, n, lang=None: _search_with_ddg_json(query, n, lang),
        "limits": [
            (60, _limit_from_env("AEGIS_SEARCH_DDGJSON_PER_MIN", "20")),
            (86400, _limit_from_env("AEGIS_SEARCH_DDGJSON_PER_DAY", "500")),
        ],
        "cooldown_seconds": _limit_from_env("AEGIS_SEARCH_DDGJSON_COOLDOWN", "120"),
        "error_cooldown_seconds": _limit_from_env("AEGIS_SEARCH_DDGJSON_ERROR_COOLDOWN", "60"),
    },
    "qwant_html": {
        "func": lambda query, n, lang=None: _search_with_qwant_html(query, n, lang),
        "limits": [
            (60, _limit_from_env("AEGIS_SEARCH_QWANT_PER_MIN", "20")),
            (86400, _limit_from_env("AEGIS_SEARCH_QWANT_PER_DAY", "800")),
        ],
        "cooldown_seconds": _limit_from_env("AEGIS_SEARCH_QWANT_COOLDOWN", "90"),
        "error_cooldown_seconds": _limit_from_env("AEGIS_SEARCH_QWANT_ERROR_COOLDOWN", "45"),
    },
    "startpage_html": {
        "func": lambda query, n, lang=None: _search_with_startpage_html(query, n, lang),
        "limits": [
            (60, _limit_from_env("AEGIS_SEARCH_STARTPAGE_PER_MIN", "20")),
            (86400, _limit_from_env("AEGIS_SEARCH_STARTPAGE_PER_DAY", "800")),
        ],
        "cooldown_seconds": _limit_from_env("AEGIS_SEARCH_STARTPAGE_COOLDOWN", "120"),
        "error_cooldown_seconds": _limit_from_env("AEGIS_SEARCH_STARTPAGE_ERROR_COOLDOWN", "60"),
    },
    "brave_html": {
        "func": lambda query, n, lang=None: _search_with_brave_html(query, n, lang),
        "limits": [
            (60, _limit_from_env("AEGIS_SEARCH_BRAVE_PER_MIN", "15")),
            (86400, _limit_from_env("AEGIS_SEARCH_BRAVE_PER_DAY", "600")),
        ],
        "cooldown_seconds": _limit_from_env("AEGIS_SEARCH_BRAVE_COOLDOWN", "150"),
        "error_cooldown_seconds": _limit_from_env("AEGIS_SEARCH_BRAVE_ERROR_COOLDOWN", "75"),
    },
}


def _provider_transport(provider_name: str) -> str:
    if provider_name == "ddgs":
        return "python"
    if provider_name.endswith("_html"):
        return "html"
    if provider_name.endswith("_json"):
        return "json"
    return "custom"


def _provider_availability(provider_name: str) -> dict[str, Any]:
    cfg = _PROVIDERS.get(provider_name)
    if cfg is None:
        return {
            "available": False,
            "configured": False,
            "reason": "provider_not_configured",
            "transport": _provider_transport(provider_name),
        }
    if provider_name == "ddgs" and not _HAS_DDGS:
        return {
            "available": False,
            "configured": True,
            "reason": "duckduckgo_search_not_installed",
            "transport": _provider_transport(provider_name),
        }
    return {
        "available": True,
        "configured": True,
        "reason": "",
        "transport": _provider_transport(provider_name),
    }


def _provider_signal_cost(windows: Sequence[dict[str, Any]]) -> tuple[float, float]:
    call_cost = 0.0
    error_cost = 0.0
    for item in windows:
        window_seconds = int(item.get("window_seconds") or 0)
        weight = 4.0 if 0 < window_seconds <= 60 else 1.0
        call_cost += float(item.get("call_count") or 0) * weight
        error_cost += float(item.get("error_count") or 0) * weight
    return call_cost, error_cost


def _query_rotation_offset(query: str, lang_code: str, size: int) -> int:
    if size <= 1 or not QUERY_SHARD_ROTATION:
        return 0
    seed = f"{lang_code}:{query}".encode("utf-8", errors="ignore")
    digest = hashlib.sha1(seed).digest()
    return int.from_bytes(digest[:4], "big") % size


def _resolve_provider_plan(query: str, lang_code: str) -> tuple[list[str], list[dict[str, Any]]]:
    snapshot_rows = {
        str(row.get("provider") or "").strip(): row
        for row in search_state.provider_snapshot(PROVIDER_ORDER)
    }
    provider_rows: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []
    cooling_rows: list[dict[str, Any]] = []
    unavailable_rows: list[dict[str, Any]] = []

    for base_index, provider_name in enumerate(PROVIDER_ORDER):
        availability = _provider_availability(provider_name)
        row = snapshot_rows.get(provider_name) or {
            "provider": provider_name,
            "status": "ready",
            "cooldown_until": 0.0,
            "cooling_down": False,
            "windows": [],
        }
        windows = list(row.get("windows") or [])
        call_cost, error_cost = _provider_signal_cost(windows)
        entry = {
            **row,
            "provider": provider_name,
            "available": bool(availability.get("available")),
            "configured": bool(availability.get("configured")),
            "reason": str(availability.get("reason") or ""),
            "transport": str(availability.get("transport") or ""),
            "call_cost": call_cost,
            "error_cost": error_cost,
            "base_index": base_index,
        }
        provider_rows.append(entry)
        if not entry["available"]:
            unavailable_rows.append(entry)
        elif bool(entry.get("cooling_down")):
            cooling_rows.append(entry)
        else:
            ready_rows.append(entry)

    ready_rows.sort(key=lambda item: (float(item.get("error_cost") or 0.0), float(item.get("call_cost") or 0.0), int(item.get("base_index") or 0)))
    cooling_rows.sort(key=lambda item: (float(item.get("cooldown_until") or 0.0), float(item.get("error_cost") or 0.0), float(item.get("call_cost") or 0.0), int(item.get("base_index") or 0)))
    unavailable_rows.sort(key=lambda item: (str(item.get("reason") or ""), int(item.get("base_index") or 0)))

    if ROTATION_MODE in {"auto", "balanced", "health"} and ready_rows:
        offset = _query_rotation_offset(query, lang_code, len(ready_rows))
        if offset:
            ready_rows = ready_rows[offset:] + ready_rows[:offset]

    effective_order = [str(item.get("provider") or "").strip() for item in ready_rows + cooling_rows + unavailable_rows if str(item.get("provider") or "").strip()]
    return effective_order, provider_rows

# DuckDuckGo HTML regex: grab <a class="result__a" href="...">Title</a>
_DDG_A_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

# Some DDG pages may require JS; detect common block pages
_BLOCK_MARKERS = ("enable javascript", "requires javascript", "unusual traffic", "robot")


def _clean_query(q: str) -> str:
    q = " ".join((q or "").split())
    if len(q) > MAX_QUERY_CHARS:
        q = q[:MAX_QUERY_CHARS].rsplit(" ", 1)[0] or q[:MAX_QUERY_CHARS]
    return q.strip()


def _modify_query_for_retry(query: str) -> str:
    """
    Modify query for retry when stale cache is used.
    Strategies:
    - Add "latest" if not present
    - Use shorter core terms
    - Remove modifiers and focus on key terms
    """
    q = (query or "").strip().lower()
    if not q:
        return query

    # Strategy 1: Add "latest" or "current" if not present
    if "latest" not in q and "current" not in q and "recent" not in q:
        # Try adding latest
        return f"{query} latest"

    # Strategy 2: Extract core terms (remove adjectives, modifiers)
    q = re.sub(r"\b(new|current|latest|recent|best|top|popular|how to|what is|why|when|where)\b", "", q)
    q = re.sub(r"\s+", " ", q).strip()

    # If core terms exist, try with them
    if len(q) >= 3:
        return q

    # Strategy 3: Generic fallback
    return query


def _should_retry_with_modified_query(
    original_query: str,
    stale_cache_age_seconds: float,
    meta: Dict[str, Any],
) -> bool:
    """
    Decide whether to retry with modified query based on stale cache age.
    Returns True if stale cache is too old (>5 minutes).
    """
    if not stale_cache_age_seconds:
        return False

    STALE_THRESHOLD_SECONDS = 300.0  # 5 minutes

    # Retry if stale cache is old
    if stale_cache_age_seconds > STALE_THRESHOLD_SECONDS:
        return True

    # Also check if the source metadata indicates problems
    source = str(meta.get("source") or "").strip().lower()
    if source == "stale-cache":
        return True

    return False


def _decode_ddg_href(href: str) -> str:
    """
    DDG HTML results often use redirect links like:
      /l/?kh=-1&uddg=https%3A%2F%2Fexample.com
    Decode to the real destination URL.
    """
    href = (href or "").strip()
    if not href:
        return ""

    # Normalize scheme-less
    if href.startswith("//"):
        href = "https:" + href

    # Make absolute if relative
    if href.startswith("/"):
        href = urljoin("https://duckduckgo.com", href)

    try:
        p = urlparse(href)
        qs = parse_qs(p.query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0]).strip()
    except Exception:
        pass

    return href.strip()


def _normalize_result(title: str | None, snippet: str | None, link: str | None) -> Optional[WebSearchResult]:
    link = (link or "").strip()
    if not link:
        return None
    return WebSearchResult(
        title=(title or "").strip(),
        snippet=(snippet or "").strip(),
        link=link,
    )


def _get_memory_cache(query: str, num_results: int, lang: str) -> Optional[Tuple[WebSearchResult, ...]]:
    key = (query, num_results, lang)
    with _cache_lock:
        item = _cache.get(key)
        if not item:
            return None
        ts, payload = item
        if time.time() - ts > CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        return payload


def _set_memory_cache(query: str, num_results: int, lang: str, results: Sequence[WebSearchResult]) -> None:
    key = (query, num_results, lang)
    with _cache_lock:
        _cache[key] = (time.time(), tuple(results))


def _fetch_cached_results(query: str, num_results: int, lang: str) -> Optional[List[WebSearchResult]]:
    mem = _get_memory_cache(query, num_results, lang)
    if mem:
        return list(mem)

    meta = search_state.get_cached_results_meta(query, num_results, lang=lang, allow_stale=True)
    if meta and meta.get("stale"):
        return None

    cached = search_state.get_cached_results(query, num_results, lang=lang)
    if not cached:
        return None
    try:
        parsed = [WebSearchResult(**item) for item in cached]
    except Exception:
        return None
    _set_memory_cache(query, num_results, lang, parsed)
    return parsed


def _persist_cache(query: str, num_results: int, lang: str, provider: str, results: Sequence[WebSearchResult]) -> None:
    _set_memory_cache(query, num_results, lang, results)
    payload = [r.to_dict() for r in results]
    search_state.set_cached_results(query, num_results, provider, payload, DISK_CACHE_TTL_SECONDS, lang=lang)


def _build_meta(
    *,
    cleaned_query: str,
    num_results: int,
    lang: str,
    status: str,
    source: str,
    provider: str = "",
    results: int = 0,
    attempted: bool = False,
    cache_used: bool = False,
    stale_cache_used: bool = False,
    live_web_used: bool = False,
    fetched_at: float | None = None,
    expires_at: float | None = None,
    providers_tried: Sequence[str] | None = None,
    providers_skipped: Sequence[str] | None = None,
    effective_provider_order: Sequence[str] | None = None,
    rotation_mode: str = "",
) -> Dict[str, Any]:
    return {
        "query": cleaned_query,
        "requested_results": int(num_results),
        "lang": lang,
        "status": status,
        "source": source,
        "provider": provider,
        "results": int(results),
        "attempted": bool(attempted),
        "cache_used": bool(cache_used),
        "stale_cache_used": bool(stale_cache_used),
        "live_web_used": bool(live_web_used),
        "fetched_at": float(fetched_at or 0.0),
        "expires_at": float(expires_at or 0.0),
        "providers_tried": [str(item) for item in (providers_tried or []) if str(item).strip()],
        "providers_skipped": [str(item) for item in (providers_skipped or []) if str(item).strip()],
        "effective_provider_order": [str(item) for item in (effective_provider_order or []) if str(item).strip()],
        "rotation_mode": str(rotation_mode or ROTATION_MODE or "fixed"),
    }


def web_search_structured_with_meta(
    query: str,
    num_results: int = DEFAULT_RESULTS,
    lang: Optional[str] = None,
) -> tuple[list[WebSearchResult], Dict[str, Any]]:
    """Search with provider orchestration and return results + runtime metadata."""
    try:
        cleaned = _clean_query(query)
        lang_code = _resolve_lang(lang)
        n = max(1, min(num_results, MAX_RESULTS))

        if not cleaned:
            return [], _build_meta(
                cleaned_query="",
                num_results=n,
                lang=lang_code,
                status="empty",
                source="none",
            )

        mem = _get_memory_cache(cleaned, n, lang_code)
        if mem:
            disk_meta = search_state.get_cached_results_meta(cleaned, n, lang=lang_code, allow_stale=True) or {}
            return list(mem), _build_meta(
                cleaned_query=cleaned,
                num_results=n,
                lang=lang_code,
                status="cache",
                source="cache",
                provider=str(disk_meta.get("provider") or "memory"),
                results=len(mem),
                cache_used=True,
                fetched_at=float(disk_meta.get("fetched_at") or 0.0),
                expires_at=float(disk_meta.get("expires_at") or 0.0),
            )

        disk_meta = search_state.get_cached_results_meta(cleaned, n, lang=lang_code, allow_stale=True)
        if disk_meta and not bool(disk_meta.get("stale")):
            cached = search_state.get_cached_results(cleaned, n, lang=lang_code)
            if cached:
                try:
                    parsed = [WebSearchResult(**item) for item in cached]
                    _set_memory_cache(cleaned, n, lang_code, parsed)
                    return parsed, _build_meta(
                        cleaned_query=cleaned,
                        num_results=n,
                        lang=lang_code,
                        status="cache",
                        source="cache",
                        provider=str(disk_meta.get("provider") or "cache"),
                        results=len(parsed),
                        cache_used=True,
                        fetched_at=float(disk_meta.get("fetched_at") or 0.0),
                        expires_at=float(disk_meta.get("expires_at") or 0.0),
                    )
                except Exception:
                    logger.debug("Failed to parse cached results for %r", cleaned)

        providers_tried: list[str] = []
        effective_provider_order, provider_rows = _resolve_provider_plan(cleaned, lang_code)
        providers_skipped: list[str] = [
            f"{str(row.get('provider') or '').strip()}:{str(row.get('reason') or '').strip()}"
            for row in provider_rows
            if not bool(row.get("available")) and str(row.get("provider") or "").strip() and str(row.get("reason") or "").strip()
        ]
        for provider_name in effective_provider_order:
            cfg = _PROVIDERS.get(provider_name)
            if not cfg:
                logger.debug("web_search_structured_with_meta: unknown provider %s", provider_name)
                providers_skipped.append(f"{provider_name}:unknown_provider")
                continue
            availability = _provider_availability(provider_name)
            if not bool(availability.get("available")):
                reason = str(availability.get("reason") or "unavailable").strip() or "unavailable"
                skipped_key = f"{provider_name}:{reason}"
                if skipped_key not in providers_skipped:
                    providers_skipped.append(skipped_key)
                continue
            providers_tried.append(provider_name)
            try:
                results = _call_provider(provider_name, cfg, cleaned, n, lang_code)
            except ProviderCooldownError as exc:
                logger.info("Provider %s cooling down: %s", provider_name, exc)
                providers_skipped.append(f"{provider_name}:cooldown")
                continue
            except ProviderLimitError as exc:
                logger.info("Provider %s quota hit: %s", provider_name, exc)
                providers_skipped.append(f"{provider_name}:quota")
                continue
            except Exception:
                providers_skipped.append(f"{provider_name}:error")
                continue

            if not results:
                logger.debug("Provider %s returned no results for %r", provider_name, cleaned)
                providers_skipped.append(f"{provider_name}:empty")
                continue

            trimmed = results[:n]
            _persist_cache(cleaned, n, lang_code, provider_name, trimmed)
            return trimmed, _build_meta(
                cleaned_query=cleaned,
                num_results=n,
                lang=lang_code,
                status="live",
                source="live",
                provider=provider_name,
                results=len(trimmed),
                attempted=True,
                live_web_used=True,
                providers_tried=providers_tried,
                providers_skipped=providers_skipped,
                effective_provider_order=effective_provider_order,
                rotation_mode=ROTATION_MODE,
            )

        logger.warning(
            "web_search_structured: all providers exhausted for %r (tried=%s skipped=%s)",
            cleaned,
            providers_tried,
            providers_skipped,
)
        stale = search_state.get_stale_cached_results(cleaned, n, lang=lang_code)
        if stale:
            try:
                restored = [WebSearchResult(**item) for item in stale][:n]
                stale_meta = search_state.get_cached_results_meta(cleaned, n, lang=lang_code, allow_stale=True) or {}
                stale_fetched_at = float(stale_meta.get("fetched_at") or 0.0)
                stale_age_seconds = time.time() - stale_fetched_at if stale_fetched_at > 0 else 0.0
                
                # Issue #4: Check if we should retry with modified query on stale cache
                should_retry = _should_retry_with_modified_query(cleaned, stale_age_seconds, stale_meta)
                
                if should_retry:
                    # Retry with modified query for fresh results
                    modified_query = _modify_query_for_retry(cleaned)
                    logger.info("Retrying with modified query %r (original: %r, stale_age: %.1fs)", modified_query, cleaned, stale_age_seconds)
                    
                    # Clear stale cache and retry search
                    search_state.clear_cached_results(modified_query, n, lang=lang_code)
                    
                    # Attempt retry with modified query
                    retry_providers_tried: list[str] = []
                    retry_effective_order, retry_provider_rows = _resolve_provider_plan(modified_query, lang_code)
                    
                    for retry_provider in retry_effective_order:
                        retry_cfg = _PROVIDERS.get(retry_provider)
                        if not retry_cfg:
                            continue
                        retry_avail = _provider_availability(retry_provider)
                        if not bool(retry_avail.get("available")):
                            continue
                        
                        retry_providers_tried.append(retry_provider)
                        try:
                            retry_results = _call_provider(retry_provider, retry_cfg, modified_query, n, lang_code)
                        except Exception:
                            continue
                        
                        if retry_results:
                            trimmed_retry = retry_results[:n]
                            _persist_cache(modified_query, n, lang_code, retry_provider, trimmed_retry)
                            logger.info("Retry succeeded with provider %s for query %r", retry_provider, modified_query)
                            return trimmed_retry, _build_meta(
                                cleaned_query=modified_query,
                                num_results=n,
                                lang=lang_code,
                                status="live",
                                source="live",
                                provider=retry_provider,
                                results=len(trimmed_retry),
                                attempted=True,
                                live_web_used=True,
                                providers_tried=providers_tried + retry_providers_tried,
                                providers_skipped=providers_skipped,
                                effective_provider_order=effective_provider_order,
                                rotation_mode=ROTATION_MODE,
                            )
                    
                    # If retry failed, log and fall back to stale cache
                    logger.warning("Retry failed for %r, falling back to stale cache", cleaned)
                
                logger.info("Using stale cache for %r (age: %.1fs) after provider exhaustion.", cleaned, stale_age_seconds)
                return restored, _build_meta(
                    cleaned_query=cleaned,
                    num_results=n,
                    lang=lang_code,
                    status="stale-cache",
                    source="stale-cache",
                    provider=str(stale_meta.get("provider") or "cache"),
                    results=len(restored),
                    attempted=True,
                    cache_used=True,
                    stale_cache_used=True,
                    fetched_at=stale_fetched_at,
                    expires_at=float(stale_meta.get("expires_at") or 0.0),
                    providers_tried=providers_tried,
                    providers_skipped=providers_skipped,
                    effective_provider_order=effective_provider_order,
                    rotation_mode=ROTATION_MODE,
                )
            except Exception:
                logger.debug("Failed to parse stale cache for %r", cleaned)
        return [], _build_meta(
            cleaned_query=cleaned,
            num_results=n,
            lang=lang_code,
            status="unavailable",
            source="none",
            attempted=True,
            providers_tried=providers_tried,
            providers_skipped=providers_skipped,
            effective_provider_order=effective_provider_order,
            rotation_mode=ROTATION_MODE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("web_search_structured_with_meta failed for query=%r: %s", query, exc)
        return [], _build_meta(
            cleaned_query=_clean_query(query),
            num_results=max(1, min(num_results, MAX_RESULTS)),
            lang=_resolve_lang(lang),
            status="error",
            source="none",
            attempted=True,
        )


def _search_with_ddgs(query: str, num_results: int, lang: Optional[str] = None) -> List[WebSearchResult]:
    if not _HAS_DDGS:
        return []

    results: List[WebSearchResult] = []
    lang_code = _resolve_lang(lang)
    try:
        deadline = time.monotonic() + HTTP_TIMEOUT
        with DDGS(timeout=HTTP_TIMEOUT) as ddgs:  # type: ignore[operator]
            # Try a couple backends; versions vary a lot in behavior.
            backends = [None, "html", "lite"]

            for backend in backends:
                if time.monotonic() > deadline:
                    logger.warning("DDGS search timed out before backend=%r for query=%r", backend, query)
                    break
                try:
                    kwargs = dict(
                        safesearch=DDG_SAFESRCH,
                        region=DDG_REGION,
                        timelimit="d",
                    )
                    kwargs["language"] = lang_code
                    if backend:
                        kwargs["backend"] = backend

                    for item in ddgs.text(query, max_results=num_results, **kwargs):
                        r = _normalize_result(
                            item.get("title"),
                            item.get("body"),
                            item.get("href") or item.get("url"),
                        )
                        if r:
                            results.append(r)
                        if len(results) >= num_results or time.monotonic() > deadline:
                            break

                    if results:
                        return results[:num_results]

                except TypeError:
                    # Minimal call if this installed version hates kwargs
                    for item in ddgs.text(query, max_results=num_results):
                        r = _normalize_result(
                            item.get("title"),
                            item.get("body"),
                            item.get("href") or item.get("url"),
                        )
                        if r:
                            results.append(r)
                        if len(results) >= num_results or time.monotonic() > deadline:
                            break
                    if results:
                        return results[:num_results]

                except Exception as exc:  # noqa: BLE001
                    logger.warning("DDGS backend=%r failed for query=%r: %s", backend, query, exc)
                    results = []
                    continue

    except Exception as exc:  # noqa: BLE001
        logger.exception("DDGS search failed for query=%r: %s", query, exc)

    return []


def _search_with_ddg_html(query: str, num_results: int, lang: Optional[str] = None) -> List[WebSearchResult]:
    """
    Real web search fallback by fetching DuckDuckGo HTML results and parsing links.
    This avoids the Instant Answer API limitation (often returns no URLs).
    """
    endpoints = (
        "https://html.duckduckgo.com/html/",
        "https://duckduckgo.com/html/",
        "https://lite.duckduckgo.com/lite/",
    )

    lang_code = _resolve_lang(lang)
    headers = {
        "User-Agent": "Mozilla/5.0 (AegisChat)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": _accept_language_header(lang_code),
    }

    for base in endpoints:
        try:
            resp = http_get(
                base,
                params={"q": query, "kl": lang_code},
                timeout=HTTP_TIMEOUT,
                headers=headers,
                allow_redirects=True,
            )
            if resp.status_code >= 400:
                continue

            text = resp.text or ""
            low = text.lower()
            if any(m in low for m in _BLOCK_MARKERS):
                logger.warning("DDG HTML appears blocked (marker) for query=%r via %s", query, base)
                continue

            matches = list(_DDG_A_RE.finditer(text))
            if not matches:
                continue

            out: List[WebSearchResult] = []
            for m in matches:
                href = _decode_ddg_href(m.group(1))
                title_html = m.group(2) or ""
                title = _html.unescape(re.sub(r"<.*?>", "", title_html)).strip()

                r = _normalize_result(title, "", href)
                if r:
                    out.append(r)
                if len(out) >= num_results:
                    break

            if out:
                return out[:num_results]

        except Exception as exc:  # noqa: BLE001
            logger.warning("DDG HTML fallback failed via %s for query=%r: %s", base, query, exc)
            continue

    return []


def _search_with_ddg_json(query: str, num_results: int, lang: Optional[str] = None) -> List[WebSearchResult]:
    """
    DuckDuckGo Instant Answer API (NOT a real web search API).
    Keep as last resort only.
    """
    url = "https://api.duckduckgo.com/"
    lang_code = _resolve_lang(lang)
    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "t": "aegis-chat",
        "kl": lang_code,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (AegisChat)",
        "Accept": "application/json,text/plain,*/*",
    }

    try:
        resp = http_get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT,
            headers=headers,
            allow_redirects=True,
        )
        resp.raise_for_status()

        if not resp.text or not resp.text.strip():
            logger.warning("DDG JSON fallback returned empty body for query=%r", query)
            return []

        data = resp.json()

    except Exception as exc:  # noqa: BLE001
        snippet = ""
        try:
            snippet = (resp.text[:200] if "resp" in locals() and resp is not None and resp.text else "")
        except Exception:
            pass
        logger.exception("DuckDuckGo JSON fallback failed for %r: %s | body=%r", query, exc, snippet)
        return []

    results: List[WebSearchResult] = []

    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = (data.get("AbstractURL") or "").strip()
    heading = (data.get("Heading") or "").strip()
    r0 = _normalize_result(heading or query, abstract, abstract_url)
    if r0:
        results.append(r0)

    related = data.get("RelatedTopics") or []
    for item in related:
        if len(results) >= num_results:
            break

        if "Topics" in item:
            for st in (item.get("Topics") or []):
                if len(results) >= num_results:
                    break
                text = st.get("Text") or ""
                first_url = st.get("FirstURL") or ""
                r = _normalize_result(text, text, first_url)
                if r:
                    results.append(r)
            continue

        text = item.get("Text") or ""
        first_url = item.get("FirstURL") or ""
        r = _normalize_result(text, text, first_url)
        if r:
            results.append(r)

    return results[:num_results]


def _decode_qwant_href(href: str) -> str:
    try:
        parsed = urlparse(href)
        if "qwant.com" in parsed.netloc and "/redirect" in parsed.path:
            target = parse_qs(parsed.query).get("u")
            if target:
                return unquote(target[0])
    except Exception:
        return href
    return href


def _qwant_lite_url(query: str, num_results: int, lang_code: str) -> str:
    lang = (lang_code or "en-us").split("-", 1)[0]
    return f"https://lite.qwant.com/?q={quote_plus(query)}&l={lang}&count={min(max(num_results, 10), 30)}"


def _search_with_qwant_html(query: str, num_results: int, lang: Optional[str] = None) -> List[WebSearchResult]:
    lang_code = _resolve_lang(lang)
    url = _qwant_lite_url(query, num_results, lang_code)
    headers = {
        "User-Agent": "Mozilla/5.0 (AegisChat-Qwant)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = http_get(url, timeout=HTTP_TIMEOUT, headers=headers, allow_redirects=True)
        if resp.status_code >= 400:
            return []
        soup = BeautifulSoup(resp.text or "", "html.parser")
        anchors = soup.select("a.result-link, a[data-testid='result-title'], div.result a[href]")
        results: List[WebSearchResult] = []
        seen: set[str] = set()
        for a in anchors:
            href = a.get("href")
            if not href:
                continue
            href = _decode_qwant_href(_html.unescape(href.strip()))
            if not href.lower().startswith("http"):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = a.get_text(" ", strip=True)
            snippet_node = None
            parent = a.find_parent("div")
            if parent:
                snippet_node = parent.find(class_="result-desc")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            r = _normalize_result(title, snippet, href)
            if r:
                results.append(r)
            if len(results) >= num_results:
                break
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qwant search failed for %r: %s", query, exc)
        return []


def _search_with_startpage_html(query: str, num_results: int, lang: Optional[str] = None) -> List[WebSearchResult]:
    lang_code = _resolve_lang(lang)
    sp_lang = _startpage_lang(lang_code)
    url = f"https://www.startpage.com/sp/search?q={quote_plus(query)}&segment=startpage.firefox&language={sp_lang}"
    headers = {
        "User-Agent": "Mozilla/5.0 (AegisChat-Startpage)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = http_get(url, timeout=HTTP_TIMEOUT, headers=headers, allow_redirects=True)
        if resp.status_code >= 400:
            return []
        soup = BeautifulSoup(resp.text or "", "html.parser")
        containers = soup.select("div.w-gl__result, div.serp-result")
        results: List[WebSearchResult] = []
        seen: set[str] = set()
        for container in containers:
            link = container.select_one("a.w-gl__result-title, a.result-link, a[data-testid='result-title']")
            if not link:
                continue
            href = link.get("href")
            if not href or not href.lower().startswith("http"):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = link.get_text(" ", strip=True)
            snippet_el = container.select_one("p.w-gl__description, p.result-description")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            r = _normalize_result(title, snippet, href)
            if r:
                results.append(r)
            if len(results) >= num_results:
                break
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("Startpage search failed for %r: %s", query, exc)
        return []


def _search_with_brave_html(query: str, num_results: int, lang: Optional[str] = None) -> List[WebSearchResult]:
    lang_code = _resolve_lang(lang)
    url = f"https://search.brave.com/search?q={quote_plus(query)}&source=web&country=US&ui-lang={lang_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (AegisChat-Brave)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = http_get(url, timeout=HTTP_TIMEOUT, headers=headers, allow_redirects=True)
        if resp.status_code >= 400:
            return []
        soup = BeautifulSoup(resp.text or "", "html.parser")
        anchors = soup.select("a[data-testid='result-title'], a.result-header, div.snippet a[href]")
        results: List[WebSearchResult] = []
        seen: set[str] = set()
        for a in anchors:
            href = a.get("href")
            if not href or not href.lower().startswith("http"):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = a.get_text(" ", strip=True)
            snippet_el = a.find_parent("div")
            snippet = ""
            if snippet_el:
                snippet_candidate = snippet_el.find("p")
                if snippet_candidate:
                    snippet = snippet_candidate.get_text(" ", strip=True)
            r = _normalize_result(title, snippet, href)
            if r:
                results.append(r)
            if len(results) >= num_results:
                break
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("Brave search failed for %r: %s", query, exc)
        return []


def _call_provider(
    provider_name: str,
    cfg: Dict[str, object],
    query: str,
    num_results: int,
    lang: str,
) -> List[WebSearchResult]:
    func: Callable[[str, int, str], List[WebSearchResult]] = cfg["func"]  # type: ignore[assignment]
    limits: Sequence[tuple[int, int]] = cfg["limits"]  # type: ignore[assignment]
    cooldown_seconds: int = cfg["cooldown_seconds"]  # type: ignore[assignment]
    error_cooldown_seconds: int = cfg["error_cooldown_seconds"]  # type: ignore[assignment]

    search_state.guard_provider(provider_name, limits, cooldown_seconds)
    try:
        results = func(query, num_results, lang)
        return results or []
    except Exception as exc:
        logger.exception("Provider %s failed for %r: %s", provider_name, query, exc)
        search_state.record_error(provider_name, [window for window, _ in limits], error_cooldown_seconds)
        raise


def web_search_structured(
    query: str,
    num_results: int = DEFAULT_RESULTS,
    lang: Optional[str] = None,
) -> list[WebSearchResult]:
    """Compatibility helper that returns only results (without meta block)."""
    results, _meta = web_search_structured_with_meta(query, num_results=num_results, lang=lang)
    return results


_warmup_started = False
_warmup_thread: Thread | None = None
_warmup_stop = Event()


def _run_warmup_cycle() -> None:
    for q in WARMUP_QUERIES:
        try:
            web_search_structured(q, num_results=3)
        except Exception:
            logger.debug("Warmup query %r failed", q, exc_info=True)


def _warmup_loop() -> None:
    if WARMUP_ON_START:
        _run_warmup_cycle()
    if WARMUP_INTERVAL_SECONDS <= 0:
        return
    while not _warmup_stop.wait(max(WARMUP_INTERVAL_SECONDS, 5.0)):
        _run_warmup_cycle()


def start_background_warmup() -> None:
    global _warmup_started, _warmup_thread
    if _warmup_started and _warmup_thread is not None and _warmup_thread.is_alive():
        return
    if not WARMUP_ON_START and WARMUP_INTERVAL_SECONDS <= 0:
        return
    _warmup_stop.clear()
    _warmup_started = True
    _warmup_thread = Thread(target=_warmup_loop, name="web-search-warmup", daemon=False)
    _warmup_thread.start()


def stop_background_warmup(timeout_s: float = 2.0) -> bool:
    global _warmup_started, _warmup_thread
    thread = _warmup_thread
    if thread is None:
        _warmup_started = False
        return False
    _warmup_stop.set()
    if thread.is_alive():
        thread.join(max(0.1, float(timeout_s)))
    stopped = not thread.is_alive()
    _warmup_thread = None
    _warmup_started = False
    return stopped


def get_web_search_status(*, probe: bool = False, probe_query: str = "python fastapi", probe_results: int = 1) -> dict:
    """Return provider health/cooldown/cache policy summary for readiness UI."""
    effective_provider_order, ranked_rows = _resolve_provider_plan(probe_query, "en")
    raw_provider_rows = ranked_rows
    provider_rows: list[dict[str, Any]] = []
    unavailable_reasons: list[str] = []
    available_provider_count = 0
    ready_provider_count = 0
    cooling_provider_count = 0

    for row in raw_provider_rows:
        provider_name = str(row.get("provider") or "").strip()
        availability = _provider_availability(provider_name)
        cooling_down = bool(row.get("cooling_down"))
        available = bool(availability.get("available"))
        status = "unavailable"
        if available:
            available_provider_count += 1
            if cooling_down:
                cooling_provider_count += 1
                status = "cooldown"
            else:
                ready_provider_count += 1
                status = "ready"
        else:
            reason = str(availability.get("reason") or "").strip()
            if reason:
                unavailable_reasons.append(f"{provider_name}:{reason}")

        provider_rows.append(
            {
                **row,
                "status": status,
                "available": available,
                "configured": bool(availability.get("configured")),
                "reason": str(availability.get("reason") or ""),
                "transport": str(availability.get("transport") or ""),
            }
        )

    status = "unavailable"
    if provider_rows:
        if ready_provider_count > 0:
            status = "ready"
        elif available_provider_count > 0:
            status = "cooldown"

    payload = {
        "status": status,
        "providers": provider_rows,
        "provider_order": list(PROVIDER_ORDER),
        "effective_provider_order": list(effective_provider_order),
        "provider_count": len(PROVIDER_ORDER),
        "known_provider_count": len(_PROVIDERS),
        "available_provider_count": available_provider_count,
        "ready_provider_count": ready_provider_count,
        "cooling_provider_count": cooling_provider_count,
        "unavailable_provider_count": max(0, len(PROVIDER_ORDER) - available_provider_count),
        "unavailable_reasons": unavailable_reasons,
        "rotation_mode": ROTATION_MODE,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "disk_cache_ttl_seconds": DISK_CACHE_TTL_SECONDS,
        "timeout_seconds": HTTP_TIMEOUT,
        "warmup_enabled": WARMUP_ON_START or WARMUP_INTERVAL_SECONDS > 0,
        "probe_enabled": bool(probe),
        "probe_ok": None,
        "probe_provider": None,
        "probe_results": 0,
    }
    if not probe:
        return payload

    try:
        results, meta = web_search_structured_with_meta(probe_query, num_results=max(1, probe_results), lang="en")
        payload["probe_ok"] = bool(results)
        payload["probe_results"] = len(results or [])
        payload["probe_provider"] = meta.get("provider")
        payload["probe_source"] = meta.get("source")
        payload["probe_status"] = meta.get("status")
        if not results and payload["status"] == "ready":
            payload["status"] = "degraded"
    except Exception as exc:  # noqa: BLE001
        payload["probe_ok"] = False
        payload["probe_error"] = str(exc)
        if payload["status"] == "ready":
            payload["status"] = "degraded"
    return payload
