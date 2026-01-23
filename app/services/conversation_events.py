from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

MAX_EVENTS_PER_CONV = int(os.getenv("AEGIS_CONV_EVENTS_MAX", "200") or "200")
EVENT_TTL_SECONDS = int(os.getenv("AEGIS_CONV_EVENTS_TTL", "3600") or "3600")
INCLUDE_TEXT = (os.getenv("AEGIS_CONV_EVENTS_INCLUDE_TEXT", "") or "").lower() in {"1", "true", "yes", "on"}

_lock = threading.Lock()
_events: Dict[str, List[Dict[str, Any]]] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sanitize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    if INCLUDE_TEXT:
        return data
    sanitized: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[f"{key}_len"] = len(value)
        else:
            sanitized[key] = value
    return sanitized


def _prune_locked(now_ms: int) -> None:
    if EVENT_TTL_SECONDS <= 0:
        return
    cutoff = now_ms - (EVENT_TTL_SECONDS * 1000)
    for conv_id in list(_events.keys()):
        items = [evt for evt in _events.get(conv_id, []) if evt.get("ts", 0) >= cutoff]
        if items:
            _events[conv_id] = items
        else:
            _events.pop(conv_id, None)


def record_event(
    conv_id: str,
    stage: str,
    *,
    level: str = "info",
    detail: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not conv_id:
        return None
    now_ms = _now_ms()
    evt: Dict[str, Any] = {"ts": now_ms, "stage": stage, "level": level}
    if detail:
        evt["detail"] = detail
    if data:
        evt["data"] = _sanitize_data(data)

    with _lock:
        items = _events.setdefault(conv_id, [])
        items.append(evt)
        if MAX_EVENTS_PER_CONV > 0 and len(items) > MAX_EVENTS_PER_CONV:
            del items[: len(items) - MAX_EVENTS_PER_CONV]
        _prune_locked(now_ms)
    return evt


def list_events(
    conv_id: str,
    *,
    since_ts: Optional[int] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    if not conv_id:
        return []
    with _lock:
        _prune_locked(_now_ms())
        items = list(_events.get(conv_id, []))
    if since_ts:
        items = [evt for evt in items if int(evt.get("ts", 0)) > int(since_ts)]
    if limit > 0:
        return items[-limit:] 
    return items
