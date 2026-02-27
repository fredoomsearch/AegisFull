from __future__ import annotations

"""
Lightweight system snapshot endpoints.
"""

import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.services import crypto_prediction_log, crypto_trade_log, job_manager
from app.services import health_state

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_api_key)])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = Path(os.getenv("FILES_UPLOAD_ROOT", "data/uploads")).resolve()


def _embedding_api():
    if (os.getenv("AEGIS_DISABLE_EMBEDDINGS", "0") or "0").lower() in {"1", "true", "yes", "on"}:
        return None
    try:
        from app.services import embedding_service

        return embedding_service
    except Exception:
        return None


def _is_under_uploads(path: Path) -> bool:
    try:
        return UPLOADS_DIR in path.resolve().parents or path.resolve() == UPLOADS_DIR
    except Exception:
        return False


def _serialize_root(entry: Path) -> Dict[str, Any]:
    stat = entry.stat()
    rel = entry.relative_to(PROJECT_ROOT)
    info: Dict[str, Any] = {
        "name": entry.name,
        "path": str(rel),
        "type": "dir" if entry.is_dir() else "file",
        "is_dir": entry.is_dir(),
        "size": stat.st_size,
        "modified": int(stat.st_mtime * 1000),
    }
    if entry.is_dir():
        try:
            children = list(entry.iterdir())
            info["items"] = len(children)
        except Exception:
            info["items"] = None
    return info


