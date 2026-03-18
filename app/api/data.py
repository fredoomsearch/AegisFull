from __future__ import annotations

"""
Data/DB utility endpoints.

Why this module exists:
- Expose minimal database health signal for diagnostics.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_api_key
from app.db.deps import get_db

router = APIRouter(
    prefix="/data",
    tags=["data"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/health")
def data_health(db: Session = Depends(get_db)) -> dict:
    """
    Health check del módulo de datos/DB. Ejecuta un SELECT 1 para validar conexión.
    """
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"DB unreachable: {exc}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {"status": "ok", "db": "up", "latency_ms": elapsed_ms}
