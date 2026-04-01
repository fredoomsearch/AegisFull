from __future__ import annotations

"""
Local llama.cpp / Groq-compatible backend.

- One-time GGUF load (thread-safe)
- Formats OpenAI-style messages into WizardCoder [INST]
- Applies sane defaults (token limits, sanitization)
- Fixes transcript echoing ("User:"/"Assistant:" loops) and empty-output hiccups
"""

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional
import requests

from app.tools import sanitize_messages

logger = logging.getLogger(__name__)
_llama_class: Any = None
_llama_import_attempted = False
_llama_import_error: str | None = None

# Avoid tokenizer fork warnings/deadlocks under multi-process/worker flows.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _get_llama_class() -> Any:
    global _llama_class, _llama_import_attempted, _llama_import_error
    if _llama_import_attempted:
        return _llama_class
    _llama_import_attempted = True
    try:  # pragma: no cover
        from llama_cpp import Llama as _ImportedLlama  # type: ignore

        _llama_class = _ImportedLlama
    except Exception as exc:  # noqa: BLE001
        _llama_class = None
        _llama_import_error = str(exc)
    return _llama_class

# ============================================================
# ENV / CONFIG
# ============================================================

MODEL_PATH = os.getenv(
    "AEGIS_MODEL_PATH", "./models/wizardcoder-python-7b-v1.0.Q5_K_M.gguf"
)
# Opt-in fast mode to keep the local model responsive on constrained hardware.
FAST_MODE = os.getenv("AEGIS_FAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
_raw_concurrency = os.getenv("AEGIS_LLM_CONCURRENCY", "").strip()
LLM_CONCURRENCY: Optional[int]
if _raw_concurrency:
    try:
        LLM_CONCURRENCY = max(1, int(_raw_concurrency))
    except ValueError:
        LLM_CONCURRENCY = None
else:
    # Default to single-flight generation; WizardCoder + llama.cpp doesn't love concurrent calls.
    LLM_CONCURRENCY = 1

def _get_int_env(name: str, default: int, fast_default: Optional[int] = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        if FAST_MODE and fast_default is not None:
            return fast_default
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r, using default %s", name, raw, default)
        return default


def _get_float_env(name: str, default: float, fast_default: Optional[float] = None) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        if FAST_MODE and fast_default is not None:
            return fast_default
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r, using default %s", name, raw, default)
        return default


# Queue wait budget before returning "model busy".
# 0 means block until a slot is available.
LLM_QUEUE_WAIT_SECONDS = max(
    0.0,
    _get_float_env("AEGIS_LLM_QUEUE_WAIT_SECONDS", 45.0, fast_default=20.0),
)
LLM_STALL_BUSY_AFTER_SECONDS = max(
    0.0,
    _get_float_env("AEGIS_LLM_STALL_BUSY_AFTER_SECONDS", 90.0, fast_default=30.0),
)


def _get_str_env(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip()


def _configured_provider() -> str:
    raw = _get_str_env("AEGIS_LLM_PROVIDER", "local").lower()
    if raw in {"local", "groq", "auto"}:
        return raw
    if raw:
        logger.warning("Invalid AEGIS_LLM_PROVIDER=%r, falling back to local", raw)
    return "local"


def _remote_model_name() -> str:
    return _get_str_env("AEGIS_GROQ_MODEL", "")


def _remote_base_url() -> str:
    return _get_str_env("AEGIS_GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")


def _remote_api_key() -> str:
    return _get_str_env("AEGIS_GROQ_API_KEY") or _get_str_env("GROQ_API_KEY")


def _remote_timeout_seconds() -> float:
    try:
        return max(1.0, float(_get_str_env("AEGIS_GROQ_TIMEOUT_SECONDS", "20")))
    except ValueError:
        return 20.0


def _remote_user_agent() -> str:
    return _get_str_env("AEGIS_GROQ_USER_AGENT", "AEGISChat/2026 Groq API Client")


# ============================================================
# STATUS
# ============================================================

def llm_status() -> Dict[str, Any]:
    model_exists = os.path.exists(MODEL_PATH)
    llama_class = _get_llama_class()
    provider = _configured_provider()
    remote_model = _remote_model_name()
    remote_base_url = _remote_base_url()
    remote_api_key = _remote_api_key()
    remote_ready = bool(remote_model and remote_api_key)
    local_available = bool(llama_class is not None and model_exists)
    local_ready = bool(local_available and _llama is not None)

    if provider == "groq":
        effective_provider = "groq"
        fallback_available = bool(remote_ready)
        available = bool(remote_ready)
        status = "ready" if remote_ready else "error"
    elif provider == "auto":
        effective_provider = "local" if local_available else ("groq" if remote_ready else "local")
        fallback_available = bool(local_available or remote_ready)
        available = bool(local_available or remote_ready)
        if local_ready or remote_ready:
            status = "ready"
        elif local_available or remote_model or remote_api_key:
            status = "configured"
        else:
            status = "error"
    else:
        effective_provider = "local" if local_available else ("groq" if remote_ready else "local")
        fallback_available = bool(local_available or remote_ready)
        available = bool(local_available or remote_ready)
        if local_ready or remote_ready:
            status = "ready"
        elif local_available or remote_model or remote_api_key:
            status = "configured"
        else:
            status = "error"

    active_model = remote_model if provider == "groq" else (remote_model if effective_provider == "groq" and remote_model else MODEL_PATH)
    return {
        "model_path": MODEL_PATH,
        "model": active_model,
        "model_exists": model_exists,
        "provider": provider,
        "effective_provider": effective_provider,
        "remote_model": remote_model,
        "remote_base_url": remote_base_url,
        "remote_ready": remote_ready,
        "fallback_available": fallback_available,
        "ctx": AEGIS_LLAMA_CTX,
        "threads": AEGIS_LLAMA_THREADS,
        "gpu_layers": AEGIS_N_GPU_LAYERS,
        "batch": AEGIS_LLAMA_BATCH,
        "max_new_tokens": MAX_NEW_TOKENS,
        "loaded": _llama is not None,
        "available": available,
        "import_error": _llama_import_error,
        "status": status,
    }


# ============================================================
# MODEL LOADER
# ============================================================

def _get_llama() -> Any:
    global _llama

    if _llama is not None:
        return _llama

    llama_class = _get_llama_class()
    if llama_class is None:
        detail = _llama_import_error or "llama-cpp-python is not installed."
        raise RuntimeError(detail)

    with _llama_lock:
        if _llama is not None:
            return _llama

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"GGUF model not found at {MODEL_PATH}")

        logger.info("[llm_offload] Loading GGUF model from %s", MODEL_PATH)
        logger.info(
            "[llm_offload] ctx=%s threads=%s gpu_layers=%s batch=%s",
            AEGIS_LLAMA_CTX,
            AEGIS_LLAMA_THREADS,
            AEGIS_N_GPU_LAYERS,
            AEGIS_LLAMA_BATCH,
        )

        _llama = llama_class(
            model_path=MODEL_PATH,
            n_ctx=AEGIS_LLAMA_CTX,
            n_threads=AEGIS_LLAMA_THREADS,
            n_gpu_layers=AEGIS_N_GPU_LAYERS,
            n_batch=AEGIS_LLAMA_BATCH,
            verbose=False,
        )

        logger.info("[llm_offload] Model loaded successfully.")
        return _llama


# ============================================================
# PROMPT FORMAT FOR WIZARDCODER
# ============================================================

def _format_wizardcoder(messages: List[Dict[str, str]]) -> str:
    """
    IMPORTANT FIX:
    Your old version added "User:" / "Assistant:" prefixes.
    That makes WizardCoder continue as a script and echo the chat.

    So here we:
    - Merge system into SYS
    - Append other messages as plain text (no role labels)
    - Add a small rule: "reply as assistant only"
    """
    system_parts: List[str] = []
    convo_parts: List[str] = []

    for m in messages:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue

        if role == "system":
            system_parts.append(content)
        else:
            convo_parts.append(content)

    system_text = "\n".join(system_parts).strip() or "You are a helpful AI assistant."
    convo_text = "\n\n".join(convo_parts).strip()

    system_text = (
        system_text
        + "\n\n"
        + "Rules: Reply as the assistant only. Do not include 'User:' or 'Assistant:' labels."
    )

    return (
        "[INST] <<SYS>>\n"
        f"{system_text}\n"
        "<</SYS>>\n\n"
        f"{convo_text}\n"
        "[/INST]\n"
    )


def _extract_text(result: Any) -> str:
    try:
        if isinstance(result, dict):
            choices = result.get("choices") or []
            if choices and isinstance(choices, list) and isinstance(choices[0], dict):
                return str(choices[0].get("text") or "").strip()
    except Exception:
        pass
    return ""


def _postprocess(text: str) -> str:
    if not text:
        return ""
    text = _PREFIX_STRIP_RE.sub("", text)
    return text.strip()

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
            "local model is busy",
            "couldn't generate a response",
            "empty response",
        )
    )


