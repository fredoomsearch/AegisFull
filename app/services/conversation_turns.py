from __future__ import annotations

"""
Conversation turn/item trace store.

Why this module exists:
- Persist structured turn traces for planner/tool debugging.
- Provide deterministic turn history endpoints for UI and evals.
"""

import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.utils.runtime_helpers import now_ms as _now_ms

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TURNS_DIR = PROJECT_ROOT / "data" / "conversation_turns"
MAX_TURNS_PER_CONV = 80
MAX_ITEMS_PER_TURN = 32
MAX_TEXT = 1200

_lock = threading.RLock()

def _conv_path(conversation_id: str) -> Path:
    return TURNS_DIR / f"{conversation_id}.json"


def _legacy_conv_dir(conversation_id: str) -> Path:
    return TURNS_DIR / str(conversation_id or "").strip()


def _trim_text(value: Any, max_chars: int = MAX_TEXT) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Bound payload size to keep turn traces compact and safe."""
    out: Dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if isinstance(value, str):
            out[key] = _trim_text(value)
        elif isinstance(value, list):
            out[key] = [(_trim_text(item) if isinstance(item, str) else item) for item in value[:20]]
        elif isinstance(value, dict):
            nested: Dict[str, Any] = {}
            for nested_key, nested_value in list(value.items())[:20]:
                if isinstance(nested_value, str):
                    nested[nested_key] = _trim_text(nested_value)
                else:
                    nested[nested_key] = nested_value
            out[key] = nested
        else:
            out[key] = value
    return out


def _load_turns(conversation_id: str) -> List[Dict[str, Any]]:
    path = _conv_path(conversation_id)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _save_turns(conversation_id: str, turns: List[Dict[str, Any]]) -> None:
    TURNS_DIR.mkdir(parents=True, exist_ok=True)
    path = _conv_path(conversation_id)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(turns[-MAX_TURNS_PER_CONV:], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def start_turn(
    conversation_id: str,
    *,
    user_message: str,
    mode: str,
    source_plan: str,
    active_project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Start a new turn record and persist it immediately."""
    turn = {
        "turn_id": uuid.uuid4().hex[:12],
        "created_at": _now_ms(),
        "finished_at": None,
        "status": "running",
        "mode": mode or "chat",
        "source_plan": source_plan or "local_only",
        "active_project_id": active_project_id,
        "user_message": _trim_text(user_message),
        "items": [],
    }
    with _lock:
        turns = _load_turns(conversation_id)
        turns.append(turn)
        _save_turns(conversation_id, turns)
    return turn


def append_turn_item(
    conversation_id: str,
    turn_id: str,
    *,
    kind: str,
    payload: Optional[Dict[str, Any]] = None,
    status: str = "ok",
) -> Optional[Dict[str, Any]]:
    """Append a structured item (plan/tool/web/llm) to an existing turn."""
    if not conversation_id or not turn_id:
        return None
    item = {
        "item_id": uuid.uuid4().hex[:12],
        "ts": _now_ms(),
        "kind": kind,
        "status": status,
        "payload": _sanitize_payload(payload or {}),
    }
    with _lock:
        turns = _load_turns(conversation_id)
        for turn in reversed(turns):
            if str(turn.get("turn_id")) != str(turn_id):
                continue
            items = turn.setdefault("items", [])
            if isinstance(items, list):
                items.append(item)
                if len(items) > MAX_ITEMS_PER_TURN:
                    del items[: len(items) - MAX_ITEMS_PER_TURN]
                _save_turns(conversation_id, turns)
                return item
            break
    return None


def finish_turn(
    conversation_id: str,
    turn_id: str,
    *,
    assistant_message: str,
    response_context: Optional[Dict[str, Any]] = None,
    status: str = "success",
) -> Optional[Dict[str, Any]]:
    """Mark turn as completed with final response context/status."""
    if not conversation_id or not turn_id:
        return None
    with _lock:
        turns = _load_turns(conversation_id)
        for turn in reversed(turns):
            if str(turn.get("turn_id")) != str(turn_id):
                continue
            turn["finished_at"] = _now_ms()
            turn["status"] = status
            turn["assistant_message"] = _trim_text(assistant_message)
            turn["response_context"] = _sanitize_payload(response_context or {})
            _save_turns(conversation_id, turns)
            return turn
    return None


def delete_turns(conversation_id: str) -> bool:
    """
    Remove persisted turn traces for one conversation.

    Handles both canonical `<conversation_id>.json` files and legacy
    directory-shaped traces (`data/conversation_turns/<conversation_id>/...`).
    """
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        return False
    removed = False
    with _lock:
        file_path = _conv_path(conv_id)
        try:
            if file_path.exists():
                file_path.unlink()
                removed = True
        except Exception:
            pass
        legacy_dir = _legacy_conv_dir(conv_id)
        try:
            if legacy_dir.exists() and legacy_dir.is_dir():
                shutil.rmtree(legacy_dir, ignore_errors=True)
                removed = True
        except Exception:
            pass
    return removed


def list_turns(conversation_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    with _lock:
        turns = _load_turns(conversation_id)
    return turns[-max(1, limit) :]


def get_turn(conversation_id: str, turn_id: str, *, include_items: bool = True) -> Optional[Dict[str, Any]]:
    if not conversation_id or not turn_id:
        return None
    with _lock:
        turns = _load_turns(conversation_id)
    for turn in reversed(turns):
        if str(turn.get("turn_id") or "") != str(turn_id):
            continue
        if include_items:
            return turn
        slim = dict(turn)
        slim.pop("items", None)
        return slim
    return None


def get_turns_meta(conversation_id: str) -> Dict[str, Any]:
    with _lock:
        turns = _load_turns(conversation_id)
    count = len(turns)
    if not turns:
        return {"turn_count": 0, "last_turn_id": None}
    last = turns[-1]
    return {
        "turn_count": count,
        "last_turn_id": str(last.get("turn_id") or "") or None,
    }


def export_turns_bundle(conversation_id: str, *, limit: int = 200) -> Dict[str, Any]:
    safe_limit = max(1, min(int(limit or 200), 2000))
    with _lock:
        turns = _load_turns(conversation_id)
    items = turns[-safe_limit:]
    meta = get_turns_meta(conversation_id)
    return {
        "conversation_id": conversation_id,
        "turn_count": int(meta.get("turn_count") or 0),
        "last_turn_id": meta.get("last_turn_id"),
        "items": items,
    }
