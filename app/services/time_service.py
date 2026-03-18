from __future__ import annotations

"""
Time-question helper.

Why this module exists:
- Answer simple timezone/time-of-day questions without invoking heavy model flow.
"""

import re
from datetime import datetime
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


CITY_TZ = {
    "colombia": "America/Bogota",
    "bogota": "America/Bogota",
    "méxico": "America/Mexico_City",
    "mexico": "America/Mexico_City",
    "argentina": "America/Argentina/Buenos_Aires",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "new york": "America/New_York",
    "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "london": "Europe/London",
    "madrid": "Europe/Madrid",
    "berlin": "Europe/Berlin",
    "tokyo": "Asia/Tokyo",
    "sydney": "Australia/Sydney",
    "dubai": "Asia/Dubai",
    "singapore": "Asia/Singapore",
}

_TIME_PATTERNS = [
    # English
    re.compile(r"\bwhat\s+time\s+is\s+it\s+in\s+(.+?)\??\s*$", re.I),
    re.compile(r"\btime\s+in\s+(.+?)\??\s*$", re.I),
    # Spanish
    re.compile(r"\bqu[eé]\s+hora\s+es\s+en\s+(.+?)\??\s*$", re.I),
    re.compile(r"\bhora\s+en\s+(.+?)\??\s*$", re.I),
]

_TS_PREFIX = re.compile(r"^\s*\[[^\]]+\]\s*")  # removes: [2025-12-15 00:00:00]


def _normalize_city(raw: str) -> str:
    return " ".join((raw or "").strip().lower().replace(",", " ").split())


def _time_in_tz(tz_name: str) -> str:
    if ZoneInfo is not None:
        try:
            now = datetime.now(ZoneInfo(tz_name))
            return now.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    try:
        import pytz  # type: ignore
        tz = pytz.timezone(tz_name)
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:
        raise RuntimeError(f"Timezone data not available for {tz_name}: {exc}") from exc


def maybe_answer_time_question(user_text: str, lang: str = "en") -> Optional[str]:
    text = _TS_PREFIX.sub("", (user_text or "").strip())
    if not text:
        return None

    city_raw: Optional[str] = None
    for pat in _TIME_PATTERNS:
        m = pat.search(text)
        if m:
            city_raw = m.group(1)
            break

    if not city_raw:
        return None

    city_norm = _normalize_city(city_raw)
    tz = CITY_TZ.get(city_norm)
    if not tz:
        return None

    ts = _time_in_tz(tz)

    if (lang or "").lower().startswith("es"):
        return f"En {city_raw.strip()} son las {ts} ({tz})."
    return f"It's currently {ts} ({tz}) in {city_raw.strip()}."
