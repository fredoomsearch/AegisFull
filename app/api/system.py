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


def _pnl_snapshot() -> Dict[str, Any]:
    try:
        trades = crypto_trade_log.list_trades(limit=200)
        pnl = crypto_trade_log.compute_pnl(trades, price_lookup=lambda _sym: None)
        return pnl
    except Exception:
        return {}


@router.get("/snapshot")
async def system_snapshot() -> Dict[str, Any]:
    """
    Returns a compact snapshot of recent state: uploads roots, jobs, embeddings,
    predictions/outcomes, stats, and P&L.
    """
    emb = _embedding_status()
    jobs = [job_manager.serialize_job(j) for j in job_manager.list_jobs(limit=5)]
    preds = crypto_prediction_log.pair_predictions_with_outcomes(limit=10)
    stats = crypto_prediction_log.recent_stats(limit=200)
    pnl = _pnl_snapshot()

    return {
        "ingest_roots": _list_ingest_roots(),
        "jobs": jobs,
        "embeddings": emb,
        "predictions": preds,
        "stats": stats,
        "pnl": pnl,
    }
