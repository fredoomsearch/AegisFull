from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from app.llm_client_offload import MAX_NEW_TOKENS
from app.models.llm_utils import detect_build_intent, is_code_question, is_market_question, is_repo_content_question
from app.services.input_normalizer import strip_attachment_context
from app.tools import sanitize_messages

logger = logging.getLogger(__name__)

FAST_MODE = os.getenv("AEGIS_FAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
FAST_MAX_TOKENS = int(os.getenv("AEGIS_FAST_MAX_TOKENS", "512"))
USE_OPENAI_FALLBACK = (os.getenv("AEGIS_USE_OPENAI_FALLBACK", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
OPENAI_MODEL = (os.getenv("OPENAI_MODEL", "") or "gpt-4o-mini").strip()
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "20"))

_BACKEND_FAILURE_FRAGMENTS = (
    "groq backend is not configured",
    "groq backend failed",
    "groq request failed",
    "groq http error",
    "groq returned non-json response",
    "groq response missing",
    "groq response was empty",
    "local llm backend is not available",
    "llm backend is not fully configured",
    "llama-cpp-python missing",
    "openai fallback is enabled but openai_api_key is not set",
    "openai fallback failed",
    "openai client is not installed",
)

try:  # pragma: no cover
    import openai  # type: ignore
except Exception:  # noqa: BLE001
    openai = None  # type: ignore



# TOP_P EXPLANAITION

# How it Works
# Instead of looking at every possible word or a fixed number of words, Top-p selects the smallest group of words whose combined probabilities add up to your chosen value, p. 
# Example: If you set top_p = 0.9 and the AI is predicting the next word for "The cat sat on the...":

#     mat (40% probability)
#     rug (30% probability)
#     floor (20% probability) — Cumulative total is now 90%
#     pizza (10% probability) — Excluded      /   

PROFILES = {
    # Keep interactive latency bounded by using smaller mode-specific token caps.
    "general": {"temperature": 0.3, "top_p": 0.95, "max_tokens": 900},
    "chat": {"temperature": 0.3, "top_p": 0.95, "max_tokens": 900},
    "web": {"temperature": 0.25, "top_p": 0.92, "max_tokens": 850},
    "url": {"temperature": 0.25, "top_p": 0.92, "max_tokens": 850},
    "code": {"temperature": 0.15, "top_p": 0.9, "max_tokens": 1200},
    "crypto": {"temperature": 0.2, "top_p": 0.92, "max_tokens": 900},
}


_AUTO_ROUTE_HEAVY_MODES = {"code", "crypto", "agent"}


def _last_user_text(messages: List[Dict]) -> str:
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role != "user":
            continue
        text = str(message.get("content") or "").strip()
        if text:
            return text
    return ""


def _route_prompt_text(messages: List[Dict]) -> str:
    parts: List[str] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "").strip()
        if content:
            parts.append(content)
    return strip_attachment_context("\n".join(parts)).strip()


