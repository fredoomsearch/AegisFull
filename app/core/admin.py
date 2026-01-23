from __future__ import annotations

"""
Admin endpoints (refresh crypto models in background).

This is intentionally simple: it triggers the fetch + train scripts without
blocking the request. Protect with ADMIN_API_KEY if set.
"""

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from threading import Lock
from typing import Set

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import require_admin_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
_running_procs: Set[subprocess.Popen] = set()
_procs_lock = Lock()


class RefreshRequest(BaseModel):
    quick: bool = Field(False, description="Use smaller models for faster training")
    per_page: int = Field(200, description="Items per page for fetch (max 250)")
    pages: int = Field(1, description="Number of pages to fetch")
    vs_currency: str = Field("usd", description="Quote currency for fetch")
    out_csv: Path = Field(Path("data/crypto_data.csv"), description="Output CSV path")


class RefreshResponse(BaseModel):
    status: str
    job_id: str
    log_path: Path


def _run_cmd(cmd: list[str], log_file: Path) -> None:
    proc: subprocess.Popen | None = None
    try:
        logger.info("Running: %s", " ".join(cmd))
        with log_file.open("a", encoding="utf-8") as lf:
            lf.write(f"\n[$] {' '.join(cmd)}\n")
            lf.flush()
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, text=True)
        with _procs_lock:
            if proc:
                _running_procs.add(proc)
        if proc:
            proc.wait()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Admin refresh command failed: %s", exc)
    finally:
        if proc:
            with _procs_lock:
                _running_procs.discard(proc)


def _refresh_crypto_background(req: RefreshRequest, log_file: Path) -> None:
    python_bin = sys.executable or "python"
    per_page = max(1, min(req.per_page, 250))
    fetch_cmd = [
        python_bin,
        "-m",
        "app.scripts.fetch_market_data",
        "--out",
        str(req.out_csv),
        "--per-page",
        str(per_page),
        "--pages",
        str(req.pages),
        "--vs-currency",
        req.vs_currency,
    ]
    train_cmd = [
        python_bin,
        "-m",
        "app.scripts.train_models",
        "--csv-path",
        str(req.out_csv),
    ]
    if req.quick:
        train_cmd.append("--quick")

    _run_cmd(fetch_cmd, log_file)
    _run_cmd(train_cmd, log_file)


@router.post("/refresh-crypto", status_code=202)
async def refresh_crypto(
    req: RefreshRequest,
    background: BackgroundTasks,
    _: None = Depends(require_admin_scope),
) -> RefreshResponse:
    job_id = uuid.uuid4().hex[:10]
    logs_dir = Path(os.getenv("CRYPTO_REFRESH_LOG_DIR", "logs")).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"refresh_{job_id}.log"

    background.add_task(_refresh_crypto_background, req, log_file)
    return RefreshResponse(status="accepted", job_id=job_id, log_path=log_file)


@router.get("/refresh-log")
async def refresh_log(
    path: str = Query(..., description="Path to log file (must be under logs/)"),
    tail: int = Query(200, ge=10, le=2000, description="Number of lines from the end"),
    _: None = Depends(require_admin_scope),
) -> dict:
    """
    Return the last N lines of a refresh log. Restricted to logs/ directory.
    """
    logs_dir = Path(os.getenv("CRYPTO_REFRESH_LOG_DIR", "logs")).resolve()
    target = Path(path).resolve()
    if not str(target).startswith(str(logs_dir)):
        raise HTTPException(status_code=400, detail="Log path outside allowed directory")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    try:
        with target.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        tail_lines = lines[-tail:]
        return {"path": str(target), "lines": tail_lines}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Cannot read log: {exc}")


@router.post("/cancel-all")
async def cancel_all_processes(_: None = Depends(require_admin_scope)) -> dict:
    """
    Best-effort terminate all running admin background subprocesses.
    """
    killed = 0
    with _procs_lock:
        procs = list(_running_procs)
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        killed += 1
        with _procs_lock:
            _running_procs.discard(p)
    return {"status": "ok", "terminated": killed}