def _looks_like_remote_failure(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    return any(
        frag in lowered
        for frag in (
            "groq backend is not configured",
            "groq backend failed",
            "groq request failed",
            "groq http error",
            "groq response was empty",
            "groq response missing",
        )
    )


def _normalize_provider_choice(value: Optional[str]) -> Optional[str]:
    choice = str(value or "").strip().lower()
    if choice in {"local", "groq", "auto"}:
        return choice
    return None


def _call_groq_chat(
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.3,
    top_p: float = 0.95,
    stop: Optional[List[str]] = None,
) -> str:
    api_key = _remote_api_key()
    model = _remote_model_name()
    if not api_key:
        return "Groq backend is not configured (AEGIS_GROQ_API_KEY or GROQ_API_KEY is missing)."
    if not model:
        return "Groq backend is not configured (AEGIS_GROQ_MODEL is missing)."

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if stop:
        payload["stop"] = stop

    url = f"{_remote_base_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _remote_user_agent(),
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=_remote_timeout_seconds(),
        )
        raw = resp.text
        resp.raise_for_status()
    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)
        body = ""
        code = getattr(response, "status_code", None) or getattr(resp, "status_code", "?")
        if response is not None:
            body = getattr(response, "text", "") or ""
        elif "resp" in locals():
            body = getattr(resp, "text", "") or ""
        return f"Groq HTTP error {code}: {body or exc}"
    except requests.RequestException as exc:
        logger.exception("Groq request failed: %s", exc)
        return f"Groq request failed: {exc}"

    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Groq returned non-JSON response: %s", exc)
        return f"Groq returned non-JSON response: {raw[:240]}"

    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return "Groq response missing choices."

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") or {}
    if isinstance(message, dict):
        text = str(message.get("content") or "").strip()
    else:
        text = ""
    if not text:
        return "Groq response was empty."
    return _postprocess(text)


