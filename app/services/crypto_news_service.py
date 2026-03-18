from __future__ import annotations

"""
Lightweight crypto news fetcher with sentiment/impact tagging.

- Primary provider: CryptoPanic (if CRYPTOPANIC_TOKEN is set), else GDELT.
- Results are cached briefly to avoid hammering upstream.

Why this module exists:
- Enrich crypto routes with lightweight news/sentiment context.
"""

import os
import time
from datetime import datetime
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import requests

NEWS_TTL = int(os.getenv("CRYPTO_NEWS_TTL", "90"))  # seconds
NEWS_TIMEOUT = float(os.getenv("CRYPTO_NEWS_TIMEOUT", "5"))
NEWS_MAX = int(os.getenv("CRYPTO_NEWS_MAX", "8"))
ALLOWED_DOMAINS = {
    d.strip().lower()
    for d in (
        os.getenv(
            "CRYPTO_NEWS_ALLOWED",
            "binance.com,cointelegraph.com,coindesk.com,newsbtc.com,decrypt.co,ambcrypto.com",
        )
        or ""
    ).split(",")
    if d.strip()
}
CRYPTOPANIC_TOKEN = os.getenv("CRYPTOPANIC_TOKEN")
NEWSAPI_TOKEN = os.getenv("NEWSAPI_TOKEN")
RSS_FEEDS = [
    u.strip()
    for u in (os.getenv("CRYPTO_NEWS_RSS", "") or "").split(",")
    if u.strip()
]

_cache: Dict[str, Tuple[float, Dict]] = {}

_POS = {"surge", "rally", "bull", "upgrade", "partnership", "approval", "etf", "launch"}
_NEG = {"hack", "ban", "halt", "selloff", "bear", "downgrade", "exploit", "lawsuit"}
_IMPACT_MAP = {
    "regulation": {"sec", "regulation", "ban", "approval", "etf"},
    "hack": {"hack", "exploit", "breach"},
    "listing": {"listing", "launch", "ipo"},
    "outage": {"outage", "halt", "downtime"},
    "macro": {"inflation", "fomc", "fed", "rates"},
}

_TRUSTED_DOMAINS = {"coindesk.com", "cointelegraph.com", "decrypt.co", "bloomberg.com", "reuters.com"}
_LOW_TRUST_DOMAINS = {"newsbtc.com", "ambcrypto.com"}
_MIN_TS = 946684800  # 2000-01-01 to drop junk timestamps (1970/no-date)


def _sentiment(text: str) -> float:
    if not text:
        return 0.0
    t = text.lower()
    score = sum(1 for k in _POS if k in t) - sum(1 for k in _NEG if k in t)
    return max(-3, min(3, score)) / 3.0


def _impact_tags(text: str) -> List[str]:
    tags: List[str] = []
    if not text:
        return tags
    t = text.lower()
    for tag, kws in _IMPACT_MAP.items():
        if any(k in t for k in kws):
            tags.append(tag)
    return tags


def _is_clickbaity(title: str) -> bool:
    if not title:
        return False
    exclam = title.count("!")
    caps_ratio = sum(c.isupper() for c in title) / max(len(title), 1)
    return exclam >= 2 or caps_ratio > 0.35


def _trust_score(title: str, url_item: str, source: str, ts_epoch: int) -> float:
    score = 0.5
    try:
        host = (urlparse(url_item).hostname or "").lower()
    except Exception:
        host = (source or "").lower()

    if host:
        if any(host.endswith(d) for d in _TRUSTED_DOMAINS):
            score += 0.25
        if any(host.endswith(d) for d in _LOW_TRUST_DOMAINS):
            score -= 0.15
        if url_item.startswith("https://"):
            score += 0.05

    try:
        age_hours = max(0.0, (time.time() - int(ts_epoch)) / 3600.0)
        if age_hours < 6:
            score += 0.1
        elif age_hours < 24:
            score += 0.05
        elif age_hours > 72:
            score -= 0.05
    except Exception:
        pass

    if _is_clickbaity(title):
        score -= 0.15

    sent = _sentiment(title)
    if abs(sent) > 0.7:
        score -= 0.05

    return max(0.0, min(1.0, score))