def _confidence_bucket(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.55:
        return "medium"
    return "low"


def _quantitative_route_signal(prompt_text: str, *, mode: str, hard_turn: bool, build_intent: Dict[str, Any]) -> Dict[str, Any]:
    clean = strip_attachment_context(prompt_text or "")
    compact = " ".join(clean.split())
    lower = compact.lower()
    confidence = 0.86
    factors: List[str] = []

    if len(compact) > 1500:
        confidence -= 0.22
        factors.append("very_long_prompt")
    elif len(compact) > 900:
        confidence -= 0.14
        factors.append("long_prompt")
    elif len(compact) > 500:
        confidence -= 0.08
        factors.append("medium_prompt")
    elif len(compact) < 24:
        confidence += 0.04
        factors.append("short_prompt")

    if hard_turn:
        confidence -= 0.12
        factors.append("hard_turn")
    if bool(build_intent.get("is_build")):
        confidence -= 0.08
        factors.append("build_intent")
    if is_code_question(compact):
        confidence -= 0.08
        factors.append("code_question")
    if is_market_question(compact):
        confidence -= 0.06
        factors.append("market_question")
    if is_repo_content_question(compact):
        confidence -= 0.06
        factors.append("repo_content")
    if any(token in lower for token in ("latest", "current", "today", "news", "weather", "market", "price", "source", "sources", "citation", "cite")):
        confidence -= 0.05
        factors.append("freshness_or_evidence")
    if mode in {"code", "crypto"}:
        confidence -= 0.04
        factors.append(f"mode:{mode}")

    confidence = max(0.08, min(0.98, confidence))
    bucket = _confidence_bucket(confidence)
    if confidence >= 0.75:
        gate = "allow_local"
        risk = "low"
    elif confidence >= 0.55:
        gate = "prefer_remote"
        risk = "medium"
    else:
        gate = "prefer_remote"
        risk = "high"

    if not factors:
        factors.append("balanced_prompt")

    return {
        "confidence": confidence,
        "confidence_bucket": bucket,
        "gate": gate,
        "risk": risk,
        "factors": factors,
        "mode": mode,
    }


def llm_route_policy(messages: List[Dict], *, mode: str = "general") -> Dict[str, Any]:
    configured = (os.getenv("AEGIS_LLM_PROVIDER") or "local").strip().lower()
    profile = configured if configured in {"local", "groq", "auto"} else "local"
    prompt_text = _last_user_text(messages) or _route_prompt_text(messages)
    build_intent = detect_build_intent(prompt_text)
    hard_turn = bool(
        mode in _AUTO_ROUTE_HEAVY_MODES
        or bool(build_intent.get("is_build"))
        or is_code_question(prompt_text)
        or is_market_question(prompt_text)
        or is_repo_content_question(prompt_text)
        or len(prompt_text) > 1200
    )
    quantitative = _quantitative_route_signal(prompt_text, mode=mode, hard_turn=hard_turn, build_intent=build_intent)

    alternative_provider = "groq" if profile != "groq" else "local"
    if profile == "auto":
        try:
            from app import llm_client_offload

            remote_ready = bool(llm_client_offload.llm_status().get("remote_ready"))
        except Exception:
            remote_ready = False

        if quantitative["gate"] == "prefer_remote" and remote_ready:
            preferred_provider = "groq"
            route_reason = f"quantitative_remote:{quantitative['confidence_bucket']}"
        elif quantitative["gate"] == "prefer_remote":
            preferred_provider = "local"
            route_reason = f"quantitative_local_fallback:{quantitative['confidence_bucket']}"
        elif hard_turn and remote_ready:
            preferred_provider = "groq"
            route_reason = "hard_turn_remote"
        else:
            preferred_provider = "local"
            route_reason = "simple_turn"
        alternative_provider = "local" if preferred_provider == "groq" else "groq"
    else:
        preferred_provider = profile
        route_reason = "explicit_provider"
        alternative_provider = "groq" if preferred_provider == "local" else "local"

    return {
        "configured_provider": profile,
        "preferred_provider": preferred_provider,
        "alternative_provider": alternative_provider,
        "route_reason": route_reason,
        "hard_turn": hard_turn,
        "prompt_chars": len(prompt_text),
        "mode": mode,
        "quantitative": quantitative,
    }


def _looks_like_local_failure(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    return any(
        frag in lowered
        for frag in (
            "llm backend is not fully configured",
            "local llm backend is not available",
            "llama-cpp-python missing",
        )
    )


def _looks_like_backend_failure_message(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return True
    return any(fragment in lowered for fragment in _BACKEND_FAILURE_FRAGMENTS)


def _safe_llm_unavailable_message() -> str:
    return (
        "The language model is temporarily unavailable right now. "
        "Please retry in a moment."
    )


def _normalize_backend_failure_text(text: str) -> str:
    if not _looks_like_backend_failure_message(text):
        return text
    return _safe_llm_unavailable_message()


def _openai_generate(
    messages: List[Dict],
    max_tokens: int,
    temperature: float,
    top_p: float,
) -> str:
    if openai is None:
        return (
            "OpenAI client is not installed. "
            "Install the openai package or disable fallback."
        )

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return "OpenAI fallback is enabled but OPENAI_API_KEY is not set."

    openai.api_key = api_key
    try:
        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            request_timeout=OPENAI_TIMEOUT,
        )
        choices = resp.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            return str(msg.get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenAI fallback failed: %s", exc)
        return "OpenAI fallback failed."
    return ""


def generate_response(
    messages: List[Dict],
    max_new_tokens: Optional[int] = None,
    temperature: Optional[float] = None,  # optional manual override
    top_p: Optional[float] = None,        # optional manual override
    mode: str = "general",
    **extra_kwargs: Any,
) -> str:
    """
    Generic LLM entrypoint used by the rest of the app.

    - Sanitizes messages.
    - Caps tokens using MAX_NEW_TOKENS.
    - Delegates to the local offload backend (llm_client_offload).
    - On failure, returns a safe placeholder instead of crashing.
    """
    profile = PROFILES.get(mode, PROFILES["general"])
    profile_max = int(min(profile.get("max_tokens", MAX_NEW_TOKENS), MAX_NEW_TOKENS))
    if FAST_MODE:
        # Keep responses short in fast mode to avoid long blocking calls.
        profile_max = min(profile_max, FAST_MAX_TOKENS)

    if max_new_tokens is None or max_new_tokens <= 0:
        max_tokens = profile_max
    else:
        max_tokens = int(min(max_new_tokens, MAX_NEW_TOKENS))

    temperature = float(temperature if temperature is not None else profile["temperature"])
    top_p = float(top_p if top_p is not None else profile["top_p"])

    messages = sanitize_messages(messages)
    route = llm_route_policy(messages, mode=mode)

    try:
        from app import llm_client_offload
        from app.services import runtime_metrics

        q = dict(route.get("quantitative") or {})
        try:
            runtime_metrics.record_model_competition(
                champion=str(route.get("preferred_provider") or "local"),
                challenger=str(route.get("alternative_provider") or ("groq" if route.get("preferred_provider") == "local" else "local")),
                route_mode=str(route.get("mode") or mode),
                route_reason=str(route.get("route_reason") or ""),
                confidence_bucket=str(q.get("confidence_bucket") or "unknown"),
                gate=str(q.get("gate") or ""),
            )
        except Exception:
            logger.debug("Failed to record model competition snapshot", exc_info=True)

        local = llm_client_offload.generate_response(
            messages,
            max_new_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            preferred_provider=route.get("preferred_provider"),
        )
        if USE_OPENAI_FALLBACK and _looks_like_local_failure(local):
            return _normalize_backend_failure_text(_openai_generate(messages, max_tokens, temperature, top_p))
        return _normalize_backend_failure_text(local)
    except Exception as exc:  # noqa: BLE001
        logger.error("llm_client_offload failed: %s", exc)
        if USE_OPENAI_FALLBACK:
            return _normalize_backend_failure_text(_openai_generate(messages, max_tokens, temperature, top_p))
        return _normalize_backend_failure_text(
            "LLM backend is not fully configured. "
            "The server is running, but no model is available."
        )


class LLMClient:
    """
    Thin wrapper to allow DI/mocking in services if needed.
    """

    def generate(
        self,
        messages: List[Dict],
        max_new_tokens: Optional[int] = None,
        mode: str = "general",
        **kwargs: Any,
    ) -> str:
        return generate_response(messages, max_new_tokens=max_new_tokens, mode=mode, **kwargs)
    

# Why this file is very important (almost “more important” than others)

# This file is basically the LLM front-door for your whole backend. Everything that wants “AI magic” should go through here:

# Single source of truth
# Any route (/chat, tools, memory summarization, RAG, etc.) should import generate_response (or LLMClient) from here, not from llm_client_offload. That means one place to:

# Set token limits (MAX_NEW_TOKENS)

# Sanitize messages

# Handle logging and fallbacks

# Add global behaviors (e.g., safety filters, telemetry)

# Hard decoupling from the backend engine
# Today: you use local WizardCoder via llm_client_offload.
# Tomorrow: you might want:

# OpenAI / Anthropic / Groq cloud fallback

# Two different models (e.g., “fast” and “smart”)

# Routing by temperature, cost, or context length

# You do not want to change 50 endpoints and services; you change the logic here, in one file, and the rest of the app just keeps calling generate_response.

# Architecture boundary
# Think of layers:

# API / services: app/api/chat.py, memory, tools, etc.
# ➜ depend on this file (app.models.llm_client)

# LLM Backend(s): app/llm_client_offload.py (and maybe app/llm_client_openai.py later)
# ➜ do the low-level heavy lifting (talk to llama.cpp, HTTP API, etc.)

# This file is the clean interface between “business logic” and “LLM implementation”. That’s textbook clean architecture / hexagonal stuff.

# Testability
# Because you have the LLMClient class here, in one place, you can:

# Inject a fake client in tests that returns deterministic strings.

# Swap real vs mock just by changing DI, without touching your API endpoints.

# Future features
# When you add:

# Per-user temperature/top_p policies

# Model selection per conversation

# Tracing, logging, metrics, cost accounting

# All that orchestration belongs here. That’s why this file is strategic.

# Short version: this file is the brain adapter. Everything else is “body parts” asking for help; this is the thing that decides how to talk to the actual model. Treat it nice.
