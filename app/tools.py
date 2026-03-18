from __future__ import annotations

"""
Core tools & utilities used by runtime.

This module intentionally contains only canonical utilities:
- Browser binary discovery used by capability checks / browser smoke.
- SSRF-safe URL fetching utilities used by chat and web snippets.
- Lightweight sanitizers for web/user text.

Canonical web search orchestration lives in `app/services/web_search.py`.
"""

import ipaddress
import logging
import os
import re
import shutil
import socket
import time
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry

try:  # pragma: no cover
    import selenium  # noqa: F401

    SELENIUM_AVAILABLE = True
except Exception:  # noqa: BLE001
    SELENIUM_AVAILABLE = False

try:  # pragma: no cover
    import chromedriver_autoinstaller

    CHROMEDRIVER_AUTOINSTALLER_AVAILABLE = True
except Exception:  # noqa: BLE001
    CHROMEDRIVER_AUTOINSTALLER_AVAILABLE = False

logger = logging.getLogger("app.tools")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
logger.setLevel(os.getenv("TOOLS_LOG_LEVEL", "INFO"))

__all__ = [
    "find_brave_binary",
    "fetch_url",
    "is_onion",
    "fetch_url_via_tor",
    "sanitize_web_context",
    "sanitize_messages",
    "parse_cors_origins",
]

FetchResult = Dict[str, Any]

DEFAULT_USER_AGENT = "Mozilla/5.0 (AegisChat)"
REQUEST_TIMEOUT = int(os.getenv("TOOLS_REQUEST_TIMEOUT", "12"))
TOR_SOCKS_PROXY = os.getenv("TOR_SOCKS_PROXY", "socks5h://127.0.0.1:9050")
FETCH_TIMEOUT = int(os.getenv("TOOLS_FETCH_TIMEOUT", "15"))
MAX_BYTES = int(os.getenv("TOOLS_MAX_BYTES", str(200_000)))
MAX_REDIRECTS = int(os.getenv("TOOLS_MAX_REDIRECTS", "1"))
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_MIME_PREFIXES = ("text/",)
ALLOWED_MIME_EXACT = {"application/json", "application/xml", "application/xhtml+xml"}
BLOCK_LOCAL_NETS = {"127.", "10.", "192.168.", "169.254.", "0.0.0.0"}
BLOCK_LOCAL_NETS |= {
    p.strip()
    for p in (os.getenv("TOOLS_BLOCK_NETS", "") or "").split(",")
    if p.strip()
}
RATE_LIMIT_PER_MINUTE = int(os.getenv("TOOLS_RATE_LIMIT", "120"))


def parse_cors_origins(raw: str | None) -> List[str]:
    """
    Parse comma-separated CORS origins.
    - Empty input -> ["*"]
    - Any wildcard entry collapses to ["*"]
    - Trims spaces and trailing slashes.
    - Keeps insertion order while deduplicating.
    """
    text = (raw or "").strip()
    if not text:
        return ["*"]

    parsed: List[str] = []
    seen: set[str] = set()
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if item == "*":
            return ["*"]
        cleaned = item.rstrip("/")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            parsed.append(cleaned)

    return parsed or ["*"]


def _create_session(
    retries: int = 2,
    backoff_factor: float = 0.3,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    return session


_default_session: requests.Session = _create_session()
_tor_session: requests.Session = _create_session(retries=1, backoff_factor=0.2)
_rate_bucket: Dict[str, List[float]] = {}

def find_brave_binary() -> Optional[str]:
    """
    Locate a Brave/Chromium-compatible binary on the system.
    """
    # Allow explicit override (useful when the default is a Snap wrapper that cannot run in this environment).
    override = (os.getenv("AEGIS_BROWSER_BINARY") or os.getenv("AEGIS_CHROME_BINARY") or os.getenv("CHROME_BIN") or "").strip()
    if override:
        try:
            if os.path.isfile(override) and os.access(override, os.X_OK):
                logger.debug("Using browser binary override: %s", override)
                return override
        except Exception:
            pass

    common_paths: List[str] = [
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        "/snap/bin/brave",
        shutil.which("brave-browser") or "",
        shutil.which("brave") or "",
        shutil.which("google-chrome") or "",
        shutil.which("chromium-browser") or "",
        shutil.which("chromium") or "",
    ]
    for path in common_paths:
        if not path:
            continue
        try:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                logger.debug("Found browser binary at %s", path)
                return path
        except Exception:
            continue
    return None

def _is_blocked_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True

    host = parsed.hostname or ""
    host_l = host.lower()
    if host_l in {"localhost", "127.0.0.1"} or host_l.endswith(".local"):
        return True
    if any(host_l.startswith(prefix) for prefix in BLOCK_LOCAL_NETS):
        return True

    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip_str = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                ):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _check_rate_limit(key: str) -> None:
    """
    Simple in-process sliding window rate limit per key.
    Raises HTTPException when exceeded.
    """
    if RATE_LIMIT_PER_MINUTE <= 0:
        return
    now = time.time()
    window_start = now - 60
    bucket = _rate_bucket.setdefault(key, [])
    bucket[:] = [t for t in bucket if t >= window_start]
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    bucket.append(now)


