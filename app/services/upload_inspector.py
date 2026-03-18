from __future__ import annotations

"""
Upload folder inspection utilities.

Why this module exists:
- Produce quick deterministic summaries of uploaded project trees.
- Support “what did I upload?” flows before/after ingest.
"""

import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_ROOT = Path(os.getenv("FILES_UPLOAD_ROOT", "data/uploads")).resolve()
STATE_FILE = UPLOAD_ROOT / ".aegis_upload_state.json"
_PATH_TOKEN_RE = re.compile(r"(~?/[^\s,;\"'<>]+|data/uploads/[^\s,;\"'<>]+)")


def _safe_resolve(path: Path) -> Optional[Path]:
    try:
        resolved = path.resolve()
    except Exception:
        return None
    if resolved == UPLOAD_ROOT or UPLOAD_ROOT in resolved.parents:
        return resolved
    return None


def resolve_upload_path(raw_path: str) -> Optional[Path]:
    raw = (raw_path or "").strip()
    if not raw:
        return None

    cand = Path(raw).expanduser()
    if not cand.is_absolute():
        cand = (PROJECT_ROOT / cand).resolve()
    else:
        cand = cand.resolve()

    safe = _safe_resolve(cand)
    if safe is None or not safe.exists() or not safe.is_dir():
        return None
    return safe


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def remember_last_upload(path: Path, source: str = "upload") -> None:
    safe = _safe_resolve(path)
    if safe is None:
        return
    state = _load_state()
    state["last_upload"] = {
        "path": str(safe),
        "source": source,
        "ts": int(time.time()),
    }
    _save_state(state)


def get_last_upload_path() -> Optional[Path]:
    state = _load_state()
    last = state.get("last_upload") if isinstance(state, dict) else None
    if not isinstance(last, dict):
        return None
    raw = (last.get("path") or "").strip()
    if not raw:
        return None
    return resolve_upload_path(raw)


def extract_upload_path_from_text(text: str) -> Optional[str]:
    raw = text or ""
    for token in _PATH_TOKEN_RE.findall(raw):
        token = token.strip().rstrip(".,;:)]}\"'")
        if not token:
            continue
        if resolve_upload_path(token) is not None:
            return token
    return None


def inspect_upload_tree(path: Path, sample_limit: int = 120, max_walk_files: int = 5000) -> Dict:
    total_files = 0
    total_dirs = 0
    total_bytes = 0
    sample_files: List[Dict] = []
    ext_counter: Counter[str] = Counter()
    truncated = False

    for root, dirs, files in os.walk(path):
        total_dirs += len(dirs)
        for filename in files:
            fp = Path(root) / filename
            try:
                st = fp.stat()
            except OSError:
                continue
            total_files += 1
            total_bytes += int(st.st_size)
            ext = fp.suffix.lower() if fp.suffix else "(no_ext)"
            ext_counter[ext] += 1
            if len(sample_files) < sample_limit:
                try:
                    rel = str(fp.relative_to(path))
                except Exception:
                    rel = filename
                sample_files.append({"path": rel, "bytes": int(st.st_size)})
            if total_files >= max_walk_files:
                truncated = True
                break
        if truncated:
            break

    top_ext = [{"ext": ext, "count": int(cnt)} for ext, cnt in ext_counter.most_common(10)]
    return {
        "root": str(path),
        "files": int(total_files),
        "dirs": int(total_dirs),
        "bytes": int(total_bytes),
        "top_extensions": top_ext,
        "sample_files": sample_files,
        "truncated": truncated,
    }


def format_upload_summary(info: Dict, lang: str = "es") -> str:
    es = (lang or "es").lower().startswith("es")
    root = info.get("root") or "?"
    files = int(info.get("files") or 0)
    dirs = int(info.get("dirs") or 0)
    size_mb = round((int(info.get("bytes") or 0)) / (1024 * 1024), 2)
    top_ext = info.get("top_extensions") or []
    sample_files = info.get("sample_files") or []
    truncated = bool(info.get("truncated"))

    ext_line = ", ".join(f"{row.get('ext')}: {row.get('count')}" for row in top_ext[:6]) or "-"
    lines = [
        f"{'Resumen de proyecto' if es else 'Project summary'}",
        f"{'Ruta' if es else 'Path'}: {root}",
        f"{'Archivos' if es else 'Files'}: {files} | {'Carpetas' if es else 'Dirs'}: {dirs} | {'Tamaño' if es else 'Size'}: ~{size_mb} MB",
        f"{'Extensiones top' if es else 'Top extensions'}: {ext_line}",
    ]

    if sample_files:
        lines.append("")
        lines.append("Muestra de archivos:" if es else "Sample files:")
        for row in sample_files[:30]:
            lines.append(f"- {row.get('path')} ({row.get('bytes')} B)")

    if truncated:
        lines.append("")
        lines.append(
            "Nota: listado truncado para mantener respuesta rápida."
            if es
            else "Note: listing truncated to keep response fast."
        )

    return "\n".join(lines)
