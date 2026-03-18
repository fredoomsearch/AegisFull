from __future__ import annotations

"""
Embedding helpers for retrieval/service layers.

Why this module exists:
- Provide a single embedding backend abstraction (model or hash fallback).
- Keep embedding readiness and timeout behavior deterministic.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Union
from app.utils.ml_helpers import hash_embed as _hash_embed
from app.utils.threading_helpers import call_with_timeout

logger = logging.getLogger(__name__)

FAST_MODE = os.getenv("AEGIS_FAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

try:  # pragma: no cover
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # noqa: BLE001
    SentenceTransformer = None  # type: ignore


_EMBED_MODEL_RAW = os.getenv("AEGIS_EMBED_MODEL", "").strip()
DEFAULT_MODEL_NAME = _EMBED_MODEL_RAW or (
    "hash" if FAST_MODE else "sentence-transformers/all-MiniLM-L6-v2"
)
FALLBACK_DIM = int(os.getenv("AEGIS_EMBED_DIM", "256"))
EMBED_LOAD_TIMEOUT = float(
    os.getenv("AEGIS_EMBED_LOAD_TIMEOUT", "15" if FAST_MODE else "30")
)
EMBED_ENCODE_TIMEOUT = float(
    os.getenv("AEGIS_EMBED_ENCODE_TIMEOUT", "30" if FAST_MODE else "120")
)
_EMBED_LOCAL_ONLY_RAW = os.getenv("AEGIS_EMBED_LOCAL_ONLY", "").strip().lower()
EMBED_DEVICE = os.getenv("AEGIS_EMBED_DEVICE", "").strip() or None


def _detect_cache_dir() -> str:
    env_dir = os.getenv("AEGIS_EMBED_CACHE_DIR", "").strip()
    if env_dir:
        return env_dir
    candidate = Path(__file__).resolve().parents[2] / "models" / "embeddings"
    if candidate.exists():
        return str(candidate)
    return ""


def _cache_has_model_files(cache_dir: str) -> bool:
    try:
        base = Path(cache_dir)
        if not base.exists():
            return False
        patterns = ("config.json", "modules.json", "*.safetensors", "pytorch_model.bin")
        for pattern in patterns:
            if next(base.rglob(pattern), None):
                return True
    except Exception:
        return False
    return False


EMBED_CACHE_DIR = _detect_cache_dir()
EMBED_LOCAL_ONLY = _EMBED_LOCAL_ONLY_RAW in {"1", "true", "yes"}
if not EMBED_LOCAL_ONLY and not _EMBED_LOCAL_ONLY_RAW and EMBED_CACHE_DIR:
    if _cache_has_model_files(EMBED_CACHE_DIR):
        EMBED_LOCAL_ONLY = True

_model_lock = threading.Lock()
_model: Optional[Union[Any, str]] = None
EMBEDDING_DIM: int | None = None
_LAST_EMBED_MODE = "unloaded"
_LAST_EMBED_ERROR: Optional[str] = None


def _set_status(mode: str, error: Optional[str] = None) -> None:
    global _LAST_EMBED_MODE, _LAST_EMBED_ERROR
    _LAST_EMBED_MODE = mode
    if error:
        _LAST_EMBED_ERROR = error


def _load_model() -> Any:
    global _model, EMBEDDING_DIM
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        if DEFAULT_MODEL_NAME.strip().lower() == "hash":
            EMBEDDING_DIM = FALLBACK_DIM
            _model = "hash"
            _set_status("hash")
            logger.info("Using hashing-only embeddings (AEGIS_EMBED_MODEL=hash).")
            return _model

        if SentenceTransformer is None:
            logger.warning(
                "sentence-transformers not available; using hashing fallback embeddings."
            )
            EMBEDDING_DIM = FALLBACK_DIM
            _model = "hash"
            _set_status("hash", "sentence-transformers not available")
            return _model

        try:
            model = None
            model_kwargs = {}
            if EMBED_CACHE_DIR:
                model_kwargs["cache_folder"] = EMBED_CACHE_DIR
            if EMBED_LOCAL_ONLY:
                model_kwargs["local_files_only"] = True
            if EMBED_DEVICE:
                model_kwargs["device"] = EMBED_DEVICE
            if EMBED_LOAD_TIMEOUT and EMBED_LOAD_TIMEOUT > 0:
                model = _load_sentence_transformer_with_timeout(
                    DEFAULT_MODEL_NAME,
                    EMBED_LOAD_TIMEOUT,
                    model_kwargs,
                )
                if model is None:
                    EMBEDDING_DIM = FALLBACK_DIM
                    _model = "hash"
                    _set_status("hash", "embedding model load timed out")
                    logger.warning(
                        "Embedding model load timed out; using hashing fallback (dim=%s).",
                        EMBEDDING_DIM,
                    )
                    return _model
            else:
                model = SentenceTransformer(DEFAULT_MODEL_NAME, **model_kwargs)
            EMBEDDING_DIM = int(model.get_sentence_embedding_dimension())
            _model = model
            _set_status("model")
            logger.info(
                "Loaded embedding model %s (dim=%s)",
                DEFAULT_MODEL_NAME,
                EMBEDDING_DIM,
            )
            return model
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to load %s; using hashing fallback embedding. %s",
                DEFAULT_MODEL_NAME,
                exc,
            )
            EMBEDDING_DIM = FALLBACK_DIM
            _model = "hash"
            _set_status("hash", str(exc))
            return _model


def _load_sentence_transformer_with_timeout(
    model_name: str,
    timeout_s: float,
    model_kwargs: Optional[dict] = None,
) -> Optional[Any]:
    result = call_with_timeout(
        lambda: SentenceTransformer(model_name, **(model_kwargs or {})),
        timeout_s=timeout_s,
        thread_name="embed-model-load",
        daemon=True,
    )
    if not result.completed:
        logger.warning("Embedding model load timed out after %.1fs.", timeout_s)
        return None
    if result.error is not None:
        raise result.error  # type: ignore[misc]
    return result.value


def _normalize(vec: Sequence[float]) -> List[float]:
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [float(v / norm) for v in vec]


def embed_texts(texts: Iterable[str]) -> List[List[float]]:
    texts_list = [t or "" for t in texts]
    if not texts_list:
        return []

    model = _load_model()
    if isinstance(model, str) and model == "hash":
        dim = EMBEDDING_DIM or FALLBACK_DIM
        _set_status("hash", _LAST_EMBED_ERROR)
        return [_normalize(_hash_embed(t, dim)) for t in texts_list]

    try:
        embeddings = _encode_with_timeout(
            model,
            texts_list,
            EMBED_ENCODE_TIMEOUT,
        )
        if embeddings is None:
            logger.warning("Embedding encode timed out; using hashing fallback.")
            dim = EMBEDDING_DIM or FALLBACK_DIM
            _set_status("hash", "embedding encode timed out")
            return [_normalize(_hash_embed(t, dim)) for t in texts_list]
        _set_status("model")
        return [list(map(float, vec)) for vec in embeddings]
    except Exception as exc:  # noqa: BLE001
        logger.exception("sentence-transformers encode failed; falling back to hashing. %s", exc)
        dim = EMBEDDING_DIM or FALLBACK_DIM
        _set_status("hash", str(exc))
        return [_normalize(_hash_embed(t, dim)) for t in texts_list]


def _encode_with_timeout(
    model: Any,
    texts: List[str],
    timeout_s: float,
) -> Optional[Sequence[Sequence[float]]]:
    if not timeout_s or timeout_s <= 0:
        return model.encode(texts, normalize_embeddings=True)  # type: ignore[arg-type]

    result = call_with_timeout(
        lambda: model.encode(texts, normalize_embeddings=True),  # type: ignore[arg-type]
        timeout_s=timeout_s,
        thread_name="embed-encode",
        daemon=True,
    )
    if not result.completed:
        logger.warning("Embedding encode timed out after %.1fs.", timeout_s)
        return None
    if result.error is not None:
        raise result.error  # type: ignore[misc]
    return result.value


def get_embedding_status(ensure_loaded: bool = False) -> dict:
    if ensure_loaded:
        try:
            _load_model()
        except Exception:
            pass

    loaded = _model is not None
    mode = _LAST_EMBED_MODE
    if isinstance(_model, str) and _model == "hash":
        mode = "hash"
    elif _model is not None:
        mode = "model"

    dim = EMBEDDING_DIM
    if mode == "hash" and not dim:
        dim = FALLBACK_DIM

    return {
        "status": "ok",
        "mode": mode,
        "model": DEFAULT_MODEL_NAME,
        "dim": dim,
        "loaded": loaded,
        "local_only": EMBED_LOCAL_ONLY,
        "cache_dir": EMBED_CACHE_DIR or None,
        "device": EMBED_DEVICE,
        "error": _LAST_EMBED_ERROR,
    }


def prepare_embeddings(sample: str = "ping") -> dict:
    embed_texts([sample])
    return get_embedding_status(ensure_loaded=True)


__all__ = ["EMBEDDING_DIM", "embed_texts", "get_embedding_status", "prepare_embeddings"]