def fetch_url(
    url: str,
    max_chars: int = 4000,
    max_bytes: int = MAX_BYTES,
    session: Optional[requests.Session] = None,
) -> FetchResult:
    session = session or _default_session
    headers = {"User-Agent": session.headers.get("User-Agent", DEFAULT_USER_AGENT)}

    _check_rate_limit("fetch_url")

    parsed = urlparse(url)
    if (parsed.scheme or "").lower() not in ALLOWED_SCHEMES:
        return {"ok": False, "error": "Only http/https are allowed."}
    if is_onion(url):
        return {"ok": False, "error": "Use Tor fetch for .onion URLs."}
    if _is_blocked_url(url):
        return {"ok": False, "error": "Blocked or invalid URL."}

    try:
        redirects = 0
        current_url = url
        while True:
            with session.get(
                current_url,
                timeout=REQUEST_TIMEOUT,
                headers=headers,
                stream=True,
                allow_redirects=False,
            ) as resp:
                if 300 <= resp.status_code < 400:
                    if redirects >= MAX_REDIRECTS:
                        return {"ok": False, "error": "Redirect limit exceeded."}
                    loc = resp.headers.get("location")
                    if not loc:
                        return {"ok": False, "error": "Redirect without location."}
                    next_url = requests.compat.urljoin(current_url, loc)
                    parsed_next = urlparse(next_url)
                    if (parsed_next.scheme or "").lower() not in ALLOWED_SCHEMES or _is_blocked_url(next_url):
                        return {"ok": False, "error": "Redirected to disallowed target."}
                    current_url = next_url
                    redirects += 1
                    continue

                resp.raise_for_status()

                content_length = resp.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            return {"ok": False, "error": "Content too large."}
                    except Exception:
                        pass

                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if not (ctype.startswith(ALLOWED_MIME_PREFIXES) or ctype in ALLOWED_MIME_EXACT or ctype == ""):
                    return {"ok": False, "error": f"Disallowed content type: {ctype or 'unknown'}"}

                content: List[bytes] = []
                total = 0
                for chunk in resp.iter_content(chunk_size=4096):
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        content.append(chunk[: max_bytes - (total - len(chunk))])
                        break
                    content.append(chunk)

                raw = b"".join(content)
                text = raw.decode(resp.encoding or "utf-8", errors="replace")
                soup = BeautifulSoup(text, "html.parser")
                cleaned = " ".join(soup.get_text(separator="\n").split())
                if len(cleaned) > max_chars:
                    cleaned = cleaned[:max_chars] + " … [truncated]"
                return {
                    "ok": True,
                    "status": resp.status_code,
                    "text": f"Content from {current_url}:\n{cleaned}",
                }
    except Exception as exc:  # noqa: BLE001
        logger.debug("fetch_url failure for %s: %s", url, exc)
        return {"ok": False, "error": str(exc)}


def is_onion(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return host.lower().endswith(".onion")
    except Exception:
        return False


def fetch_url_via_tor(
    url: str,
    tor_proxy: str = TOR_SOCKS_PROXY,
    max_bytes: int = MAX_BYTES,
) -> FetchResult:
    _check_rate_limit("fetch_url_via_tor")

    parsed = urlparse(url)
    if not is_onion(url):
        return {"ok": False, "error": "Tor fetch is only for .onion domains."}
    if (parsed.scheme or "").lower() not in ALLOWED_SCHEMES:
        return {"ok": False, "error": "Only http/https are allowed."}
    if _is_blocked_url(url):
        return {"ok": False, "error": "Blocked or invalid URL."}

    headers = {"User-Agent": DEFAULT_USER_AGENT}
    proxies = {"http": tor_proxy, "https": tor_proxy}

    try:
        with _tor_session.get(
            url,
            headers=headers,
            timeout=FETCH_TIMEOUT,
            stream=True,
            proxies=proxies,
            allow_redirects=False,
        ) as r:
            r.raise_for_status()

            ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if not (ctype.startswith(ALLOWED_MIME_PREFIXES) or ctype in ALLOWED_MIME_EXACT or ctype == ""):
                return {"ok": False, "error": f"Disallowed content type: {ctype or 'unknown'}"}

            data: List[bytes] = []
            total = 0
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    data.append(chunk[: max_bytes - (total - len(chunk))])
                    break
                data.append(chunk)

            text = b"".join(data).decode(errors="replace")
            text = re.sub(r"(?is)<script.*?>.*?</script>", "", text)
            text = re.sub(r"(?is)<iframe.*?>.*?</iframe>", "", text)
            return {"ok": True, "status": r.status_code, "text": text}
    except RequestException as exc:  # noqa: BLE001
        logger.debug("fetch_url_via_tor request exception: %s", exc)
        return {
            "ok": False,
            "status": getattr(exc.response, "status_code", None),
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("fetch_url_via_tor generic exception: %s", exc)
        return {"ok": False, "error": str(exc)}


def sanitize_web_context(text: str, max_chars: int = 1200) -> str:
    if not text:
        return ""

    current_year = datetime.now(UTC).year
    years = re.findall(r"\b(19\d{2}|20\d{2}|21\d{2})\b", text)
    flagged: List[int] = []
    for y in years:
        try:
            yi = int(y)
            if yi < current_year - 1:
                flagged.append(yi)
        except Exception:
            continue

    clean = text[:max_chars]

    if flagged:
        clean = (
            "⚠️ Advertencia: La(s) fuente(s) web contienen años potencialmente "
            f"desactualizados {sorted(set(flagged))}. No asumir que son actuales.\n\n"
        ) + clean

    clean = re.sub(r"(?is)<script.*?>.*?</script>", "", clean)
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean


def sanitize_messages(
    messages: List[Dict[str, Any]],
    max_total_chars: int = 8000,
) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    total = 0

    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if not content:
            continue

        remaining = max_total_chars - total
        if remaining <= 0:
            break

        if len(content) > remaining:
            content = content[:remaining] + " … [truncated]"

        sanitized.append({"role": role, "content": content})
        total += len(content)

    return sanitized