# ============================================================
# Default profile: safer for mid-range, CPU-first. Use FAST_MODE=1 for even lighter settings.
AEGIS_LLAMA_CTX = _get_int_env("AEGIS_LLAMA_CTX",3048, fast_default=1536)
AEGIS_LLAMA_THREADS = _get_int_env("AEGIS_LLAMA_THREADS", 16, fast_default=4)
AEGIS_N_GPU_LAYERS = _get_int_env("AEGIS_N_GPU_LAYERS", 32, fast_default=0)
AEGIS_LLAMA_BATCH = _get_int_env("AEGIS_LLAMA_BATCH", 512, fast_default=128)
MAX_NEW_TOKENS = _get_int_env("AEGIS_MAX_NEW_TOKENS", 1800, fast_default=256)
# Hard timeout is disabled by default for llama.cpp safety.
# A timed-out worker cannot be safely cancelled and may keep generating in the
# background, which risks concurrent calls and GGML assertions.
MAX_CALL_SECONDS = _get_float_env("LLM_MAX_CALL_SECONDS", 0.0, fast_default=0.0)
AEGIS_FAST_MODE = FAST_MODE
AEGIS_LLM_CONCURRENCY = LLM_CONCURRENCY
AEGIS_LLM_QUEUE_WAIT_SECONDS = LLM_QUEUE_WAIT_SECONDS
AEGIS_LLM_STALL_BUSY_AFTER_SECONDS = LLM_STALL_BUSY_AFTER_SECONDS

