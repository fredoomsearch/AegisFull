from __future__ import annotations

"""
ClamAV integration and event telemetry.

Why this module exists:
- Provide AV scanner status for readiness checks.
- Store recent scan events for audit/debug visibility.
"""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.utils.runtime_helpers import now_ts as _now_ts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
AV_LOG_FILE = Path(os.getenv("AEGIS_AV_LOG_FILE", str(DATA_DIR / "av_scan_events.jsonl"))).resolve()
AV_MAX_RECENT = max(1, int(os.getenv("AEGIS_AV_RECENT_LIMIT", "50") or "50"))

_lock = threading.RLock()

def _detect_scanner() -> tuple[Optional[str], Optional[str]]:
    clamdscan = shutil.which("clamdscan")
    if clamdscan:
        return "clamdscan", clamdscan
    clamscan = shutil.which("clamscan")
    if clamscan:
        return "clamscan", clamscan
    return None, None


def clamav_status() -> Dict[str, Any]:
    """Return scanner availability/reachability summary."""
    scanner_kind, scanner_path = _detect_scanner()
    if not scanner_path:
        return {
            "status": "missing",
            "available": False,
            "scanner": None,
            "scanner_path": None,
            "version": None,
            "reachable": False,
            "detail": "ClamAV scanner not found",
        }

    version = ""
    try:
        out = subprocess.check_output(
            [scanner_path, "--version"],
            timeout=3,
            stderr=subprocess.STDOUT,
            text=True,
        )
        version = (out or "").strip().splitlines()[0][:200]
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "degraded",
            "available": True,
            "scanner": scanner_kind,
            "scanner_path": scanner_path,
            "version": None,
            "reachable": False,
            "detail": f"Scanner present but version probe failed: {exc}",
        }

    reachable = True
    detail = f"{scanner_kind} available ({version})"
    status = "ready"
    if scanner_kind == "clamdscan":
        try:
            subprocess.check_output(
                [scanner_path, "--fdpass", "--stdout", "--version"],
                timeout=3,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as exc:  # noqa: BLE001
            reachable = False
            status = "degraded"
            detail = f"clamdscan present but daemon probe failed ({version}): {exc}"

    return {
        "status": status,
        "available": True,
        "scanner": scanner_kind,
        "scanner_path": scanner_path,
        "version": version or None,
        "reachable": reachable,
        "detail": detail,
    }


def record_av_event(
    *,
    path: str,
    status: str,
    detail: str = "",
    scanner: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
) -> None:
    """Append a normalized AV scan event to local log."""
    payload = {
        "ts": _now_ts(),
        "path": path,
        "status": status,
        "detail": detail[:500],
        "scanner": scanner or "",
        "elapsed_ms": int(elapsed_ms or 0),
    }
    with _lock:
        try:
            AV_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with AV_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass


def recent_av_events(limit: int = 20) -> List[Dict[str, Any]]:
    """Read most recent AV events from local JSONL log."""
    target_limit = max(1, min(limit, AV_MAX_RECENT))
    if not AV_LOG_FILE.exists():
        return []
    try:
        lines = AV_LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []

    rows: List[Dict[str, Any]] = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
        if len(rows) >= target_limit:
            break
    return rows


def latest_av_event() -> Optional[Dict[str, Any]]:
    rows = recent_av_events(limit=1)
    return rows[0] if rows else None
