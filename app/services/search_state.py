from __future__ import annotations

"""
Web-search runtime state store (sqlite-backed).

Why this module exists:
- Track provider quotas/cooldowns deterministically.
- Persist web/url/robots caches across process restarts.
"""

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Sequence


class ProviderLimitError(RuntimeError):
    """Raised when a provider hit its quota window."""


class ProviderCooldownError(RuntimeError):
    """Raised when a provider is cooling down (e.g. after repeated failures)."""


class ProxyUnavailableError(RuntimeError):
    """Raised when no proxy is currently available."""


DATA_DIR = Path(os.getenv("AEGIS_DATA_DIR", "data")).resolve()
STATE_DB = DATA_DIR / "system_state.db"
_lock = threading.RLock()


def _ensure_db() -> None:
    """Initialize sqlite schema for provider usage/cache/proxy tables."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATE_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_usage (
                provider TEXT NOT NULL,
                window_seconds INTEGER NOT NULL,
                window_start REAL NOT NULL,
                call_count INTEGER NOT NULL,
                error_count INTEGER NOT NULL,
                cooldown_until REAL NOT NULL,
                PRIMARY KEY (provider, window_seconds)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_cache (
                query_hash TEXT PRIMARY KEY,
                provider TEXT,
                fetched_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS url_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                fetched_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS robots_cache (
                domain TEXT PRIMARY KEY,
                fetched_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                blob TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proxy_pool (
                name TEXT PRIMARY KEY,
                proxy_url TEXT NOT NULL,
                cooldown_until REAL NOT NULL,
                fail_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL
            )
            """
        )
        conn.commit()


_ensure_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(STATE_DB)


def _now() -> float:
    return time.time()


def guard_provider(provider: str, limits: Sequence[tuple[int, int]], cooldown_seconds: int) -> None:
    """
    Ensure the provider still has quota in every window defined by `limits`.
    Each limit tuple is (window_seconds, max_calls).
    """
    now = _now()
    with _lock, _conn() as conn:
        for window_seconds, max_calls in limits:
            row = conn.execute(
                """
                SELECT window_start, call_count, cooldown_until
                FROM provider_usage
                WHERE provider=? AND window_seconds=?
                """,
                (provider, window_seconds),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO provider_usage(provider, window_seconds, window_start, call_count, error_count, cooldown_until)
                    VALUES (?, ?, ?, 0, 0, 0)
                    """,
                    (provider, window_seconds, now),
                )
                row = (now, 0, 0.0)

            window_start, call_count, cooldown_until = row

            if cooldown_until and cooldown_until > now:
                raise ProviderCooldownError(f"{provider} cooling down for {int(cooldown_until - now)}s")

            if now - window_start >= window_seconds:
                conn.execute(
                    """
                    UPDATE provider_usage
                    SET window_start=?, call_count=0, error_count=0
                    WHERE provider=? AND window_seconds=?
                    """,
                    (now, provider, window_seconds),
                )
                call_count = 0

            if call_count >= max_calls:
                cooldown_until = now + cooldown_seconds
                conn.execute(
                    """
                    UPDATE provider_usage
                    SET cooldown_until=?
                    WHERE provider=? AND window_seconds=?
                    """,
                    (cooldown_until, provider, window_seconds),
                )
                raise ProviderLimitError(f"{provider} limit hit ({max_calls} calls/{window_seconds}s)")

        for window_seconds, _ in limits:
            conn.execute(
                """
                UPDATE provider_usage
                SET call_count=call_count+1
                WHERE provider=? AND window_seconds=?
                """,
                (provider, window_seconds),
            )
        conn.commit()


def record_error(provider: str, window_seconds_list: Iterable[int], cooldown_seconds: int) -> None:
    """
    Increment error counters. If the provider errored too many times inside a short window,
    force a short cooldown to avoid hammering the source.
    """
    now = _now()
    with _lock, _conn() as conn:
        for window_seconds in window_seconds_list:
            row = conn.execute(
                """
                SELECT window_start, error_count
                FROM provider_usage
                WHERE provider=? AND window_seconds=?
                """,
                (provider, window_seconds),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO provider_usage(provider, window_seconds, window_start, call_count, error_count, cooldown_until)
                    VALUES (?, ?, ?, 0, 1, 0)
                    """,
                    (provider, window_seconds, now),
                )
                continue

            window_start, error_count = row
            if now - window_start >= window_seconds:
                conn.execute(
                    """
                    UPDATE provider_usage
                    SET window_start=?, error_count=1
                    WHERE provider=? AND window_seconds=?
                    """,
                    (now, provider, window_seconds),
                )
                continue

            error_count += 1
            conn.execute(
                """
                UPDATE provider_usage
                SET error_count=?
                WHERE provider=? AND window_seconds=?
                """,
                (error_count, provider, window_seconds),
            )
            if error_count >= 3:
                cooldown_until = now + cooldown_seconds
                conn.execute(
                    """
                    UPDATE provider_usage
                    SET cooldown_until=?
                    WHERE provider=? AND window_seconds=?
                    """,
                    (cooldown_until, provider, window_seconds),
                )
        conn.commit()


