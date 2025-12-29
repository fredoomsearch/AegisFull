from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from app.services import search_state
from app.services.search_state import (
    ProviderCooldownError,
    ProviderLimitError,
    ProxyUnavailableError,
)
from app.tools import fetch_url, sanitize_web_context

try:
    from app.services import proxy_pool
except Exception:  # pragma: no cover
    proxy_pool = None

logger = logging.getLogger(__name__)

MAX_PAGES = int(os.getenv("AEGIS_WEB_SNIPPETS_MAX_PAGES", "2"))
SNIPPET_MAX_CHARS = int(os.getenv("AEGIS_WEB_SNIPPETS_MAX_CHARS", "1600"))
SNIPPET_CACHE_TTL = float(os.getenv("AEGIS_WEB_SNIPPETS_CACHE_TTL", "600"))
DOMAIN_WINDOW_SECONDS = int(os.getenv("AEGIS_WEB_SNIPPETS_DOMAIN_WINDOW", "60"))
DOMAIN_MAX_CALLS = int(os.getenv("AEGIS_WEB_SNIPPETS_DOMAIN_MAX_CALLS", "1"))
DOMAIN_COOLDOWN_SECONDS = int(os.getenv("AEGIS_WEB_SNIPPETS_DOMAIN_COOLDOWN", "60"))
GLOBAL_WINDOW_SECONDS = int(os.getenv("AEGIS_WEB_SNIPPETS_GLOBAL_WINDOW", "60"))
GLOBAL_MAX_CALLS = int(os.getenv("AEGIS_WEB_SNIPPETS_GLOBAL_MAX_CALLS", "8"))
GLOBAL_COOLDOWN_SECONDS = int(os.getenv("AEGIS_WEB_SNIPPETS_GLOBAL_COOLDOWN", "30"))
ROBOTS_TTL_SECONDS = float(os.getenv("AEGIS_WEB_ROBOTS_TTL", "21600"))
USER_AGENT = os.getenv("AEGIS_WEB_SNIPPETS_UA", "AEGISBot/1.0 (+https://example.com)")


class SnippetResult(Dict[str, str]):
    """Typed alias for snippet payload."""


def _is_https(url: str) -> bool:
    try:
        return urlparse(url).scheme.lower() == "https"
    except Exception:
        return False


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _proxies_enabled() -> bool:
    return bool(getattr(proxy_pool, "proxies_configured", lambda: False)())


def _http_get(url: str, **kwargs) -> requests.Response:
    if proxy_pool and _proxies_enabled():
        try:
            with proxy_pool.proxy_session() as (session, _):
                return session.get(url, **kwargs)
        except ProxyUnavailableError:
            logger.debug("Proxy unavailable for %s; falling back to direct request.", url)
    return requests.get(url, **kwargs)


@contextmanager
def _maybe_proxy_session():
    if proxy_pool and _proxies_enabled():
        try:
            with proxy_pool.proxy_session() as (session, _):
                yield session
                return
        except ProxyUnavailableError:
            logger.debug("Proxy unavailable for snippet fetch; using direct session.")
    yield None


def _load_robots(domain: str) -> RobotFileParser | None:
    domain = (domain or "").lower()
    if not domain:
        return None

    cached = search_state.get_cached_robots(domain)
    parser = RobotFileParser()
    if cached is not None:
        parser.parse((cached or "").splitlines())
        parser.modified()
        return parser

    robots_url = f"https://{domain}/robots.txt"
    try:
        resp = _http_get(
            robots_url,
            timeout=4,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code < 400 and resp.text:
            text = resp.text
            search_state.set_cached_robots(domain, text, ROBOTS_TTL_SECONDS)
            parser.parse(text.splitlines())
            parser.modified()
            return parser
        search_state.set_cached_robots(domain, "", ROBOTS_TTL_SECONDS)
        return None
    except Exception:
        search_state.set_cached_robots(domain, "", ROBOTS_TTL_SECONDS)
        return None


def _robots_allows(url: str) -> bool:
    domain = _domain_from_url(url)
    parser = _load_robots(domain)
    if parser is None:
        return True
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _shorten(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    return text[: SNIPPET_MAX_CHARS - 3] + "..."


def _guard_domain(domain: str) -> None:
    provider = f"fetch-domain:{domain.lower()}"
    limits = [(DOMAIN_WINDOW_SECONDS, DOMAIN_MAX_CALLS)]
    search_state.guard_provider(provider, limits, DOMAIN_COOLDOWN_SECONDS)


def _guard_global() -> None:
    provider = "fetch-global"
    limits = [(GLOBAL_WINDOW_SECONDS, GLOBAL_MAX_CALLS)]
    search_state.guard_provider(provider, limits, GLOBAL_COOLDOWN_SECONDS)


def fetch_snippets_from_sources(
    sources: Sequence[Dict[str, str]],
    max_pages: int = MAX_PAGES,
) -> Tuple[List[SnippetResult], List[str]]:
    snippets: List[SnippetResult] = []
    errors: List[str] = []
    if not sources or max_pages <= 0:
        return snippets, errors

    for src in sources:
        if len(snippets) >= max_pages:
            break
        url = (src.get("url") or src.get("link") or "").strip()
        if not url or not _is_https(url):
            continue

        domain = _domain_from_url(url)
        if not domain:
            continue
        if not _robots_allows(url):
            logger.info("robots disallow %s", url)
            continue

        cached = search_state.get_url_cache(url)
        if cached:
            snippet_text = cached.get("snippet") or ""
            if snippet_text:
                snippets.append(
                    {
                        "title": src.get("title") or "",
                        "url": url,
                        "snippet": snippet_text,
                    }
                )
                continue

        try:
            _guard_domain(domain)
            _guard_global()
        except (ProviderCooldownError, ProviderLimitError) as exc:
            logger.debug("Skipping %s due to throttle: %s", url, exc)
            errors.append(f"{url}: throttled ({exc})")
            continue

        try:
            with _maybe_proxy_session() as session:
                result = fetch_url(url, max_chars=SNIPPET_MAX_CHARS, session=session)
        except Exception as exc:  # noqa: BLE001
            logger.exception("fetch_url failed for %s: %s", url, exc)
            errors.append(f"{url}: fetch failed")
            continue

        if not isinstance(result, dict) or not result.get("ok"):
            errors.append(f"{url}: fetch error")
            continue

        text = result.get("text") or ""
        text = sanitize_web_context(text, SNIPPET_MAX_CHARS)
        text = _shorten(text)
        if not text:
            errors.append(f"{url}: empty snippet")
            continue

        snippets.append({"title": src.get("title") or "", "url": url, "snippet": text})
        search_state.set_url_cache(url, {"snippet": text}, SNIPPET_CACHE_TTL)

    return snippets, errors
