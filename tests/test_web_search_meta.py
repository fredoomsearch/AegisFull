from __future__ import annotations

import uuid

from app.core.types import WebSearchResult
from app.services import search_state, web_search


def _fake_provider_cfg() -> dict:
    return {
        "func": None,
        "limits": [],
        "cooldown_seconds": 0,
        "error_cooldown_seconds": 0,
    }


def test_web_search_meta_reports_live_then_cache(monkeypatch):
    query = f"meta-live-{uuid.uuid4().hex}"
    lang = web_search._resolve_lang("en")
    key = (query, 1, lang)

    monkeypatch.setattr(web_search, "CACHE_TTL_SECONDS", 60.0)
    monkeypatch.setattr(web_search, "DISK_CACHE_TTL_SECONDS", 60.0)
    monkeypatch.setattr(web_search, "PROVIDER_ORDER", ["fake"])
    monkeypatch.setattr(web_search, "_PROVIDERS", {"fake": _fake_provider_cfg()})

    calls = {"count": 0}

    def fake_call(provider_name, cfg, cleaned, n, lang_code):
        calls["count"] += 1
        return [WebSearchResult(title="JWT", snippet="auth", link="https://example.com/jwt")]

    monkeypatch.setattr(web_search, "_call_provider", fake_call)

    with web_search._cache_lock:
        web_search._cache.pop(key, None)

    results1, meta1 = web_search.web_search_structured_with_meta(query, num_results=1, lang="en")
    results2, meta2 = web_search.web_search_structured_with_meta(query, num_results=1, lang="en")

    assert len(results1) == 1
    assert meta1["source"] == "live"
    assert meta1["provider"] == "fake"
    assert meta1["live_web_used"] is True

    assert len(results2) == 1
    assert meta2["source"] == "cache"
    assert meta2["cache_used"] is True
    assert calls["count"] == 1

    with web_search._cache_lock:
        web_search._cache.pop(key, None)
    search_state.delete_cache_entry(search_state.cache_key(query, 1, lang=lang))


def test_web_search_meta_uses_stale_cache_when_live_fails(monkeypatch):
    query = f"meta-stale-{uuid.uuid4().hex}"
    lang = web_search._resolve_lang("en")
    key = (query, 1, lang)
    payload = [{"title": "Old JWT", "snippet": "cached", "link": "https://example.com/cached"}]

    monkeypatch.setattr(web_search, "CACHE_TTL_SECONDS", 60.0)
    monkeypatch.setattr(web_search, "DISK_CACHE_TTL_SECONDS", 60.0)
    monkeypatch.setattr(web_search, "PROVIDER_ORDER", ["fake"])
    monkeypatch.setattr(web_search, "_PROVIDERS", {"fake": _fake_provider_cfg()})
    monkeypatch.setattr(web_search, "_call_provider", lambda *args, **kwargs: [])

    with web_search._cache_lock:
        web_search._cache.pop(key, None)

    search_state.set_cached_results(query, 1, "fake", payload, ttl_seconds=-1, lang=lang)
    results, meta = web_search.web_search_structured_with_meta(query, num_results=1, lang="en")

    assert len(results) == 1
    assert results[0].title == "Old JWT"
    assert meta["source"] == "stale-cache"
    assert meta["stale_cache_used"] is True

    with web_search._cache_lock:
        web_search._cache.pop(key, None)
    search_state.delete_cache_entry(search_state.cache_key(query, 1, lang=lang))


def test_get_web_search_status_reports_partial_provider_availability(monkeypatch):
    monkeypatch.setattr(web_search, "PROVIDER_ORDER", ["ddgs", "startpage_html"])
    monkeypatch.setattr(
        search_state,
        "provider_snapshot",
        lambda providers: [
            {"provider": "ddgs", "status": "ready", "cooldown_until": 0.0, "cooling_down": False, "windows": []},
            {"provider": "startpage_html", "status": "ready", "cooldown_until": 0.0, "cooling_down": False, "windows": []},
        ],
    )
    monkeypatch.setattr(web_search, "_HAS_DDGS", False)
    monkeypatch.setattr(
        web_search,
        "_PROVIDERS",
        {"ddgs": _fake_provider_cfg(), "startpage_html": _fake_provider_cfg()},
    )

    status = web_search.get_web_search_status()

    assert status["status"] == "ready"
    assert status["provider_count"] == 2
    assert status["available_provider_count"] == 1
    assert status["ready_provider_count"] == 1
    assert status["unavailable_provider_count"] == 1
    ddgs = next(item for item in status["providers"] if item["provider"] == "ddgs")
    assert ddgs["status"] == "unavailable"
    assert ddgs["reason"] == "duckduckgo_search_not_installed"


