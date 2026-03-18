from __future__ import annotations

"""
Small ML-adjacent deterministic helpers shared across services/api.
"""

import hashlib
from typing import Iterable

POS_WORDS_DEFAULT: tuple[str, ...] = (
    "rise",
    "surge",
    "bull",
    "gain",
    "positive",
    "beat",
    "record",
    "upgrade",
    "approve",
    "strong",
    "growth",
)

NEG_WORDS_DEFAULT: tuple[str, ...] = (
    "fall",
    "drop",
    "bear",
    "loss",
    "negative",
    "miss",
    "hack",
    "ban",
    "lawsuit",
    "fine",
    "weak",
    "decline",
)


def sentiment_score(
    text: str | None,
    *,
    pos_words: Iterable[str] = POS_WORDS_DEFAULT,
    neg_words: Iterable[str] = NEG_WORDS_DEFAULT,
    clamp: float = 0.25,
) -> float:
    """
    Lightweight lexical sentiment score bounded to [-clamp, +clamp].
    """
    if not text:
        return 0.0
    lowered = text.lower()
    pos = sum(word in lowered for word in pos_words)
    neg = sum(word in lowered for word in neg_words)
    if pos == 0 and neg == 0:
        return 0.0
    score = (pos - neg) / max(1, pos + neg)
    bound = abs(float(clamp))
    return max(-bound, min(bound, score))


def hash_embed(text: str, dim: int) -> list[float]:
    """
    Deterministic text->vector fallback used when embedding backends are unavailable.
    """
    buf = text.encode("utf-8", errors="ignore")
    if not buf:
        buf = b"\x00"
    digest = hashlib.sha1(buf).digest()
    repeats = (dim + len(digest) - 1) // len(digest)
    raw = (digest * repeats)[:dim]
    return [(b - 128) / 128.0 for b in raw]

