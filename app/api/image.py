from __future__ import annotations

"""
Image generation and reference-analysis API.

Why this module exists:
- Bridge AEGIS with local image backends over HTTP.
- Provide explicit fallback behavior when backend is degraded.
- Support OCR-assisted reference-to-image workflows.
"""
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import require_files_api_key
from app.services.image_backend_helpers import (
    extract_checkpoint_choices,
    normalize_checkpoint_values,
    normalize_prompt_url,
    split_prompt_url,
)
from app.vision_client import analyze_image_bytes

logger = logging.getLogger(__name__)

# Pillow solo se usa para fallback textual si falla el backend de imágenes
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    Image = None  # type: ignore


router = APIRouter(prefix="/image", tags=["image"], dependencies=[Depends(require_files_api_key)])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = Path("data/images").resolve()
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = IMAGES_DIR / "log.jsonl"

# Config del backend de difusión local (ComfyUI/Invoke/otro).


GEN_URL = normalize_prompt_url(os.getenv("AEGIS_IMAGE_ENDPOINT", "http://127.0.0.1:8188/prompt"))
GEN_TIMEOUT = float(os.getenv("AEGIS_IMAGE_TIMEOUT", "60"))
GEN_PROVIDER = os.getenv("AEGIS_IMAGE_PROVIDER", "sd-local")
MAX_REFERENCE_BYTES = int(os.getenv("AEGIS_IMAGE_MAX_REFERENCE_BYTES", str(10 * 1024 * 1024)))
DEFAULT_IMAGE_CKPT = "sd_turbo.safetensors"


class ImageRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg: float = 7.0
    seed: Optional[int] = None
    provider: str = GEN_PROVIDER


def _merge_reference_prompt(prompt: str, ocr_text: str, lang: str) -> str:
    base = str(prompt or "").strip()
    extracted = str(ocr_text or "").strip()
    if not extracted:
        return base
    if len(extracted) > 1200:
        extracted = extracted[:1197].rstrip() + "..."
    marker = "[Contexto OCR de imagen de referencia]" if str(lang or "en").lower().startswith("es") else "[Reference image OCR context]"
    if not base:
        return f"{marker}\n{extracted}".strip()
    return f"{base}\n\n{marker}\n{extracted}".strip()


def _configured_checkpoint() -> str:
    raw = (os.getenv("AEGIS_IMAGE_CKPT", DEFAULT_IMAGE_CKPT) or "").strip()
    return raw or DEFAULT_IMAGE_CKPT


def _resolve_endpoint_and_base() -> tuple[str, str]:
    return split_prompt_url(os.getenv("AEGIS_IMAGE_ENDPOINT", GEN_URL))


def _normalize_checkpoint_values(raw: Any) -> list[str]:
    return normalize_checkpoint_values(raw)


def _extract_checkpoint_choices(payload: Any) -> list[str]:
    return extract_checkpoint_choices(payload)


def _fetch_backend_checkpoints(base_url: str) -> list[str]:
    if not base_url:
        return []
    info_url = f"{base_url.rstrip('/')}/object_info/CheckpointLoaderSimple"
    resp = requests.get(info_url, timeout=min(max(GEN_TIMEOUT, 1.0), 4.0))
    resp.raise_for_status()
    payload = resp.json() if resp.content else {}
    return _extract_checkpoint_choices(payload)


def _resolve_checkpoint(base_url: str) -> tuple[str, str, list[str], Optional[str]]:
    configured = _configured_checkpoint()
    try:
        available = _fetch_backend_checkpoints(base_url)
    except Exception as exc:  # noqa: BLE001
        return configured, configured, [], str(exc)

    if not available:
        return configured, configured, [], None

    if configured in available:
        return configured, configured, available, None

    selected = available[0]
    logger.warning(
        "Configured image checkpoint '%s' is unavailable; using '%s' from backend list.",
        configured,
        selected,
    )
    return selected, configured, available, None


