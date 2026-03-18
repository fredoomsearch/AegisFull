from __future__ import annotations

"""
Canonical project registry store.

Why this module exists:
- Keep project_id -> root/manifest/status mapping deterministic.
- Centralize project registration/update/delete semantics for `/files/*`.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict
from app.utils.runtime_helpers import now_ts as _now_ts

UPLOAD_ROOT = Path(os.getenv("FILES_UPLOAD_ROOT", "data/uploads")).resolve()
STORE_FILE = UPLOAD_ROOT / ".aegis_projects.json"


class ProjectRecord(TypedDict, total=False):
    project_id: str
    root_path: str
    source: str
    status: str
    manifest_path: Optional[str]
    index_namespace: str
    created_at: int
    updated_at: int
    last_ingest_at: Optional[int]
    chunk_count: int
    metadata: Dict[str, Any]


_lock = threading.RLock()

def _load_store() -> Dict[str, ProjectRecord]:
    """Load project registry from disk; return empty store on parse errors."""
    try:
        if STORE_FILE.exists():
            raw = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {
                    str(project_id): _normalize_record(project_id, record)
                    for project_id, record in raw.items()
                    if isinstance(record, dict)
                }
    except Exception:
        pass
    return {}


def _save_store(store: Dict[str, ProjectRecord]) -> None:
    """Atomically persist project registry to disk."""
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_FILE.with_suffix(STORE_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STORE_FILE)
    except Exception:
        pass


def _normalize_record(project_id: str, raw: Dict[str, Any]) -> ProjectRecord:
    now = _now_ts()
    record: ProjectRecord = {
        "project_id": str(project_id),
        "root_path": str(raw.get("root_path") or ""),
        "source": str(raw.get("source") or "local"),
        "status": str(raw.get("status") or "unknown"),
        "manifest_path": str(raw.get("manifest_path") or "") or None,
        "index_namespace": str(raw.get("index_namespace") or project_id),
        "created_at": int(raw.get("created_at") or now),
        "updated_at": int(raw.get("updated_at") or now),
        "last_ingest_at": int(raw.get("last_ingest_at")) if raw.get("last_ingest_at") else None,
        "chunk_count": int(raw.get("chunk_count") or 0),
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    }
    return record


def list_projects(limit: int = 50) -> List[ProjectRecord]:
    with _lock:
        store = _load_store()
        items = list(store.values())
    items.sort(key=lambda row: int(row.get("updated_at") or 0), reverse=True)
    return items[: max(1, limit)]


def get_project(project_id: str) -> Optional[ProjectRecord]:
    if not project_id:
        return None
    with _lock:
        return _load_store().get(project_id)


def get_project_by_path(path: Path | str) -> Optional[ProjectRecord]:
    try:
        target = Path(path).resolve()
    except Exception:
        return None
    with _lock:
        for record in _load_store().values():
            raw_root = str(record.get("root_path") or "").strip()
            if not raw_root:
                continue
            try:
                root = Path(raw_root).resolve()
            except Exception:
                continue
            if target == root:
                return record
    return None


def register_project(
    project_id: str,
    root_path: Path | str,
    *,
    source: str,
    status: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> ProjectRecord:
    """Create or upsert a project record in canonical registry."""
    now = _now_ts()
    root = str(Path(root_path).resolve())
    with _lock:
        store = _load_store()
        current = store.get(project_id) or _normalize_record(project_id, {})
        current["root_path"] = root
        current["source"] = source
        current["status"] = status
        current["index_namespace"] = project_id
        current["updated_at"] = now
        if not current.get("created_at"):
            current["created_at"] = now
        if metadata:
            merged = dict(current.get("metadata") or {})
            merged.update(metadata)
            current["metadata"] = merged
        store[project_id] = current
        _save_store(store)
        return current


def ensure_project_for_path(path: Path | str, *, source: str = "local") -> ProjectRecord:
    target = Path(path).resolve()
    existing = get_project_by_path(target)
    if existing:
        return existing
    return register_project(target.name, target, source=source, status="uploaded")


def update_project(project_id: str, **updates: Any) -> Optional[ProjectRecord]:
    if not project_id:
        return None
    with _lock:
        store = _load_store()
        current = store.get(project_id)
        if not current:
            return None
        current = _normalize_record(project_id, current)
        now = _now_ts()
        for key, value in updates.items():
            if key == "metadata" and isinstance(value, dict):
                merged = dict(current.get("metadata") or {})
                merged.update(value)
                current["metadata"] = merged
                continue
            current[key] = value
        current["updated_at"] = now
        store[project_id] = current
        _save_store(store)
        return current


def delete_project(project_id: str) -> bool:
    if not project_id:
        return False
    with _lock:
        store = _load_store()
        if project_id not in store:
            return False
        store.pop(project_id, None)
        _save_store(store)
        return True


def delete_project_by_path(path: Path | str) -> bool:
    record = get_project_by_path(path)
    if not record:
        return False
    return delete_project(str(record.get("project_id") or ""))
