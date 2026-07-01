from __future__ import annotations

"""
Context compression utilities for reducing LLM prompt size.

Why this module exists:
- Compress context when it exceeds token limits.
- Preserve key information while reducing size.
- Support multiple compression strategies.
"""

import json
import re
from typing import Any


# Token estimation constants (approximate)
AVG_TOKENS_PER_CHAR = 0.25  # ~4 chars per token
MAX_CONTEXT_CHARS = int.from_bytes(
    __import__("os").environ.get("AEGIS_MAX_CONTEXT_CHARS", "12000").encode() or b"12000"
)


def estimate_tokens(text: str) -> int:
    """Estimate token count from text."""
    if not text:
        return 0
    return int(len(text) * AVG_TOKENS_PER_CHAR)


def compress_messages(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 4000,
    preserve_system: bool = True,
) -> list[dict[str, str]]:
    """
    Compress message history to fit within token limit.
    
    Args:
        messages: List of messages with 'role' and 'content'
        max_tokens: Maximum tokens to preserve
        preserve_system: Keep system message intact
    
    Returns:
        Compressed message list
    """
    if not messages:
        return []
    
    result: list[dict[str, str]] = []
    total_tokens = 0
    
    # Keep system message if present
    system_msg = None
    if preserve_system and messages and messages[0].get("role") == "system":
        system_msg = messages[0]
        result.append(system_msg)
        total_tokens += estimate_tokens(system_msg.get("content", ""))
        messages = messages[1:]
    
    # Work backwards from most recent messages
    for msg in reversed(messages):
        content = msg.get("content", "")
        msg_tokens = estimate_tokens(content)
        
        if total_tokens + msg_tokens <= max_tokens:
            result.insert(len(system_msg) if system_msg else 0, msg)
            total_tokens += msg_tokens
        else:
            break
    
    return result


def compress_CONTEXT(
    context: list[dict[str, Any]],
    *,
    max_items: int = 8,
    max_text_len: int = 500,
) -> list[dict[str, Any]]:
    """
    Compress context items to fit within limits.
    
    Args:
        context: List of context items (dicts with title, snippet, link, etc.)
        max_items: Maximum items to keep
        max_text_len: Max characters per text field
    
    Returns:
        Compressed context list
    """
    if not context:
        return []
    
    result: list[dict[str, Any]] = []
    
    for i, item in enumerate(context[:max_items]):
        if i >= max_items:
            break
        
        compressed: dict[str, Any] = {}
        
        # Compress text fields
        for key in ("title", "snippet", "text", "content"):
            if key in item:
                text = str(item.get(key) or "")
                if len(text) > max_text_len:
                    text = text[: max_text_len - 15].strip() + " [...] [truncated]"
                compressed[key] = text
        
        # Copy other fields as-is
        for key, value in item.items():
            if key not in compressed and key not in ("title", "snippet", "text", "content"):
                compressed[key] = value
        
        result.append(compressed)
    
    return result


def compress_sources(
    sources: list[dict[str, Any]],
    *,
    max_sources: int = 6,
    max_snippet_chars: int = 400,
) -> list[dict[str, Any]]:
    """
    Compress search/web sources for LLM prompt.
    
    Args:
        sources: List of source dicts
        max_sources: Maximum sources to keep
        max_snippet_chars: Max characters per snippet
    
    Returns:
        Compressed sources
    """
    if not sources:
        return []
    
    result: list[dict[str, Any]] = []
    
    for src in sources[:max_sources]:
        compressed = dict(src)  # Copy
        
        # Truncate snippet
        snippet = str(compressed.get("snippet") or "")
        if len(snippet) > max_snippet_chars:
            compressed["snippet"] = snippet[: max_snippet_chars - 15].strip() + " [...]"
        
        result.append(compressed)
    
    return result


def truncate_for_llm(
    text: str,
    *,
    max_chars: int = 8000,
    mode: str = "smart",
) -> str:
    """
    Truncate text for LLM consumption.
    
    Args:
        text: Input text
        max_chars: Maximum characters
        mode: Truncation mode - 'simple', 'smart', or '段落'
    
    Returns:
        Truncated text
    """
    if not text or len(text) <= max_chars:
        return text
    
    if mode == "simple":
        return text[:max_chars].strip()
    
    if mode == "smart":
        # Try to break at sentence boundary
        sentences = re.split(r"(?<=[.!?])\s+", text)
        result = ""
        
        for sent in sentences:
            if len(result) + len(sent) > max_chars:
                break
            result += sent + " "
        
        if not result:
            result = text[:max_chars].strip()
        
        if result and len(text) > max_chars:
            result = result.strip() + " [...] [truncated]"
        
        return result.strip()
    
    # mode == "段落" - preserve paragraphs
    paragraphs = text.split("\n\n")
    result = ""
    
    for para in paragraphs:
        if len(result) + len(para) + 2 > max_chars:
            break
        result += para + "\n\n"
    
    if not result:
        result = text[:max_chars].strip()
    
    if result and len(text) > max_chars:
        result = result.strip() + "\n\n[...] [truncated]"
    
    return result.strip()
