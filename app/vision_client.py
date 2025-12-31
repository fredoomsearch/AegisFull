# app/vision_client.py
from __future__ import annotations

import io
import logging
from typing import Literal, Optional

from PIL import Image, ImageOps, UnidentifiedImageError
import pytesseract

logger = logging.getLogger(__name__)

SupportedLang = Literal["es", "en"]
SupportedMode = Literal["text", "code"]


def _get_ocr_lang(lang: SupportedLang) -> str:
    """
    Decide qué modelos de idioma usar en Tesseract.

    Mantiene el comportamiento original (spa+eng siempre) para no
    romper nada, pero si mañana quieres refinarlo por idioma, lo haces aquí.
    """
    return "spa+eng"


def _preprocess_image(img: Image.Image, mode: SupportedMode = "text") -> Image.Image:
    """
    Preprocesado ligero para mejorar OCR:
    - Escala mínima (900px de ancho).
    - Escala de grises + autocontrast.
    - Umbral binario simple (más fuerte para modo code).
    """
    try:
        if img.mode != "RGB":
            img = img.convert("RGB")
        # upscale if very small
        w, h = img.size
        if w < 900:
            scale = 900 / float(w)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        gray = img.convert("L")
        gray = ImageOps.autocontrast(gray)

        # basic threshold
        thresh = 150 if mode == "text" else 170
        bw = gray.point(lambda x: 255 if x > thresh else 0, mode="1")
        return bw
    except Exception as exc:  # noqa: BLE001
        logger.warning("vision_client: fallo en preprocesado OCR: %s", exc)
        return img


def analyze_image_bytes(
    image_bytes: bytes,
    lang: SupportedLang = "es",
    *,
    mode: SupportedMode = "text",
    psm: Optional[int] = None,
    oem: Optional[int] = None,
) -> str:
    """
    Análisis local sin API key.

    - Usa Tesseract para extraer texto (OCR) de la imagen.
    - Devuelve un texto descriptivo que luego el LLM puede usar como contexto.
    - No llama a ningún servicio externo.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except UnidentifiedImageError as exc:
        logger.warning("vision_client: imagen no identificable: %s", exc)
        return (
            "⚠️ No pude abrir la imagen (formato no válido o archivo dañado). "
            f"Detalle interno: {exc}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("vision_client: fallo abriendo la imagen: %s", exc)
        return (
            "⚠️ No pude abrir la imagen (formato no válido o archivo dañado). "
            f"Detalle interno: {exc}"
        )

    ocr_lang = _get_ocr_lang(lang)
    img = _preprocess_image(img, mode=mode)

    cfg_parts = [f"--psm {psm if psm is not None else 6}", f"--oem {oem if oem is not None else 1}"]
    if mode == "code":
        cfg_parts.append("-c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_./:-")
    config = " ".join(cfg_parts)

    try:
        raw_text = pytesseract.image_to_string(img, lang=ocr_lang, config=config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("vision_client: fallo en OCR: %s", exc)
        return (
            "⚠️ Fallo al intentar leer el texto de la imagen con OCR. "
            f"Detalle interno: {exc}"
        )

    raw_text = (raw_text or "").strip()
    if not raw_text:
        if lang == "es":
            return (
                "Analicé la imagen con OCR, pero no pude encontrar texto legible.\n\n"
                "Si es un error del sistema o una notificación, intenta hacer un "
                "zoom o una captura más cercana al mensaje, o describe el problema "
                "con tus propias palabras."
            )
        else:
            return (
                "I ran OCR on the image but couldn't find any readable text.\n\n"
                "If this is a system error or notification, try a closer screenshot "
                "or describe the issue in your own words."
            )

    if lang == "es":
        return (
            "He extraído el siguiente texto de la imagen (usando OCR local, "
            "sin servicios externos):\n\n"
            f"```text\n{raw_text}\n```\n\n"
            "Puedes pedirme que te explique este mensaje, que te ayude a "
            "solucionar el error, o que lo reescriba de forma más clara."
        )
    else:
        return (
            "I extracted the following text from the image (using local OCR, "
            "no external services):\n\n"
            f"```text\n{raw_text}\n```\n\n"
            "You can ask me to explain this message, help troubleshoot the error, "
            "or rewrite it more clearly."
        )
