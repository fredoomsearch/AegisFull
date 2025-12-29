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

try:  # pragma: no cover
    from llama_cpp import Llama  # type: ignore
except Exception:  # noqa: BLE001
    Llama = None  # type: ignore

from app.tools import sanitize_messages

logger = logging.getLogger(__name__)

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


# ============================================================
# STATUS
# ============================================================

def llm_status() -> Dict[str, Any]:
    return {
        "model_path": MODEL_PATH,
        "ctx": AEGIS_LLAMA_CTX,
        "threads": AEGIS_LLAMA_THREADS,
        "gpu_layers": AEGIS_N_GPU_LAYERS,
        "batch": AEGIS_LLAMA_BATCH,
        "max_new_tokens": MAX_NEW_TOKENS,
        "loaded": _llama is not None,
        "available": Llama is not None,
    }


# ============================================================
# MODEL LOADER
# ============================================================

def _get_llama() -> Any:
    global _llama

    if _llama is not None:
        return _llama

    if Llama is None:
        raise RuntimeError("llama-cpp-python is not installed.")

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

        _llama = Llama(
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
AEGIS_LLAMA_THREADS = _get_int_env("AEGIS_LLAMA_THREADS", 10, fast_default=4)
AEGIS_N_GPU_LAYERS = _get_int_env("AEGIS_N_GPU_LAYERS", 32, fast_default=0)
AEGIS_LLAMA_BATCH = _get_int_env("AEGIS_LLAMA_BATCH", 612, fast_default=128)
MAX_NEW_TOKENS = _get_int_env("AEGIS_MAX_NEW_TOKENS", 1400, fast_default=256)
# Disable backend timeouts by default; set LLM_MAX_CALL_SECONDS>0 to cap.
MAX_CALL_SECONDS = _get_float_env("LLM_MAX_CALL_SECONDS", 0.0, fast_default=0.0)
AEGIS_FAST_MODE = FAST_MODE
AEGIS_LLM_CONCURRENCY = LLM_CONCURRENCY
_TIMEOUT_SENTINEL = "__AEGIS_LLM_TIMEOUT__"

# Single shared llama instance
_llama: Optional[Any] = None
_llama_lock = threading.Lock()
_llm_semaphore = threading.Semaphore(LLM_CONCURRENCY) if LLM_CONCURRENCY else None

# If the model still tries to roleplay a transcript, strip those prefixes.
_PREFIX_STRIP_RE = re.compile(r"(?im)^\s*(aegis|assistant|user)\s*:\s*")
# ============================================================
# LOW-LEVEL CALL
# ============================================================



# This function is the low-level bridge between our FastAPI app and the local WizardCoder model. It takes the already-sanitized conversation (messages), runs them through _format_wizardcoder to build the [INST] … [/INST] prompt, and then calls the shared llama_cpp.Llama instance with the desired sampling settings (max_tokens, temperature, top_p, plus optional stop tokens). Any tuning of inference behavior—stricter temperature, different stop sequences, or logging—happens here before the generated text is returned upstream.


# En esa llamada intervienen varios “números” con funciones distintas:

# max_tokens

# Máximo de tokens nuevos que puede generar el modelo en esa respuesta. Cuanto más alto, más larga (y lenta) la salida; reducirlo evita timeouts. Ej.: 1500/2000.
# temperature (0.2)

# Controla qué tan “creativa” es la respuesta. Valores bajos (0.1–0.3) obligan al modelo a elegir tokens de mayor probabilidad, volviéndose muy determinista y técnico (ideal para código). Temperaturas altas (>0.7) lo hacen más variado pero también menos preciso.
# top_p (0.95)

# “Nucleus sampling”: el modelo sólo considera tokens cuya suma de probabilidades alcance el 95 %. Bajarlo (0.8) lo vuelve más conservador; subirlo lo hace más libre.
# stop tokens

# Lista de secuencias donde se corta la generación (por defecto ["</s>", "<|endoftext|>", "[/INST]"]). Garantizan que no siga escribiendo cuando termina el bloque de instrucción.
# AEGIS_LLAMA_CTX (3072)

# Longitud máxima del prompt (contexto) que el modelo puede ver de una vez. Afecta memoria y la capacidad de recordar mensajes largos.
# AEGIS_LLAMA_THREADS (8)

# Número de hilos CPU usados por llama.cpp. Súbelo si tienes más núcleos para acelerar la inferencia.
# AEGIS_N_GPU_LAYERS (32)

# Cuántas capas del modelo se ejecutan en GPU. Cuantas más capas en GPU, más rápidez (si tienes VRAM suficiente). Valores altos sólo aplican si cuentas con GPU compatible.
# AEGIS_LLAMA_BATCH (512)
# En esa llamada intervienen varios “números” con funciones distintas:

# max_tokens

# Máximo de tokens nuevos que puede generar el modelo en esa respuesta. Cuanto más alto, más larga (y lenta) la salida; reducirlo evita timeouts. Ej.: 1500/2000.
# temperature (0.2)

# Controla qué tan “creativa” es la respuesta. Valores bajos (0.1–0.3) obligan al modelo a elegir tokens de mayor probabilidad, volviéndose muy determinista y técnico (ideal para código). Temperaturas altas (>0.7) lo hacen más variado pero también menos preciso.
# top_p (0.95)

# “Nucleus sampling”: el modelo sólo considera tokens cuya suma de probabilidades alcance el 95 %. Bajarlo (0.8) lo vuelve más conservador; subirlo lo hace más libre.
# stop tokens

# Lista de secuencias donde se corta la generación (por defecto ["</s>", "<|endoftext|>", "[/INST]"]). Garantizan que no siga escribiendo cuando termina el bloque de instrucción.
# AEGIS_LLAMA_CTX (3072)

# Longitud máxima del prompt (contexto) que el modelo puede ver de una vez. Afecta memoria y la capacidad de recordar mensajes largos.
# AEGIS_LLAMA_THREADS (8)

# Número de hilos CPU usados por llama.cpp. Súbelo si tienes más núcleos para acelerar la inferencia.
# AEGIS_N_GPU_LAYERS (32)

# Cuántas capas del modelo se ejecutan en GPU. Cuantas más capas en GPU, más rápidez (si tienes VRAM suficiente). Valores altos sólo aplican si cuentas con GPU compatible.
# AEGIS_LLAMA_BATCH (512)

# Tamaño de lote interno para procesar tokens. Lotes grandes mejoran throughput pero consumen más RAM.
# Todos esos parámetros se combinan: primero se arma el prompt (ya “limpio”), luego _call_llama_chat lo envía a llama.cpp con max_tokens/temperature/top_p/stop. Mientras tanto, los env vars (CTX, THREADS, GPU_LAYERS, BATCH) determinan cómo está configurado el modelo residente en memoria, influyendo en velocidad y coste de cada llamada.

# Tamaño de lote interno para procesar tokens. Lotes grandes mejoran throughput pero consumen más RAM.
# Todos esos parámetros se combinan: primero se arma el prompt (ya “limpio”), luego _call_llama_chat lo envía a llama.cpp con max_tokens/temperature/top_p/stop. Mientras tanto, los env vars (CTX, THREADS, GPU_LAYERS, BATCH) determinan cómo está configurado el modelo residente en memoria, influyendo en velocidad y coste de cada llamada.

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

    result = llm(  # type: ignore[call-arg]
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        repeat_penalty=1.1,
        stop=stop_tokens,
    )
    return _postprocess(_extract_text(result))


def _call_llama_chat_with_timeout(
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.3,
    top_p: float = 0.95,
    stop: Optional[List[str]] = None,
) -> str:
    # No backend timeout when MAX_CALL_SECONDS<=0.
    if not MAX_CALL_SECONDS or MAX_CALL_SECONDS <= 0:
        return _call_llama_chat(messages, max_tokens, temperature, top_p, stop)

    result: dict[str, object] = {"text": "", "error": None}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["text"] = _call_llama_chat(messages, max_tokens, temperature, top_p, stop)
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    if not done.wait(MAX_CALL_SECONDS):
        logger.warning(
            "[llm_offload] hard timeout after %.2fs (limit=%.2fs)",
            MAX_CALL_SECONDS,
            MAX_CALL_SECONDS,
        )
        return _TIMEOUT_SENTINEL
    if result["error"] is not None:
        raise result["error"]  # type: ignore[misc]
    return str(result.get("text") or "")


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

    if Llama is None:
        logger.error("llama-cpp-python missing; cannot generate response.")
        return (
            "Local LLM backend is not available (llama-cpp-python missing). "
            "Install dependencies or configure a remote backend."
        )

    acquired = False
    if _llm_semaphore is not None:
        if not _llm_semaphore.acquire(blocking=False):
            return (
                "The local model is busy. "
                "Please retry in a moment or reduce concurrent requests."
            )
        acquired = True

    try:
        start = time.perf_counter()

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

        if text == _TIMEOUT_SENTINEL:
            return (
                "The local model took too long to respond. "
                "Try again or reduce max tokens / context size."
            )

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
