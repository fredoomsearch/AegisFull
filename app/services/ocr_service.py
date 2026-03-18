from __future__ import annotations

"""
OCR service for AEGIS.

Responsibilities:
  - Extract text from image bytes (screenshots, photos, scans).
  - Optionally extract text from PDF files by rendering pages to images.

Why this module exists:
  - Provide deterministic OCR utilities for image/reference workflows.
"""

import io
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    from PIL import Image  # type: ignore
except Exception:  # noqa: BLE001
    Image = None  # type: ignore[assignment]

try:  # pragma: no cover
    import pytesseract  # type: ignore
except Exception:  # noqa: BLE001
    pytesseract = None  # type: ignore[assignment]

try:  # pragma: no cover
    from pdf2image import convert_from_bytes  # type: ignore
except Exception:  # noqa: BLE001
    convert_from_bytes = None  # type: ignore[assignment]


class OcrError(RuntimeError):
    """Generic error for OCR-related failures."""


def _ensure_image_backend() -> None:
    if Image is None or pytesseract is None:
        raise OcrError(
            "OCR backend not available. Install Pillow and pytesseract, e.g.: "
            "`pip install pillow pytesseract` and configure Tesseract."
        )


def _ensure_pdf_backend() -> None:
    if convert_from_bytes is None:
        raise OcrError(
            "PDF OCR requires `pdf2image` and a Poppler installation. "
            "Install via `pip install pdf2image` and make sure `pdftoppm` is available."
        )
    _ensure_image_backend()


def _normalize_lang_hint(lang: str | None) -> str:
    lang = (lang or "spa+eng").strip()
    return lang or "spa+eng"


def ocr_image_bytes(image_bytes: bytes, lang: str = "spa+eng") -> str:
    _ensure_image_backend()
    if not image_bytes:
        return ""

    lang_hint = _normalize_lang_hint(lang)
    img = None
    try:
        with io.BytesIO(image_bytes) as buf:
            with Image.open(buf) as opened:  # type: ignore[arg-type]
                img = opened.convert("RGB")
        text = pytesseract.image_to_string(img, lang=lang_hint)  # type: ignore[call-arg]
        return (text or "").strip()
    except OcrError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("ocr_image_bytes failed: %s", exc)
        raise OcrError(f"OCR failed on image bytes: {exc}") from exc
    finally:
        if img is not None:
            img.close()


def ocr_file(path: str | Path, lang: str = "spa+eng") -> str:
    p = Path(path)
    if not p.exists():
        raise OcrError(f"OCR file not found: {p}")

    suffix = p.suffix.lower()
    lang_hint = _normalize_lang_hint(lang)

    if suffix == ".pdf":
        pdf_bytes = p.read_bytes()
        return ocr_pdf_bytes(pdf_bytes, lang=lang_hint)

    _ensure_image_backend()
    img = None
    try:
        with Image.open(p) as opened:  # type: ignore[arg-type]
            img = opened.convert("RGB")
        text = pytesseract.image_to_string(img, lang=lang_hint)  # type: ignore[call-arg]
        return (text or "").strip()
    except OcrError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("ocr_file failed for %s: %s", p, exc)
        raise OcrError(f"OCR failed for file {p}: {exc}") from exc
    finally:
        if img is not None:
            img.close()


def ocr_pdf_bytes(
    pdf_bytes: bytes,
    lang: str = "spa+eng",
    max_pages: Optional[int] = 5,
) -> str:
    _ensure_pdf_backend()
    if not pdf_bytes:
        return ""

    lang_hint = _normalize_lang_hint(lang)
    try:
        pages = convert_from_bytes(pdf_bytes)  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to render PDF to images: %s", exc)
        raise OcrError(f"Failed to render PDF for OCR: {exc}") from exc

    if max_pages is not None and max_pages > 0:
        pages = pages[:max_pages]

    texts: List[str] = []
    for idx, img in enumerate(pages):
        img_rgb = None
        try:
            img_rgb = img.convert("RGB")
            page_text = pytesseract.image_to_string(img_rgb, lang=lang_hint)  # type: ignore[call-arg]
            page_text = (page_text or "").strip()
            if page_text:
                texts.append(page_text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("OCR for PDF page %d failed: %s", idx, exc)
        finally:
            if img_rgb is not None:
                img_rgb.close()
            try:
                img.close()
            except Exception:
                logger.debug("Failed to close OCR PDF page image", exc_info=True)

    return "\n\n".join(t for t in texts if t)
