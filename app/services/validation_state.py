from __future__ import annotations

"""
Validation flow state persistence.

Why this module exists:
- Persist startup/verify gate step statuses across process lifetime.
- Feed `/system/snapshot` and `/system/readyz` with last validation evidence.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List
from app.utils.runtime_helpers import now_ms as _now_ms

_lock = threading.Lock()
STATE_FILE = Path(os.getenv("AEGIS_VALIDATION_STATE_FILE", "data/validation_state.json"))

def _read_state() -> Dict[str, Any]:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {"last_updated_ms": 0, "flows": {}}


def _write_state(state: Dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def start_flow(flow: str, steps: List[str]) -> None:
    """Start a named validation flow with pending step map."""
    now = _now_ms()
    with _lock:
        state = _read_state()
        flows = dict(state.get("flows") or {})
        flows[flow] = {
            "status": "running",
            "detail": "",
            "started_at_ms": now,
            "finished_at_ms": None,
            "updated_at_ms": now,
            "steps": {
                step: {
                    "status": "pending",
                    "detail": "",
                    "updated_at_ms": now,
                }
                for step in steps
            },
        }
        state["flows"] = flows
        state["last_updated_ms"] = now
        _write_state(state)


def mark_step(flow: str, step: str, status: str, detail: str = "", meta: Dict[str, Any] | None = None) -> None:
    """Update one step status inside a running validation flow."""
    now = _now_ms()
    with _lock:
        state = _read_state()
        flows = dict(state.get("flows") or {})
        flow_state = dict(flows.get(flow) or {})
        steps = dict(flow_state.get("steps") or {})
        payload: Dict[str, Any] = {
            "status": status,
            "detail": detail,
            "updated_at_ms": now,
        }
        if meta:
            payload["meta"] = dict(meta)
        steps[step] = payload
        flow_state["steps"] = steps
        flow_state["updated_at_ms"] = now
        if flow_state.get("status") != "failed":
            flow_state["status"] = "running"
        flows[flow] = flow_state
        state["flows"] = flows
        state["last_updated_ms"] = now
        _write_state(state)


def finish_flow(flow: str, status: str, detail: str = "") -> None:
    """Finalize flow status and completion timestamps."""
    now = _now_ms()
    with _lock:
        state = _read_state()
        flows = dict(state.get("flows") or {})
        flow_state = dict(flows.get(flow) or {})
        flow_state["status"] = status
        flow_state["detail"] = detail
        flow_state["finished_at_ms"] = now
        flow_state["updated_at_ms"] = now
        flows[flow] = flow_state
        state["flows"] = flows
        state["last_updated_ms"] = now
        _write_state(state)


def snapshot() -> Dict[str, Any]:
    with _lock:
        return _read_state()
