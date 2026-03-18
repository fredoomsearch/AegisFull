from __future__ import annotations

"""
Per-project ingest state checkpointing.

Why this module exists:
- Track file-hash snapshots to support incremental ingest behavior.
- Persist lightweight ingest metadata under each project root.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

STATE_FILENAME = ".aegis_ingest_state.json"


def load_project_ingest_state(root: Path) -> Dict[str, Any]:
    """Load `.aegis_ingest_state.json` for a project root."""
    try:
        path = root / STATE_FILENAME
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_project_ingest_state(
    root: Path,
    *,
    project_id: str,
    file_hashes: Dict[str, str],
    chunk_count: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """Save incremental ingest state atomically for project root."""
    path = root / STATE_FILENAME
    payload = {
        "project_id": project_id,
        "updated_at": int(time.time()),
        "chunk_count": int(chunk_count),
        "file_hashes": dict(file_hashes),
        "metadata": metadata or {},
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path
