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