def _save_log(payload: Dict[str, Any]) -> None:
    """Append best-effort image event logs for recent/status views."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _public_path(path: Path) -> str:
    """
    Return a stable app-relative path (for `/data/...` static serving)
    even if the process cwd changes.
    """
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        try:
            return f"data/images/{path.name}"
        except Exception:
            return str(path)


def _render_placeholder(prompt: str, width: int, height: int, seed: Optional[int]) -> Path:
    """Create deterministic local placeholder output when backend is unavailable."""
    fname = f"{uuid.uuid4().hex}.png"
    path = IMAGES_DIR / fname
    if Image is None:
        path = path.with_suffix(".txt")
        path.write_text(f"[placeholder image]\nprompt: {prompt}", encoding="utf-8")
        return path
    img = Image.new("RGB", (width, height), color=(18, 24, 38))
    draw = ImageDraw.Draw(img)
    txt = (prompt or "(empty)")[:240]
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw.text((10, 10), txt, fill=(120, 225, 255), font=font, spacing=4)
    draw.text((10, height - 30), f"seed:{seed or 'rnd'}", fill=(180, 180, 180), font=font)
    img.save(path)
    return path


def _call_local_sd(req: ImageRequest, checkpoint_name: Optional[str] = None) -> tuple[Path, bool, Optional[str]]:
    """
    Llama a ComfyUI (API /prompt) con un grafo mínimo text2img y recupera
    la primera imagen generada vía /history/<prompt_id> + /view.
    Si algo falla, regresa un placeholder.
    """
    endpoint, base = _resolve_endpoint_and_base()
    seed = req.seed if req.seed is not None else int(time.time() * 1000) % 1_000_000
    checkpoint = (checkpoint_name or _configured_checkpoint()).strip() or DEFAULT_IMAGE_CKPT

    prompt_graph = {
        "client_id": "aegis",
        "prompt": {
            "0": {  # checkpoint
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint},
            },
            "1": {  # positive
                "class_type": "CLIPTextEncode",
                "inputs": {"text": req.prompt, "clip": ["0", 1]},
            },
            "2": {  # negative
                "class_type": "CLIPTextEncode",
                "inputs": {"text": req.negative_prompt or "", "clip": ["0", 1]},
            },
            "3": {  # latent
                "class_type": "EmptyLatentImage",
                "inputs": {"width": req.width, "height": req.height, "batch_size": 1},
            },
            "4": {  # sampler
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": req.steps,
                    "cfg": req.cfg,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["0", 0],
                    "positive": ["1", 0],
                    "negative": ["2", 0],
                    "latent_image": ["3", 0],
                },
            },
            "5": {  # decode
                "class_type": "VAEDecode",
                "inputs": {"samples": ["4", 0], "vae": ["0", 2]},
            },
            "6": {  # save
                "class_type": "SaveImage",
                "inputs": {"images": ["5", 0], "filename_prefix": "aegis"},
            },
        },
    }

    try:
        resp = requests.post(endpoint, json=prompt_graph, timeout=GEN_TIMEOUT)
        resp.raise_for_status()
        response_payload = resp.json() if resp.content else {}
        prompt_id = response_payload.get("prompt_id")
        if not prompt_id:
            # Some backends return a structured error payload.
            backend_error = response_payload.get("error") or response_payload.get("detail")
            raise RuntimeError(f"No prompt_id returned by ComfyUI ({backend_error or 'unknown error'})")

        history_url = f"{base}/history/{prompt_id}"
        deadline = time.time() + GEN_TIMEOUT
        images_meta = None
        while time.time() < deadline:
            h = requests.get(history_url, timeout=10)
            h.raise_for_status()
            hist = h.json()
            # history structure: { prompt_id: { outputs: { "6": { "images": [...] }}}}
            entry = hist.get(prompt_id) or {}
            outputs = entry.get("outputs") or {}
            save_node = outputs.get("6") or {}
            imgs = save_node.get("images")
            if imgs:
                images_meta = imgs
                break
            time.sleep(0.5)

        if not images_meta:
            raise RuntimeError("No images in history")

        img_info = images_meta[0]
        filename = img_info.get("filename")
        subfolder = img_info.get("subfolder") or ""
        img_type = img_info.get("type") or "output"
        if not filename:
            raise RuntimeError("Missing filename from history")

        view_url = f"{base}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
        img_resp = requests.get(view_url, timeout=GEN_TIMEOUT)
        img_resp.raise_for_status()

        fname = f"{uuid.uuid4().hex}.png"
        path = IMAGES_DIR / fname
        path.write_bytes(img_resp.content)
        return path, True, None
    except Exception as exc:
        err = str(exc)
        logger.warning("Image backend call failed, using placeholder fallback: %s", err)
        return _render_placeholder(req.prompt, req.width, req.height, req.seed), False, err


def _probe_backend(base_url: str) -> tuple[bool, Optional[int], Optional[str]]:
    """Probe backend liveness for readiness/capabilities reporting."""
    try:
        resp = requests.get(base_url, timeout=min(max(GEN_TIMEOUT, 1.0), 4.0))
        reachable = resp.status_code < 500
        return reachable, resp.status_code, None
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)


def runtime_image_status() -> Dict[str, Any]:
    """Return canonical image capability state consumed by `/system/readyz`."""
    endpoint, base = _resolve_endpoint_and_base()
    recent_rows: list[dict] = []
    last_error = ""
    if LOG_FILE.exists():
        try:
            for line in reversed(LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()):
                if len(recent_rows) >= 10:
                    break
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    recent_rows.append(item)
        except Exception:
            recent_rows = []

    backend_successes = sum(1 for row in recent_rows if bool(row.get("backend_ok")))
    fallback_count = sum(1 for row in recent_rows if bool(row.get("fallback_used")))
    if recent_rows:
        last_error = str(recent_rows[0].get("backend_error") or "").strip()

    reachable, probe_status, probe_error = _probe_backend(base or endpoint)
    selected_ckpt, configured_ckpt, available_ckpts, ckpt_error = _resolve_checkpoint(base)
    fallback_only = bool(recent_rows) and backend_successes == 0 and fallback_count > 0
    transient_fallbacks = bool(recent_rows) and reachable and backend_successes > 0 and fallback_count > 0
    status = "ready"
    if not reachable and fallback_only:
        status = "fallback-only"
    elif not reachable:
        status = "degraded"
    elif fallback_only:
        status = "degraded"

    return {
        "status": status,
        "endpoint": endpoint,
        "backend_base_url": base,
        "provider": (os.getenv("AEGIS_IMAGE_PROVIDER") or GEN_PROVIDER).strip() or GEN_PROVIDER,
        "timeout_seconds": GEN_TIMEOUT,
        "images_dir": str(IMAGES_DIR),
        "images_dir_exists": IMAGES_DIR.exists(),
        "backend_reachable": reachable,
        "backend_probe_status": probe_status,
        "backend_probe_error": (probe_error or "")[:400] or None,
        "recent_log_rows": len(recent_rows),
        "recent_backend_successes": backend_successes,
        "recent_fallbacks": fallback_count,
        "fallback_only": fallback_only,
        "transient_fallbacks": transient_fallbacks,
        "last_backend_error": last_error[:400] or None,
        "configured_checkpoint": configured_ckpt,
        "selected_checkpoint": selected_ckpt,
        "available_checkpoints": available_ckpts,
        "checkpoint_fallback_used": bool(available_ckpts) and selected_ckpt != configured_ckpt,
        "checkpoint_resolver_error": (ckpt_error or "")[:400] or None,
    }


@router.post("/generate")
async def generate_image(req: ImageRequest):
    if req.width > 1024 or req.height > 1024:
        raise HTTPException(status_code=400, detail="max size 1024x1024")
    if req.steps > 50:
        raise HTTPException(status_code=400, detail="max steps 50")

    _, base = _resolve_endpoint_and_base()
    selected_ckpt, configured_ckpt, available_ckpts, ckpt_error = _resolve_checkpoint(base)
    start = time.time()
    # Llama al backend local; si falla, usa placeholder
    path, backend_ok, backend_error = _call_local_sd(req, checkpoint_name=selected_ckpt)
    latency = int((time.time() - start) * 1000)
    fallback_used = not backend_ok

    payload = {
        "prompt": req.prompt,
        "negative": req.negative_prompt,
        "width": req.width,
        "height": req.height,
        "steps": req.steps,
        "cfg": req.cfg,
        "seed": req.seed,
        "provider": req.provider,
        "path": _public_path(path),
        "latency_ms": latency,
        "backend_ok": backend_ok,
        "fallback_used": fallback_used,
        "backend_error": (backend_error or "")[:400],
        "checkpoint_configured": configured_ckpt,
        "checkpoint_selected": selected_ckpt,
        "checkpoint_fallback_used": bool(available_ckpts) and selected_ckpt != configured_ckpt,
        "checkpoint_resolver_error": (ckpt_error or "")[:400],
    }
    _save_log(payload)

    return {
        "image_path": payload["path"],
        "provider": req.provider,
        "latency_ms": latency,
        "seed": req.seed,
        "backend_ok": backend_ok,
        "fallback_used": fallback_used,
        "backend_error": (backend_error or "")[:400] or None,
        "checkpoint_configured": configured_ckpt,
        "checkpoint_selected": selected_ckpt,
        "checkpoint_fallback_used": bool(available_ckpts) and selected_ckpt != configured_ckpt,
        "checkpoint_resolver_error": (ckpt_error or "")[:400] or None,
    }


@router.post("/generate_with_reference")
async def generate_with_reference(
    prompt: str = Form(...),
    file: UploadFile = File(...),
    include_ocr: bool = Form(True),
    lang: str = Form("en"),
    negative_prompt: Optional[str] = Form(None),
    width: int = Form(512),
    height: int = Form(512),
    steps: int = Form(20),
    cfg: float = Form(7.0),
    seed: Optional[int] = Form(None),
    provider: str = Form(GEN_PROVIDER),
):
    if width > 1024 or height > 1024:
        raise HTTPException(status_code=400, detail="max size 1024x1024")
    if steps > 50:
        raise HTTPException(status_code=400, detail="max steps 50")
    content_type = str(file.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="reference file must be an image")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="empty reference image")
    if len(image_bytes) > MAX_REFERENCE_BYTES:
        raise HTTPException(status_code=413, detail="reference image too large")

    ocr_text = ""
    ocr_error = ""
    ocr_used = False
    if include_ocr:
        try:
            ocr_text = analyze_image_bytes(image_bytes, lang=str(lang or "en"), mode="ocr")
            ocr_used = bool(str(ocr_text or "").strip())
        except Exception as exc:  # noqa: BLE001
            ocr_error = str(exc)
            ocr_text = ""
            ocr_used = False

    merged_prompt = _merge_reference_prompt(prompt, ocr_text, str(lang or "en"))
    req = ImageRequest(
        prompt=merged_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
        provider=provider,
    )

    _, base = _resolve_endpoint_and_base()
    selected_ckpt, configured_ckpt, available_ckpts, ckpt_error = _resolve_checkpoint(base)
    start = time.time()
    path, backend_ok, backend_error = _call_local_sd(req, checkpoint_name=selected_ckpt)
    latency = int((time.time() - start) * 1000)
    fallback_used = not backend_ok
    payload = {
        "prompt": req.prompt,
        "negative": req.negative_prompt,
        "width": req.width,
        "height": req.height,
        "steps": req.steps,
        "cfg": req.cfg,
        "seed": req.seed,
        "provider": req.provider,
        "path": _public_path(path),
        "latency_ms": latency,
        "backend_ok": backend_ok,
        "fallback_used": fallback_used,
        "backend_error": (backend_error or "")[:400],
        "reference_used": True,
        "reference_name": str(file.filename or "").strip() or "reference_image",
        "ocr_used": ocr_used,
        "ocr_error": (ocr_error or "")[:400],
        "checkpoint_configured": configured_ckpt,
        "checkpoint_selected": selected_ckpt,
        "checkpoint_fallback_used": bool(available_ckpts) and selected_ckpt != configured_ckpt,
        "checkpoint_resolver_error": (ckpt_error or "")[:400],
    }
    _save_log(payload)

    return {
        "image_path": payload["path"],
        "provider": req.provider,
        "latency_ms": latency,
        "seed": req.seed,
        "backend_ok": backend_ok,
        "fallback_used": fallback_used,
        "backend_error": (backend_error or "")[:400] or None,
        "reference_used": True,
        "reference_name": payload["reference_name"],
        "ocr_used": ocr_used,
        "ocr_error": (ocr_error or "")[:400] or None,
        "checkpoint_configured": configured_ckpt,
        "checkpoint_selected": selected_ckpt,
        "checkpoint_fallback_used": bool(available_ckpts) and selected_ckpt != configured_ckpt,
        "checkpoint_resolver_error": (ckpt_error or "")[:400] or None,
    }


@router.get("/checkpoints")
async def list_checkpoints():
    endpoint, base = _resolve_endpoint_and_base()
    selected_ckpt, configured_ckpt, available_ckpts, ckpt_error = _resolve_checkpoint(base)
    return {
        "endpoint": endpoint,
        "backend_base_url": base,
        "configured_checkpoint": configured_ckpt,
        "selected_checkpoint": selected_ckpt,
        "available_checkpoints": available_ckpts,
        "checkpoint_fallback_used": bool(available_ckpts) and selected_ckpt != configured_ckpt,
        "resolver_error": (ckpt_error or "")[:400] or None,
    }


@router.get("/recent")
async def recent_images(limit: int = 10):
    if not LOG_FILE.exists():
        return []
    rows = []
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if len(rows) >= limit:
                break
            try:
                item = json.loads(line)
            except Exception:
                continue
            rel = item.get("path")
            if isinstance(rel, str) and rel:
                abs_path = PROJECT_ROOT / rel
                if not abs_path.exists():
                    continue
            rows.append(item)
    except Exception:
        return []
    return rows
