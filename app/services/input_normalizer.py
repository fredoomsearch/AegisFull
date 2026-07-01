from __future__ import annotations

"""
Canonical input normalization helpers used before routing/planning.

Why this module exists:
- Keep prompt normalization in one place so mode/tool routing stays consistent.
- Normalize common contractions/typos across EN/ES variants before heuristics run.
- Security: sanitization, prompt injection detection for safety.
"""

import html
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
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

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

# Mode normalization: Spanish/English prefixes -> canonical mode names
# "modo:" or "Mode:" are just prefixes, the actual mode is in the payload
_MODE_ALIASES = {
    # Spanish prefixes (these are just prefix markers, use payload)
    "modo": "chat",
    "mode": "chat",
    # Canonical mode names (used as-is)
    "web": "web",
    "url": "url",
    "crypto": "crypto",
    "cripto": "crypto",
    "image": "image",
    "imagen": "image",
    "auto": "auto",
    "project": "project",
    "proyecto": "project",
    "chat": "chat",
    "local": "local",
}

# Updated regex to support both "modo:"/"Mode:" and "web:" prefixes
_MODE_PREFIX_RE = re.compile(
    r"^\s*(modo|mode|web|url|crypto|project|image|local)\s*:\s*(.*)$",
    re.IGNORECASE | re.DOTALL
)
_DOMAIN_LIKE_RE = re.compile(
    r"^(?:https?://)?(?:localhost|[\w.-]+\.[a-z]{2,}|\d{1,3}(?:\.\d{1,3}){3})(?::\d{2,5})?(?:/[^\s]*)?$",
    re.IGNORECASE,
)


def strip_attachment_context(text: str) -> str:
    raw = str(text or "")
    for marker in ("[Attachment context ", "[Contexto de adjunto "):
        idx = raw.find(marker)
        if idx >= 0:
            trimmed = raw[:idx].strip()
            return trimmed or raw.strip()
    return raw.strip()


