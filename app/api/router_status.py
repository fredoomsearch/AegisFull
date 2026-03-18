from __future__ import annotations

from threading import RLock
from typing import Any, Dict

_lock = RLock()
_status: Dict[str, Dict[str, Any]] = {}


def record_router_status(label: str, *, enabled: bool, mounted: bool, detail: str = "") -> None:
    with _lock:
        _status[str(label)] = {
            "enabled": bool(enabled),
            "mounted": bool(mounted),
            "detail": str(detail or ""),
        }


def snapshot_router_status() -> Dict[str, Dict[str, Any]]:
    with _lock:
        return {key: dict(value) for key, value in _status.items()}