def test_get_web_search_status_reports_cooldown_when_all_available_providers_are_cooling(monkeypatch):
    monkeypatch.setattr(web_search, "PROVIDER_ORDER", ["startpage_html"])
    monkeypatch.setattr(
        search_state,
        "provider_snapshot",
        lambda providers: [
            {"provider": "startpage_html", "status": "cooldown", "cooldown_until": 9999999999.0, "cooling_down": True, "windows": []},
        ],
    )
    monkeypatch.setattr(web_search, "_PROVIDERS", {"startpage_html": _fake_provider_cfg()})

    status = web_search.get_web_search_status()

    assert status["status"] == "cooldown"
    assert status["provider_count"] == 1
    assert status["available_provider_count"] == 1
    assert status["ready_provider_count"] == 0
    assert status["cooling_provider_count"] == 1


def test_web_search_meta_auto_rotation_prefers_healthier_ready_provider(monkeypatch):
    query = f"meta-rotate-{uuid.uuid4().hex}"

    monkeypatch.setattr(web_search, "CACHE_TTL_SECONDS", 60.0)
    monkeypatch.setattr(web_search, "DISK_CACHE_TTL_SECONDS", 60.0)
    monkeypatch.setattr(web_search, "ROTATION_MODE", "auto")
    monkeypatch.setattr(web_search, "QUERY_SHARD_ROTATION", False)
    monkeypatch.setattr(web_search, "PROVIDER_ORDER", ["ddgs", "brave_html", "startpage_html"])
    monkeypatch.setattr(
        search_state,
        "provider_snapshot",
        lambda providers: [
            {
                "provider": "ddgs",
                "status": "ready",
                "cooldown_until": 0.0,
                "cooling_down": False,
                "windows": [],
            },
            {
                "provider": "brave_html",
                "status": "ready",
                "cooldown_until": 0.0,
                "cooling_down": False,
                "windows": [{"window_seconds": 60, "call_count": 9, "error_count": 2, "cooldown_until": 0.0, "cooling_down": False}],
            },
            {
                "provider": "startpage_html",
                "status": "ready",
                "cooldown_until": 0.0,
                "cooling_down": False,
                "windows": [{"window_seconds": 60, "call_count": 1, "error_count": 0, "cooldown_until": 0.0, "cooling_down": False}],
            },
        ],
    )
    monkeypatch.setattr(web_search, "_HAS_DDGS", False)
    monkeypatch.setattr(
        web_search,
        "_PROVIDERS",
        {
            "ddgs": _fake_provider_cfg(),
            "brave_html": _fake_provider_cfg(),
            "startpage_html": _fake_provider_cfg(),
        },
    )

    seen: list[str] = []

    def fake_call(provider_name, cfg, cleaned, n, lang_code):
        seen.append(provider_name)
        return [WebSearchResult(title="Result", snippet="ok", link=f"https://example.com/{provider_name}")]

    monkeypatch.setattr(web_search, "_call_provider", fake_call)

    results, meta = web_search.web_search_structured_with_meta(query, num_results=1, lang="en")

    assert len(results) == 1
    assert meta["provider"] == "startpage_html"
    assert meta["providers_tried"] == ["startpage_html"]
    assert meta["providers_skipped"] == ["ddgs:duckduckgo_search_not_installed"]
    assert meta["effective_provider_order"][0] == "startpage_html"
    assert seen == ["startpage_html"]

    lang = web_search._resolve_lang("en")
    with web_search._cache_lock:
        web_search._cache.pop((query, 1, lang), None)
    search_state.delete_cache_entry(search_state.cache_key(query, 1, lang=lang))


def test_get_web_search_status_exposes_effective_provider_order(monkeypatch):
    monkeypatch.setattr(web_search, "ROTATION_MODE", "auto")
    monkeypatch.setattr(web_search, "QUERY_SHARD_ROTATION", False)
    monkeypatch.setattr(web_search, "PROVIDER_ORDER", ["ddgs", "brave_html", "startpage_html"])
    monkeypatch.setattr(
        search_state,
        "provider_snapshot",
        lambda providers: [
            {
                "provider": "ddgs",
                "status": "ready",
                "cooldown_until": 0.0,
                "cooling_down": False,
                "windows": [],
            },
            {
                "provider": "brave_html",
                "status": "ready",
                "cooldown_until": 0.0,
                "cooling_down": False,
                "windows": [{"window_seconds": 60, "call_count": 6, "error_count": 1, "cooldown_until": 0.0, "cooling_down": False}],
            },
            {
                "provider": "startpage_html",
                "status": "ready",
                "cooldown_until": 0.0,
                "cooling_down": False,
                "windows": [{"window_seconds": 60, "call_count": 1, "error_count": 0, "cooldown_until": 0.0, "cooling_down": False}],
            },
        ],
    )
    monkeypatch.setattr(web_search, "_HAS_DDGS", False)
    monkeypatch.setattr(
        web_search,
        "_PROVIDERS",
        {
            "ddgs": _fake_provider_cfg(),
            "brave_html": _fake_provider_cfg(),
            "startpage_html": _fake_provider_cfg(),
        },
    )

    status = web_search.get_web_search_status()

    assert status["rotation_mode"] == "auto"
    assert status["known_provider_count"] == 3
    assert status["effective_provider_order"][0] == "startpage_html"
    assert status["effective_provider_order"][-1] == "ddgs"