def normalize_user_input(text: str) -> str:
    value = str(text or "")
    value = value.translate(_SMART_APOSTROPHES)
    value = value.replace("\u00a0", " ")
    value = _CONTROL_CHAR_RE.sub(" ", value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value


def normalize_for_routing(text: str) -> str:
    value = normalize_user_input(strip_attachment_context(text)).lower()
    for pattern, replacement in _ROUTING_REWRITES:
        value = pattern.sub(replacement, value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value


def split_mode_prefix(text: str) -> tuple[str | None, str]:
    value = normalize_user_input(text)
    match = _MODE_PREFIX_RE.match(value)
    if not match:
        return None, value
    mode_raw = str(match.group(1) or "").strip().lower() or None
    # Map aliases to canonical mode names
    mode = _MODE_ALIASES.get(mode_raw, mode_raw) if mode_raw else None
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


def validate_url_format(url: str) -> tuple[bool, str]:
    """
    Enhanced URL validation with proper scheme and netloc checking.
    Returns (is_valid, error_message) tuple.
    """
    value = normalize_user_input(url)
    if not value:
        return False, "URL cannot be empty"
    
    # Extract first token to check as URL
    token = value.split()[0]
    if not token:
        return False, "Invalid URL format"
    
    # Check if it has a valid scheme
    if not token.lower().startswith(("http://", "https://")):
        # Try adding https:// prefix
        token = "https://" + token
    
    try:
        parsed = urlparse(token)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc
        
        # Validate scheme
        if scheme not in ("http", "https"):
            return False, f"Invalid scheme: {scheme}. Use http:// or https://"
        
        # Validate netloc exists
        if not netloc:
            return False, "Invalid URL: no domain or hostname"
        
        # Check for minimal TLD (at least one dot in domain)
        if "." not in netloc and netloc not in ("localhost", "test"):
            return False, "Invalid domain format"
        
        # Additional check: no trailing dots in domain
        if netloc.endswith("."):
            return False, "Invalid domain: trailing dot"
        
        return True, ""
    
    except Exception as e:
        return False, f"URL parsing error: {str(e)[:50]}"


# -----------------------------------------------------------------------------
# Security: Input Sanitization
# -----------------------------------------------------------------------------

# Patterns that may indicate prompt injection attempts
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(your\s+)?(instructions|rules)", re.IGNORECASE),
    re.compile(r"(you\s+are|act\s+as)\s+(now\s+)?(a\s+)?different", re.IGNORECASE),
    re.compile(r"system\s*:\s*[^a-z]+", re.IGNORECASE),
    re.compile(r"assistant\s*:\s*[^a-z]+", re.IGNORECASE),
    re.compile(r"\b(jailbreak|bypass)\b.*(rules|safety)", re.IGNORECASE),
    re.compile(r"new\s+instruction(s)?\s*[:;]", re.IGNORECASE),
    re.compile(r"<\|(?:system|user|assistant)\|>", re.IGNORECASE),
    re.compile(r"```system\s*[\s\S]*?```", re.IGNORECASE),
)

# HTML tag pattern for sanitization
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def sanitize_html(text: str) -> str:
    """
    Strip HTML/JS tags and escape entities for safe display.
    """
    if not text:
        return ""
    # Escape HTML entities first (prevents double-decoding attacks)
    escaped = html.escape(text, quote=True)
    # Remove remaining HTML tags
    return _HTML_TAG_RE.sub("", escaped)


def detect_prompt_injection(text: str) -> tuple[bool, str]:
    """
    Detect potential prompt injection attempts.
    Returns (is_safe, warning) tuple.
    """
    if not text:
        return True, ""
    
    lowered = text.lower()
    
    # Check each pattern
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            # Check if it's clearly malicious (not a user asking about prompt injection)
            if any(
                token in lowered
                for token in ("what is", "explain", "how does", "describe", "que es", "explica")
            ):
                # Suspicious but user may be asking about it - flag for review
                return False, "flagged_for_review"
            return False, "potential_injection"
    
    return True, ""


def sanitize_input(text: str, *, allow_html: bool = False) -> str:
    """
    Primary entry point for input sanitization.
    """
    if not text:
        return ""
    
    value = str(text)
    
    # Detect prompt injection
    is_safe, warning = detect_prompt_injection(value)
    if not is_safe and warning == "potential_injection":
        # Strip the suspicious parts but keep user content
        for pattern in _PROMPT_INJECTION_PATTERNS:
            value = pattern.sub("[FILTERED]", value)
    
    # Sanitize HTML if not allowed
    if not allow_html:
        value = sanitize_html(value)
    
    return value.strip()


# -----------------------------------------------------------------------------
# PII Detection and Redaction (Optional Stage 1.3)
# -----------------------------------------------------------------------------

# PII patterns
_PII_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PII_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,4}\b")
_PII_SSN_RE = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
_PII_CC_RE = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")


def detect_pii(text: str) -> list[dict[str, str]]:
    """
    Detect potential PII in text.
    Returns list of detections with type and match.
    """
    detections = []
    if not text:
        return detections
    
    # Email
    for match in _PII_EMAIL_RE.finditer(text):
        detections.append({
            "type": "email",
            "value": match.group(),
            "start": match.start(),
            "end": match.end(),
        })
    
    # Phone (simple pattern, may have false positives)
    for match in _PII_PHONE_RE.finditer(text):
        val = match.group()
        # Skip if likely a year or date
        if len(val.replace("-", "").replace(" ", "")) >= 7:
            detections.append({
                "type": "phone",
                "value": val,
                "start": match.start(),
                "end": match.end(),
            })
    
    # SSN-like
    for match in _PII_SSN_RE.finditer(text):
        detections.append({
            "type": "ssn",
            "value": "[SSN]",
            "start": match.start(),
            "end": match.end(),
        })
    
    # Credit card-like
    for match in _PII_CC_RE.finditer(text):
        detections.append({
            "type": "credit_card",
            "value": "[CC]",
            "start": match.start(),
            "end": match.end(),
        })
    
    return detections


def redact_pii(text: str, *, replacement: str = "[PII]") -> str:
    """
    Redact detected PII from text.
    """
    if not text:
        return text
    
    # Replace SSN and credit card completely
    result = _PII_SSN_RE.sub(replacement, text)
    result = _PII_CC_RE.sub(replacement, result)
    
    # For emails and phones, we could either redact or mask
    # For safety, replace with placeholder
    result = _PII_EMAIL_RE.sub(replacement, result)
    
    return result