# Single shared llama instance
_llama: Optional[Any] = None
_llama_lock = threading.Lock()
_llama_infer_lock = threading.Lock()
_llm_semaphore = threading.Semaphore(LLM_CONCURRENCY) if LLM_CONCURRENCY else None
_timeout_disabled_warned = False
_active_generation_lock = threading.Lock()
_active_generations: Dict[int, float] = {}

# If the model still tries to roleplay a transcript, strip those prefixes.
_PREFIX_STRIP_RE = re.compile(r"(?im)^\s*(aegis|assistant|user)\s*:\s*")
# ============================================================
# LOW-LEVEL CALL
# ============================================================
def _call_llama_chat(
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.3,
    top_p: float = 0.95,
    stop: Optional[List[str]] = None,
) -> str:
    llm = _get_llama()
    prompt = _format_wizardcoder(messages)

    # IMPORTANT FIX:
    # Your old stop list included "[INST]" and "<<SYS>>" which can cause weird early stopping.
    # Keep stops minimal.
    stop_tokens = stop or ["</s>", "<|endoftext|>", "[/INST]"]

    # llama.cpp invocations must stay single-flight per process.
    with _llama_infer_lock:
        result = llm(  # type: ignore[call-arg]
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=1.1,
            stop=stop_tokens,
        )
    return _postprocess(_extract_text(result))


def _oldest_active_generation_age() -> float:
    with _active_generation_lock:
        if not _active_generations:
            return 0.0
        oldest_started = min(_active_generations.values())
    return max(0.0, time.perf_counter() - oldest_started)


def _call_llama_chat_with_timeout(
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.3,
    top_p: float = 0.95,
    stop: Optional[List[str]] = None,
) -> str:
    # Unsafe timeout mode disabled: there is no safe cancellation primitive for
    # an in-flight llama.cpp generation in this process model.
    global _timeout_disabled_warned
    if MAX_CALL_SECONDS and MAX_CALL_SECONDS > 0 and not _timeout_disabled_warned:
        logger.warning(
            "[llm_offload] LLM_MAX_CALL_SECONDS=%.2f requested, but hard timeout is disabled for llama.cpp safety.",
            MAX_CALL_SECONDS,
        )
        _timeout_disabled_warned = True
    return _call_llama_chat(messages, max_tokens, temperature, top_p, stop)


# ============================================================
# PUBLIC ENTRYPOINT
# ============================================================

