from __future__ import annotations

"""
Language utilities for AEGIS.

- Safe language detection (es/en) using langdetect if installed.
- Normalization to 'es' or 'en'.
- Small language packs for prompts.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ("es", "en")
_langdetect_detect = None  # lazy-imported callable


def _ensure_langdetect() -> Optional[object]:
    global _langdetect_detect
    if _langdetect_detect is not None:
        return _langdetect_detect
    try:
        from langdetect import detect  # type: ignore
    except Exception:
        _langdetect_detect = None
    else:
        _langdetect_detect = detect
    return _langdetect_detect


def normalize_lang(code: str | None) -> str:
    if not code:
        return "en"
    code = code.strip().lower()
    if code.startswith("es"):
        return "es"
    if code.startswith("en"):
        return "en"
    return "en"


def detect_lang_safe(text: str | None) -> str:
    stripped = (text or "").strip()
    if len(stripped) < 4:
        return "en"

    detect_fn = _ensure_langdetect()
    if detect_fn is None:
        logger.debug("langdetect not available; defaulting to 'en'")
        return "en"

    try:
        detected = detect_fn(stripped)
    except Exception:
        logger.debug("langdetect failed; defaulting to 'en'", exc_info=True)
        return "en"
    return normalize_lang(detected)


def is_spanish(text: str | None) -> bool:
    return detect_lang_safe(text) == "es"


def is_english(text: str | None) -> bool:
    return detect_lang_safe(text) == "en"


def get_language_pack(lang: str | None) -> Dict[str, str]:
    lang_norm = normalize_lang(lang)
    if lang_norm == "es":
        return {
            "system": (
                "Nunca inventes hechos. Usa solo datos que puedas justificar con el contexto, "
                "recuperación o resultados web. Si las fuentes no tienen fecha, dilo explícitamente. "
                "Responde en español si el usuario escribe en español."
            ),
            "mode_web": (
                "Usando SOLO los resultados web proporcionados, responde la consulta del usuario. "
                "Si algo no aparece en las fuentes, indica que no hay información suficiente."
            ),
            "short_label": "ES",
        }
    return {
        "system": (
            "Never invent facts. Use only information you can justify via conversation context, "
            "retrieval or web results. If sources have no date, say so explicitly. "
            "Reply in English when the user writes in English."
        ),
        "mode_web": (
            "Using ONLY the provided web results, answer the user's query. "
            "If something is not present in the sources, state that information is insufficient."
        ),
        "short_label": "EN",
    }
