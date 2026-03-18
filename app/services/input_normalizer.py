from __future__ import annotations

"""
Canonical input normalization helpers used before routing/planning.

Why this module exists:
- Keep prompt normalization in one place so mode/tool routing stays consistent.
- Normalize common contractions/typos across EN/ES variants before heuristics run.
"""

import re
from urllib.parse import urlparse

_SMART_APOSTROPHES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u2032": "'",
        "\u0060": "'",
        "\u00b4": "'",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")

_ROUTING_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bwhere(?:'s|s)\b", flags=re.IGNORECASE), "where is"),
    (re.compile(r"\bwhere\s+s\b", flags=re.IGNORECASE), "where is"),
    (re.compile(r"\bwhat(?:'s|s)\b", flags=re.IGNORECASE), "what is"),
    (re.compile(r"\bwhat\s+s\b", flags=re.IGNORECASE), "what is"),
    (re.compile(r"\bwho(?:'s|s)\b", flags=re.IGNORECASE), "who is"),
    (re.compile(r"\bwho\s+s\b", flags=re.IGNORECASE), "who is"),
    (re.compile(r"\bhow(?:'s|s)\b", flags=re.IGNORECASE), "how is"),
    (re.compile(r"\bhow\s+s\b", flags=re.IGNORECASE), "how is"),
    (re.compile(r"\bdonde(?:'s|s)\b", flags=re.IGNORECASE), "donde es"),
    (re.compile(r"\bdonde\s+s\b", flags=re.IGNORECASE), "donde es"),
)

_MODE_PREFIX_RE = re.compile(r"^\s*(web|url|crypto|project|image)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
_DOMAIN_LIKE_RE = re.compile(
    r"^(?:https?://)?(?:localhost|[\w.-]+\.[a-z]{2,}|\d{1,3}(?:\.\d{1,3}){3})(?::\d{2,5})?(?:/[^\s]*)?$",
    re.IGNORECASE,
)


def normalize_user_input(text: str) -> str:
    value = str(text or "")
    value = value.translate(_SMART_APOSTROPHES)
    value = value.replace("\u00a0", " ")
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value


def normalize_for_routing(text: str) -> str:
    value = normalize_user_input(text).lower()
    for pattern, replacement in _ROUTING_REWRITES:
        value = pattern.sub(replacement, value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value


def split_mode_prefix(text: str) -> tuple[str | None, str]:
    value = normalize_user_input(text)
    match = _MODE_PREFIX_RE.match(value)
    if not match:
        return None, value
    mode = str(match.group(1) or "").strip().lower() or None
    payload = normalize_user_input(str(match.group(2) or ""))
    return mode, payload


def looks_like_url_candidate(text: str) -> bool:
    value = normalize_user_input(text)
    if not value:
        return False
    token = value.split()[0]
    if not token:
        return False
    if not _DOMAIN_LIKE_RE.match(token):
        return False

    if token.lower().startswith(("http://", "https://")):
        try:
            parsed = urlparse(token)
            return bool(parsed.netloc)
        except Exception:
            return False
    return True