def cache_key(query: str, num_results: int, lang: str | None = None) -> str:
    lang_part = (lang or "").strip().lower()
    canon = f"{num_results}:{lang_part}:{query.strip()}".encode("utf-8")
    return hashlib.sha1(canon).hexdigest()


def get_cached_results(query: str, num_results: int, lang: str | None = None) -> list[dict] | None:
    """Fetch fresh cached search results by query key (or None)."""
    key = cache_key(query, num_results, lang=lang)
    now = _now()
    with _lock, _conn() as conn:
        row = conn.execute(
            """
            SELECT payload, expires_at FROM web_cache WHERE query_hash=?
            """,
            (key,),
        ).fetchone()
    if not row:
        return None
    payload, expires_at = row
    if expires_at < now:
        delete_cache_entry(key)
        return None
    try:
        return json.loads(payload)
    except Exception:
        delete_cache_entry(key)
        return None


def get_cached_results_meta(query: str, num_results: int, lang: str | None = None, *, allow_stale: bool = False) -> dict | None:
    key = cache_key(query, num_results, lang=lang)
    now = _now()
    with _lock, _conn() as conn:
        row = conn.execute(
            """
            SELECT provider, fetched_at, expires_at
            FROM web_cache WHERE query_hash=?
            """,
            (key,),
        ).fetchone()
    if not row:
        return None
    provider, fetched_at, expires_at = row
    stale = bool(expires_at and float(expires_at) < now)
    if stale and not allow_stale:
        return None
    return {
        "provider": str(provider or ""),
        "fetched_at": float(fetched_at or 0.0),
        "expires_at": float(expires_at or 0.0),
        "stale": stale,
    }


def set_cached_results(
    query: str,
    num_results: int,
    provider: str,
    results: Sequence[dict],
    ttl_seconds: float,
    lang: str | None = None,
) -> None:
    """Persist search results payload with explicit TTL expiry."""
    key = cache_key(query, num_results, lang=lang)
    now = _now()
    payload = json.dumps(results)
    expires_at = now + ttl_seconds
    with _lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO web_cache(query_hash, provider, fetched_at, expires_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE
            SET provider=excluded.provider,
                fetched_at=excluded.fetched_at,
                expires_at=excluded.expires_at,
                payload=excluded.payload
            """,
            (key, provider, now, expires_at, payload),
        )
        conn.commit()


def delete_cache_entry(key: str) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM web_cache WHERE query_hash=?", (key,))
        conn.commit()


def _url_hash(url: str) -> str:
    canon = (url or "").strip()
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


def get_url_cache(url: str) -> dict | None:
    key = _url_hash(url)
    now = _now()
    with _lock, _conn() as conn:
        row = conn.execute(
            """
            SELECT payload, expires_at FROM url_cache WHERE url_hash=?
            """,
            (key,),
        ).fetchone()
    if not row:
        return None
    payload, expires_at = row
    if expires_at < now:
        delete_url_cache_entry(key)
        return None
    try:
        return json.loads(payload)
    except Exception:
        delete_url_cache_entry(key)
        return None


def set_url_cache(url: str, payload: dict, ttl_seconds: float) -> None:
    key = _url_hash(url)
    now = _now()
    expires_at = now + ttl_seconds
    with _lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO url_cache(url_hash, url, fetched_at, expires_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url_hash) DO UPDATE
            SET url=excluded.url,
                fetched_at=excluded.fetched_at,
                expires_at=excluded.expires_at,
                payload=excluded.payload
            """,
            (key, url, now, expires_at, json.dumps(payload)),
        )
        conn.commit()


def delete_url_cache_entry(key: str) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM url_cache WHERE url_hash=?", (key,))
        conn.commit()


