# app/vision_client.py
from __future__ import annotations

import io
import logging
from typing import Literal, Optional

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError
import pytesseract

logger = logging.getLogger(__name__)

SupportedLang = Literal["es", "en"]
SupportedMode = Literal["text", "code", "scene", "ocr"]


def _get_ocr_lang(lang: SupportedLang) -> str:
    """
    Decide qué modelos de idioma usar en Tesseract.

    Mantiene el comportamiento original (spa+eng siempre) para no
    romper nada, pero si mañana quieres refinarlo por idioma, lo haces aquí.
    """
    return "spa+eng"


def _normalize_mode(mode: str | None) -> SupportedMode:
    value = str(mode or "text").strip().lower()
    if value == "ocr":
        return "text"
    if value in {"text", "code", "scene"}:
        return value  # type: ignore[return-value]
    return "text"


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
        m = _normalize_mode(mode)
        thresh = 150 if m in {"text", "scene"} else 170
        bw = gray.point(lambda x: 255 if x > thresh else 0, mode="1")
        return bw
    except Exception as exc:  # noqa: BLE001
        logger.warning("vision_client: fallo en preprocesado OCR: %s", exc)
        return img


def _describe_image_frame(img: Image.Image, lang: SupportedLang) -> str:
    try:
        w, h = img.size
        orientation = (
            "horizontal" if w > h else
            "vertical" if h > w else
            "square"
        )
        gray = img.convert("L")
        stats = ImageStat.Stat(gray)
        mean = float(stats.mean[0] if stats.mean else 0.0)
        stddev = float(stats.stddev[0] if stats.stddev else 0.0)

        if mean < 80:
            brightness = "dark"
        elif mean > 180:
            brightness = "bright"
        else:
            brightness = "balanced"

        if stddev < 28:
            contrast = "low"
        elif stddev > 62:
            contrast = "high"
        else:
            contrast = "medium"

        sample = img.convert("RGB").resize((128, 128), Image.LANCZOS)
        palette_img = sample.quantize(colors=5).convert("RGB")
        colors = sorted(palette_img.getcolors(128 * 128) or [], reverse=True)
        palette = ", ".join(
            f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            for _, rgb in colors[:3]
        ) or "n/a"

        if lang == "es":
            return (
                "Análisis visual local (sin servicios externos):\n"
                f"- Resolución: {w}x{h} ({orientation}).\n"
                f"- Iluminación estimada: {brightness}.\n"
                f"- Contraste estimado: {contrast}.\n"
                f"- Colores dominantes: {palette}."
            )

        return (
            "Local visual analysis (no external services):\n"
            f"- Resolution: {w}x{h} ({orientation}).\n"
            f"- Estimated lighting: {brightness}.\n"
            f"- Estimated contrast: {contrast}.\n"
            f"- Dominant colors: {palette}."
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("vision_client: frame description failed: %s", exc)
        if lang == "es":
            return "Análisis visual local disponible, pero no pude extraer métricas de imagen."
        return "Local visual analysis is available, but I could not extract image metrics."


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
    img_rgb: Image.Image | None = None
    processed_img: Image.Image | None = None
    try:
        try:
            with io.BytesIO(image_bytes) as buf:
                with Image.open(buf) as opened:
                    img_rgb = opened.convert("RGB")
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

        mode_norm = _normalize_mode(mode)
        ocr_lang = _get_ocr_lang(lang)
        processed_img = _preprocess_image(img_rgb, mode=mode_norm)

        cfg_parts = [f"--psm {psm if psm is not None else 6}", f"--oem {oem if oem is not None else 1}"]
        if mode_norm == "code":
            cfg_parts.append("-c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_./:-")
        config = " ".join(cfg_parts)

        try:
            raw_text = pytesseract.image_to_string(processed_img, lang=ocr_lang, config=config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("vision_client: fallo en OCR: %s", exc)
            return (
                "⚠️ Fallo al intentar leer el texto de la imagen con OCR. "
                f"Detalle interno: {exc}"
            )

        raw_text = (raw_text or "").strip()

        if mode_norm == "scene":
            visual = _describe_image_frame(img_rgb, lang)
            if raw_text:
                if lang == "es":
                    return (
                        f"{visual}\n\n"
                        "Texto detectado (OCR local):\n\n"
                        f"```text\n{raw_text}\n```\n\n"
                        "Puedo ayudarte a interpretar lo visual, resumir el texto o detectar errores en una captura."
                    )
                return (
                    f"{visual}\n\n"
                    "Detected text (local OCR):\n\n"
                    f"```text\n{raw_text}\n```\n\n"
                    "I can help interpret the visual content, summarize the text, or troubleshoot screenshot errors."
                )
            if lang == "es":
                return (
                    f"{visual}\n\n"
                    "No encontré texto legible en la imagen. Si quieres OCR de texto fino, prueba con una captura más cercana."
                )
            return (
                f"{visual}\n\n"
                "I could not find readable text in this image. For fine OCR, try a closer screenshot."
            )

        if not raw_text:
            if lang == "es":
                return (
                    "Analicé la imagen con OCR, pero no pude encontrar texto legible.\n\n"
                    "Si es un error del sistema o una notificación, intenta hacer un "
                    "zoom o una captura más cercana al mensaje, o describe el problema "
                    "con tus propias palabras."
                )
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
        return (
            "I extracted the following text from the image (using local OCR, "
            "no external services):\n\n"
            f"```text\n{raw_text}\n```\n\n"
            "You can ask me to explain this message, help troubleshoot the error, "
            "or rewrite it more clearly."
        )
    finally:
        if processed_img is not None and processed_img is not img_rgb:
            processed_img.close()
        if img_rgb is not None:
            img_rgb.close()
