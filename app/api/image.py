from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.api.deps import require_files_api_key

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
def _normalize_gen_url(raw: str) -> str:
    url = (raw or "").strip() or "http://127.0.0.1:8188/prompt"
    if "/prompt" not in url:
        return url.rstrip("/") + "/prompt"
    return url


GEN_URL = _normalize_gen_url(os.getenv("AEGIS_IMAGE_ENDPOINT", "http://127.0.0.1:8188/prompt"))
GEN_TIMEOUT = float(os.getenv("AEGIS_IMAGE_TIMEOUT", "60"))
GEN_PROVIDER = os.getenv("AEGIS_IMAGE_PROVIDER", "sd-local")


class ImageRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg: float = 7.0
    seed: Optional[int] = None
    provider: str = GEN_PROVIDER


def _save_log(payload: Dict[str, Any]) -> None:
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


def _call_local_sd(req: ImageRequest) -> tuple[Path, bool, Optional[str]]:
    """
    Llama a ComfyUI (API /prompt) con un grafo mínimo text2img y recupera
    la primera imagen generada vía /history/<prompt_id> + /view.
    Si algo falla, regresa un placeholder.
    """
    base = GEN_URL.rsplit("/prompt", 1)[0].rstrip("/")
    seed = req.seed if req.seed is not None else int(time.time() * 1000) % 1_000_000

    prompt_graph = {
        "client_id": "aegis",
        "prompt": {
            "0": {  # checkpoint
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": os.getenv("AEGIS_IMAGE_CKPT", "sd_turbo.safetensors")},
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
        resp = requests.post(GEN_URL, json=prompt_graph, timeout=GEN_TIMEOUT)
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


@router.post("/generate")
async def generate_image(req: ImageRequest):
    if req.width > 1024 or req.height > 1024:
        raise HTTPException(status_code=400, detail="max size 1024x1024")
    if req.steps > 50:
        raise HTTPException(status_code=400, detail="max steps 50")

    start = time.time()
    # Llama al backend local; si falla, usa placeholder
    path, backend_ok, backend_error = _call_local_sd(req)
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