def _generate_local_response(
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.2,
    top_p: float = 0.95,
) -> str:
    messages = sanitize_messages(messages)

    if _get_llama_class() is None:
        logger.error("llama-cpp-python missing; cannot generate response.")
        return (
            "Local LLM backend is not available (llama-cpp-python missing). "
            "Install dependencies or configure a remote backend."
        )

    acquired = False
    if _llm_semaphore is not None:
        if LLM_STALL_BUSY_AFTER_SECONDS > 0 and _oldest_active_generation_age() >= LLM_STALL_BUSY_AFTER_SECONDS:
            logger.warning(
                "[llm_offload] refusing queued request because an active generation exceeded %.2fs",
                LLM_STALL_BUSY_AFTER_SECONDS,
            )
            return (
                "The local model is busy with a long-running request. "
                "Please retry in a moment."
            )
        wait_started = time.perf_counter()
        if LLM_QUEUE_WAIT_SECONDS > 0:
            acquired = _llm_semaphore.acquire(timeout=LLM_QUEUE_WAIT_SECONDS)
        else:
            _llm_semaphore.acquire()
            acquired = True
        queue_wait_s = time.perf_counter() - wait_started
        if not acquired:
            return (
                "The local model is busy. "
                "Please retry in a moment or reduce concurrent requests."
            )
        if queue_wait_s >= 0.25:
            logger.info("[llm_offload] queued %.2fs before generation slot", queue_wait_s)

    try:
        start_ts = time.perf_counter()
        generation_key = threading.get_ident()
        with _active_generation_lock:
            _active_generations[generation_key] = start_ts

        text = ""
        try:
            text = _call_llama_chat_with_timeout(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[llm_offload] llama.cpp error: %s", exc)
            text = ""

        duration = time.perf_counter() - start_ts

        logger.debug(
            "[llm_offload] generate_response tokens=%s took %.2fs (loaded=%s)",
            max_tokens,
            duration,
            _llama is not None,
        )

        if not text:
            logger.error("[llm_offload] Empty response (retrying once with safer params)")
            try:
                text = _call_llama_chat(
                    messages=messages,
                    max_tokens=min(256, max_tokens),
                    temperature=0.15,
                    top_p=0.9,
                    stop=["</s>", "<|endoftext|>"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("[llm_offload] retry failed: %s", exc)
                text = ""

        if not text:
            logger.error("[llm_offload] Empty response after retry")
            return (
                "I couldn't generate a response (the local model returned empty output). "
                "Try again, or reduce context / lower max tokens."
            )

        return text
    finally:
        with _active_generation_lock:
            _active_generations.pop(threading.get_ident(), None)
        if acquired and _llm_semaphore is not None:
            try:
                _llm_semaphore.release()
            except ValueError:
                pass


def _generate_groq_response(
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.2,
    top_p: float = 0.95,
) -> str:
    messages = sanitize_messages(messages)
    return _call_groq_chat(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
    )


def generate_response(
    messages: List[Dict[str, str]],
    max_new_tokens: Optional[int] = None,
    temperature: float = 0.2,
    top_p: float = 0.95,
    preferred_provider: Optional[str] = None,
    **_: Any,
) -> str:
    """
    Generic LLM entrypoint used by the rest of the app.

    - Sanitizes messages.
    - Caps tokens using MAX_NEW_TOKENS.
    - Routes between local llama.cpp and Groq when configured.
    - On failure, returns a safe placeholder instead of crashing.
    """
    profile_provider = _configured_provider()
    profile_remote_ready = bool(_remote_api_key() and _remote_model_name())
    route_provider = _normalize_provider_choice(preferred_provider) or profile_provider

    if max_new_tokens is None or max_new_tokens <= 0:
        max_tokens = int(MAX_NEW_TOKENS)
    else:
        max_tokens = int(min(max_new_tokens, MAX_NEW_TOKENS))

    temperature = float(temperature if temperature is not None else 0.2)
    top_p = float(top_p if top_p is not None else 0.95)

    messages = sanitize_messages(messages)

    if route_provider == "groq":
        attempt_order = ["groq"]
    elif route_provider == "local":
        attempt_order = ["local", "groq"] if profile_remote_ready else ["local"]
    else:
        attempt_order = ["local", "groq"] if profile_remote_ready else ["local"]

    last_error = ""
    for backend in attempt_order:
        try:
            if backend == "groq":
                text = _generate_groq_response(messages, max_tokens, temperature, top_p)
                if _looks_like_remote_failure(text):
                    last_error = text
                    continue
                return text

            text = _generate_local_response(messages, max_tokens, temperature, top_p)
            if _looks_like_local_failure(text):
                last_error = text
                continue
            return text
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM backend %s failed: %s", backend, exc)
            last_error = str(exc)

    if last_error:
        return last_error
    return (
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

# OpenAI / Anthropic cloud fallback

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
# Helpful env reference:
# # export AEGIS_MODEL_PATH=./models/wizardcoder-python-7b-v1.0.Q5_K_M.gguf
# # export AEGIS_LLAMA_CTX=2048
# # export AEGIS_MAX_NEW_TOKENS=512
# # export AEGIS_N_GPU_LAYERS=0
# # export AEGIS_LLAMA_THREADS=6
# export AEGIS_EMBED_DIM=256