def _allowed_url(url_item: str) -> bool:
    u = (url_item or "").strip()
    if not (u.startswith("https://") or u.startswith("http://")):
        return False
    try:
        host = urlparse(u).hostname or ""
    except Exception:
        host = ""
    if ALLOWED_DOMAINS:
        return any(host.endswith(dom) for dom in ALLOWED_DOMAINS)
    return True


def _dedupe(items: List[Dict]) -> List[Dict]:
    seen = set()
    out: List[Dict] = []
    for it in items:
        key = (it.get("url") or it.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _parse_iso_to_epoch(value: str) -> int:
    if not value:
        return int(time.time())
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return int(time.time())


def _normalize_item(title: str, url_item: str, source: str, ts_epoch: int, excerpt: str = "") -> Dict:
    sent = _sentiment(f"{title} {excerpt}")
    tags = _impact_tags(title)
    trust = _trust_score(title, url_item, source, ts_epoch)
    return {
        "title": title[:240],
        "source": source[:80],
        "url": url_item,
        "ts": int(ts_epoch),
        "sentiment": round(float(sent), 3),
        "impact": tags,
        "trust": round(float(trust), 3),
    }


def _fetch_gdelt(symbol: str, limit: int) -> List[Dict]:
    query = f'"{symbol}" AND (crypto OR bitcoin OR ethereum)'
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": query, "maxrecords": str(limit), "format": "json", "mode": "artlist"}
    resp = requests.get(url, params=params, timeout=NEWS_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    articles = data.get("articles") or []
    items: List[Dict] = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        url_item = (a.get("url") or "").strip()
        if not _allowed_url(url_item):
            continue
        source = (a.get("sourcecommonname") or a.get("domain") or "").strip()
        ts = a.get("seendate") or ""
        try:
            ts_epoch = int(time.mktime(time.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")))
        except Exception:
            ts_epoch = int(time.time())
        items.append(_normalize_item(title, url_item, source, ts_epoch, a.get("excerpt", "")))
    return items


def _fetch_newsapi(symbol: str, limit: int) -> List[Dict]:
    if not NEWSAPI_TOKEN:
        return []
    params = {
        "q": symbol.upper(),
        "language": "en",
        "pageSize": min(limit, NEWS_MAX),
        "sortBy": "publishedAt",
        "apiKey": NEWSAPI_TOKEN,
    }
    url = "https://newsapi.org/v2/everything"
    resp = requests.get(url, params=params, timeout=NEWS_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    articles = data.get("articles") or []
    items: List[Dict] = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        url_item = (a.get("url") or "").strip()
        if not _allowed_url(url_item):
            continue
        source = (a.get("source", {}).get("name") or "").strip() or "newsapi"
        published = a.get("publishedAt") or ""
        ts_epoch = _parse_iso_to_epoch(str(published))
        items.append(_normalize_item(title, url_item, source, ts_epoch, a.get("description") or ""))
    return items


def _fetch_rss(symbol: str, limit: int) -> List[Dict]:
    if not RSS_FEEDS:
        return []
    import xml.etree.ElementTree as ET  # stdlib, keep lightweight

    collected: List[Dict] = []

    def _get_text(el, *tags):
        for t in tags:
            found = el.find(t)
            if found is not None and (found.text or "").strip():
                return found.text.strip()
        return ""

    for feed_url in RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=NEWS_TIMEOUT)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception:
            continue

        items = root.findall(".//item") or root.findall(".//entry")
        for item in items:
            title = _get_text(item, "title")
            if not title:
                continue
            link = _get_text(item, "link", "id")
            if not link:
                # Atom feeds sometimes have href attribute
                link_el = item.find("link")
                if link_el is not None:
                    link = link_el.attrib.get("href", "")
            if not _allowed_url(link):
                continue

            pub = _get_text(item, "pubDate", "updated", "published")
            ts_epoch = _parse_iso_to_epoch(pub) if pub else int(time.time())
            host = urlparse(link).hostname or "rss"
            collected.append(_normalize_item(title, link, host, ts_epoch, _get_text(item, "description", "summary")))

            if len(collected) >= limit:
                break
        if len(collected) >= limit:
            break
    return collected


def _fetch_cryptopanic(symbol: str, limit: int) -> List[Dict]:
    if not CRYPTOPANIC_TOKEN:
        return []
    params = {
        "auth_token": CRYPTOPANIC_TOKEN,
        "currencies": symbol.upper(),
        "kind": "news",
        "regions": "en",
        "public": "true",
        "filter": "hot",
        "limit": min(limit, NEWS_MAX),
    }
    url = "https://cryptopanic.com/api/v1/posts/"
    resp = requests.get(url, params=params, timeout=NEWS_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or []
    items: List[Dict] = []
    for r in results:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        url_item = (r.get("url") or "").strip()
        if not _allowed_url(url_item):
            continue
        host = urlparse(url_item).hostname or "source"
        published = r.get("published_at") or r.get("published_at_f") or ""
        ts_epoch = _parse_iso_to_epoch(str(published))
        items.append(_normalize_item(title, url_item, host, ts_epoch, str(r.get("body") or "")))
    return items


def fetch_news(symbol: str, limit: int = NEWS_MAX, *, force: bool = False) -> Dict:
    sym = (symbol or "").strip().upper() or "BTC"
    now = time.time()
    cached = _cache.get(sym)
    if cached and not force and now - cached[0] < NEWS_TTL:
        return cached[1]

    items: List[Dict] = []
    providers: List[str] = []

    if CRYPTOPANIC_TOKEN:
        try:
            fetched = _fetch_cryptopanic(sym, min(limit, NEWS_MAX))
            if fetched:
                providers.append("cryptopanic")
                items.extend(fetched)
        except Exception:
            pass

    if NEWSAPI_TOKEN and len(items) < limit:
        try:
            fetched = _fetch_newsapi(sym, min(limit - len(items), NEWS_MAX))
            if fetched:
                providers.append("newsapi")
                items.extend(fetched)
        except Exception:
            pass

    if RSS_FEEDS and len(items) < limit:
        try:
            fetched = _fetch_rss(sym, min(limit - len(items), NEWS_MAX))
            if fetched:
                providers.append("rss")
                items.extend(fetched)
        except Exception:
            pass

    if len(items) < limit:
        try:
            fetched = _fetch_gdelt(sym, min(limit - len(items), NEWS_MAX))
            if fetched:
                providers.append("gdelt")
                items.extend(fetched)
        except Exception:
            pass

    items = _dedupe(items)
    # Normalize timestamps and drop very old/invalid ones
    normalized: List[Dict] = []
    now_epoch = int(time.time())
    for it in items:
        ts_val = int(it.get("ts") or 0)
        if ts_val < _MIN_TS:
            ts_val = now_epoch
        it["ts"] = ts_val
        normalized.append(it)

    items = normalized
    items.sort(key=lambda i: i.get("ts", 0), reverse=True)
    items = items[:limit]

    momentum = 0.0
    trust_avg = 0.0
    if items:
        momentum = sum(float(i.get("sentiment", 0.0)) for i in items) / max(len(items), 1)
        trust_avg = sum(float(i.get("trust", 0.0)) for i in items) / max(len(items), 1)

    payload = {
        "symbol": sym,
        "items": items,
        "momentum": round(momentum, 3),
        "trust_avg": round(trust_avg, 3),
        "fetched_at": int(now),
        "provider": ",".join(providers) if providers else "gdelt",
    }
    _cache[sym] = (now, payload)
    return payload
