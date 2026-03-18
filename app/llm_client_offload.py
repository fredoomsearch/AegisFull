from __future__ import annotations

"""
Local llama.cpp (WizardCoder) backend.

- One-time GGUF load (thread-safe)
- Formats OpenAI-style messages into WizardCoder [INST]
- Applies sane defaults (token limits, sanitization)
- Fixes transcript echoing ("User:"/"Assistant:" loops) and empty-output hiccups
"""

import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional 
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


# ============================================================
# STATUS
# ============================================================

def llm_status() -> Dict[str, Any]:
    model_exists = os.path.exists(MODEL_PATH)
    llama_class = _get_llama_class()
    return {
        "model_path": MODEL_PATH,
        "model_exists": model_exists,
        "ctx": AEGIS_LLAMA_CTX,
        "threads": AEGIS_LLAMA_THREADS,
        "gpu_layers": AEGIS_N_GPU_LAYERS,
        "batch": AEGIS_LLAMA_BATCH,
        "max_new_tokens": MAX_NEW_TOKENS,
        "loaded": _llama is not None,
        "available": llama_class is not None,
        "import_error": _llama_import_error,
        "status": "ready" if (llama_class is not None and model_exists and _llama is not None) else (
            "configured" if (llama_class is not None and model_exists) else "error"
        ),
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

def generate_response(
    messages: List[Dict[str, str]],
    max_new_tokens: Optional[int] = None,
    temperature: float = 0.2,
    top_p: float = 0.95,
    **_: Any,
) -> str:
    messages = sanitize_messages(messages)

    if max_new_tokens is None or max_new_tokens <= 0:
        max_tokens = MAX_NEW_TOKENS
    else:
        max_tokens = min(int(max_new_tokens), MAX_NEW_TOKENS)

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
        start = time.perf_counter()
        generation_key = threading.get_ident()
        with _active_generation_lock:
            _active_generations[generation_key] = start

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

        duration = time.perf_counter() - start

        logger.debug(
            "[llm_offload] generate_response tokens=%s took %.2fs (loaded=%s)",
            max_tokens,
            duration,
            _llama is not None,
        )

        # IMPORTANT FIX:
        # Sometimes llama.cpp returns empty text (rare but real).
        # Retry ONCE with safer settings instead of blaming GPU/path.
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


# Helpful env reference:
# # export AEGIS_MODEL_PATH=./models/wizardcoder-python-7b-v1.0.Q5_K_M.gguf
# # export AEGIS_LLAMA_CTX=2048
# # export AEGIS_MAX_NEW_TOKENS=512
# # export AEGIS_N_GPU_LAYERS=0
# # export AEGIS_LLAMA_THREADS=6
# export AEGIS_EMBED_DIM=256