def get_cached_robots(domain: str) -> str | None:
    dom = (domain or "").lower().strip()
    if not dom:
        return None
    now = _now()
    with _lock, _conn() as conn:
        row = conn.execute(
            """
            SELECT blob, expires_at FROM robots_cache WHERE domain=?
            """,
            (dom,),
        ).fetchone()
    if not row:
        return None
    blob, expires_at = row
    if expires_at < now:
        delete_robots_cache(dom)
        return None
    return blob


def set_cached_robots(domain: str, blob: str, ttl_seconds: float) -> None:
    dom = (domain or "").lower().strip()
    if not dom:
        return
    now = _now()
    expires_at = now + ttl_seconds
    with _lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO robots_cache(domain, fetched_at, expires_at, blob)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE
            SET fetched_at=excluded.fetched_at,
                expires_at=excluded.expires_at,
                blob=excluded.blob
            """,
            (dom, now, expires_at, blob),
        )
        conn.commit()


def delete_robots_cache(domain: str) -> None:
    dom = (domain or "").lower().strip()
    if not dom:
        return
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM robots_cache WHERE domain=?", (dom,))
        conn.commit()


def get_stale_cached_results(query: str, num_results: int, lang: str | None = None) -> list[dict] | None:
    """Return cached payload even if expired (used for fallback)."""
    key = cache_key(query, num_results, lang=lang)
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT payload FROM web_cache WHERE query_hash=?",
            (key,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        delete_cache_entry(key)
        return None


# -------------------------
# Proxy pool helpers
# -------------------------


def register_proxy(name: str, proxy_url: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO proxy_pool(name, proxy_url, cooldown_until, fail_count, success_count)
            VALUES (?, ?, 0, 0, 0)
            ON CONFLICT(name) DO UPDATE
            SET proxy_url=excluded.proxy_url
            """,
            (name, proxy_url),
        )
        conn.commit()


def list_proxies() -> list[dict]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            """
            SELECT name, proxy_url, cooldown_until, fail_count, success_count
            FROM proxy_pool
            """
        ).fetchall()
    return [
        {
            "name": row[0],
            "proxy_url": row[1],
            "cooldown_until": row[2],
            "fail_count": row[3],
            "success_count": row[4],
        }
        for row in rows
    ]


def mark_proxy_success(name: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """
            UPDATE proxy_pool
            SET fail_count=0, success_count=success_count+1, cooldown_until=0
            WHERE name=?
            """,
            (name,),
        )
        conn.commit()


def mark_proxy_failure(name: str, cooldown_seconds: float) -> None:
    cooldown_until = _now() + cooldown_seconds
    with _lock, _conn() as conn:
        conn.execute(
            """
            UPDATE proxy_pool
            SET fail_count=fail_count+1, cooldown_until=?
            WHERE name=?
            """,
            (cooldown_until, name),
        )
        conn.commit()


def provider_snapshot(providers: Sequence[str]) -> list[dict]:
    items = [str(provider).strip() for provider in providers if str(provider).strip()]
    if not items:
        return []
    placeholders = ",".join("?" for _ in items)
    now = _now()
    grouped: dict[str, list[dict]] = {name: [] for name in items}
    with _lock, _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT provider, window_seconds, window_start, call_count, error_count, cooldown_until
            FROM provider_usage
            WHERE provider IN ({placeholders})
            ORDER BY provider ASC, window_seconds ASC
            """,
            tuple(items),
        ).fetchall()
    for provider, window_seconds, window_start, call_count, error_count, cooldown_until in rows:
        grouped.setdefault(provider, []).append(
            {
                "window_seconds": int(window_seconds or 0),
                "window_start": float(window_start or 0.0),
                "call_count": int(call_count or 0),
                "error_count": int(error_count or 0),
                "cooldown_until": float(cooldown_until or 0.0),
                "cooling_down": bool(cooldown_until and float(cooldown_until) > now),
            }
        )

    snapshot: list[dict] = []
    for provider in items:
        windows = grouped.get(provider) or []
        cooldown_until = max((float(item.get("cooldown_until") or 0.0) for item in windows), default=0.0)
        snapshot.append(
            {
                "provider": provider,
                "status": "cooldown" if cooldown_until > now else "ready",
                "cooldown_until": cooldown_until,
                "cooling_down": cooldown_until > now,
                "windows": windows,
            }
        )
    return snapshot