def _list_ingest_roots(limit: int = 25) -> List[Dict[str, Any]]:
    if not UPLOADS_DIR.exists():
        return []
    roots: List[Dict[str, Any]] = []
    try:
        entries = sorted(
            [p for p in UPLOADS_DIR.iterdir() if _is_under_uploads(p)],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        entries = []

    for entry in entries[:limit]:
        try:
            roots.append(_serialize_root(entry))
        except Exception:
            continue
    return roots


def _embedding_status() -> Dict[str, Any]:
    svc = _embedding_api()
    if svc is None:
        return {"status": "disabled", "detail": "Embeddings disabled for this runtime."}
    try:
        return svc.get_embedding_status(ensure_loaded=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _retrieval_status() -> Dict[str, Any]:
    try:
        from app.services import retrieval_service

        return retrieval_service.get_retrieval_status()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _image_status() -> Dict[str, Any]:
    images_dir = Path("data/images").resolve()
    log_file = images_dir / "log.jsonl"
    recent_count = 0
    if log_file.exists():
        try:
            recent_count = len(log_file.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            recent_count = 0
    endpoint = (os.getenv("AEGIS_IMAGE_ENDPOINT") or "http://127.0.0.1:8188/prompt").strip()
    if "/prompt" not in endpoint:
        endpoint = endpoint.rstrip("/") + "/prompt"
    try:
        timeout_seconds = float(os.getenv("AEGIS_IMAGE_TIMEOUT", "60") or "60")
    except Exception:
        timeout_seconds = 60.0
    return {
        "endpoint": endpoint,
        "provider": (os.getenv("AEGIS_IMAGE_PROVIDER") or "sd-local").strip() or "sd-local",
        "timeout_seconds": timeout_seconds,
        "images_dir": str(images_dir),
        "images_dir_exists": images_dir.exists(),
        "recent_log_rows": recent_count,
    }


def _pnl_snapshot() -> Dict[str, Any]:
    try:
        trades = crypto_trade_log.list_trades(limit=200)
        pnl = crypto_trade_log.compute_pnl(trades, price_lookup=lambda _sym: None)
        return pnl
    except Exception:
        return {}


def _env_snapshot() -> Dict[str, Any]:
    """Expose a few non-sensitive env toggles to help the assistant describe its state."""
    keys = [
        "BINANCE_LIVE",
        "AEGIS_SEARCH_PROVIDERS",
        "AEGIS_WEB_SNIPPETS_MAX_PAGES",
        "AEGIS_SEARCH_CACHE_TTL",
        "AEGIS_SEARCH_CACHE_DISK_TTL",
        "AEGIS_DISABLE_EMBEDDINGS",
        "AEGIS_DISABLE_DB",
    ]
    out: Dict[str, Any] = {}
    for k in keys:
        v = os.getenv(k)
        if v is not None:
            out[k] = v
    return out


def _security_snapshot() -> Dict[str, Any]:
    auth_mode = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()
    cors_raw = (os.getenv("AEGIS_CORS_ORIGINS", "*") or "*").strip()
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()] or ["*"]
    cors_wildcard = "*" in cors_origins
    cors_creds_raw = (os.getenv("AEGIS_CORS_ALLOW_CREDENTIALS", "auto") or "auto").strip().lower()
    secure_headers = (os.getenv("AEGIS_SECURE_HEADERS", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
    hsts_seconds_raw = (os.getenv("AEGIS_HSTS_SECONDS", "0") or "0").strip()
    try:
        hsts_seconds = int(hsts_seconds_raw)
    except Exception:
        hsts_seconds = 0

    weak_tokens = {"my-secret-key", "changeme", "change-me", "dev", "test", "password"}
    weak_keys: List[str] = []
    for env_name in ("AEGIS_API_KEY", "FILES_API_KEY", "ADMIN_API_KEY"):
        raw = (os.getenv(env_name) or "").strip()
        if not raw:
            continue
        if any(k.strip().lower() in weak_tokens for k in raw.split(",") if k.strip()):
            weak_keys.append(env_name)

    risks: List[str] = []
    if auth_mode != "on":
        risks.append(f"auth_mode={auth_mode}")
    if cors_wildcard:
        risks.append("cors_wildcard")
    if not secure_headers:
        risks.append("secure_headers_disabled")
    if hsts_seconds <= 0:
        risks.append("hsts_disabled")
    risks.extend([f"weak_key:{k}" for k in weak_keys])

    return {
        "auth_mode": auth_mode,
        "cors_origins": cors_origins,
        "cors_allow_credentials": cors_creds_raw,
        "cors_wildcard": cors_wildcard,
        "secure_headers_enabled": secure_headers,
        "hsts_seconds": hsts_seconds,
        "weak_keys": weak_keys,
        "risks": risks,
    }


@router.get("/snapshot")
async def system_snapshot() -> Dict[str, Any]:
    """
    Returns a compact snapshot of recent state: uploads roots, jobs, embeddings,
    predictions/outcomes, stats, and P&L.
    """
    emb = _embedding_status()
    retrieval = _retrieval_status()
    image = _image_status()
    jobs = [job_manager.serialize_job(j) for j in job_manager.list_jobs(limit=5)]
    preds = crypto_prediction_log.pair_predictions_with_outcomes(limit=10)
    stats = crypto_prediction_log.recent_stats(limit=200)
    pnl = _pnl_snapshot()
    health = health_state.snapshot()

    return {
        "ingest_roots": _list_ingest_roots(),
        "jobs": jobs,
        "embeddings": emb,
        "retrieval": retrieval,
        "image": image,
        "security": _security_snapshot(),
        "predictions": preds,
        "stats": stats,
        "pnl": pnl,
        "env": _env_snapshot(),
        "health": health,
    }


@router.get("/readyz")
async def readyz() -> Dict[str, Any]:
    emb = _embedding_status()
    retrieval = _retrieval_status()
    image = _image_status()
    jobs = [job_manager.serialize_job(j) for j in job_manager.list_jobs(limit=3)]

    emb_ok = emb.get("status") != "error"
    retrieval_ok = retrieval.get("status") != "error"
    image_ok = bool(image.get("images_dir_exists"))
    ready = emb_ok and retrieval_ok and image_ok

    return {
        "ready": ready,
        "checks": {
            "embeddings": emb_ok,
            "retrieval": retrieval_ok,
            "image": image_ok,
        },
        "security": _security_snapshot(),
        "embeddings": emb,
        "retrieval": retrieval,
        "image": image,
        "jobs": jobs,
    }
