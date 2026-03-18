from __future__ import annotations

"""
Prompt/log secret redaction helpers.

Why this module exists:
- Reduce accidental secret leakage to models/logs.
- Apply lightweight, deterministic masking before external hops.
"""

import os
import re

_ENABLED = (os.getenv("AEGIS_REDACT_SECRETS", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI-style keys
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "sk-***REDACTED***"),
    # HuggingFace tokens
    (re.compile(r"\bhf_[A-Za-z0-9]{16,}\b"), "hf_***REDACTED***"),
    # AWS access keys (common prefix)
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***REDACTED***"),
    # Generic bearer tokens
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"), "Bearer ***REDACTED***"),
    # Common env-style assignments
    (re.compile(r"(?i)\b(api[_-]?key|token|secret)\s*[:=]\s*['\"]?([A-Za-z0-9._~+/=-]{12,})['\"]?"), r"\1=***REDACTED***"),
]


def redact_secrets(text: str) -> str:
    """
    Best-effort secret redaction for prompts/logs.

    This is intentionally conservative and pattern-based. It won't catch every secret,
    but it prevents the most common accidental leak vectors (API keys/tokens) from
    being forwarded to external providers or stored in long-lived logs.
    """
    if not _ENABLED:
        return text
    if not text:
        return text
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out
