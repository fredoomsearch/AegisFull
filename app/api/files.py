from __future__ import annotations

"""
Canonical project/files API surface.

Why this module exists:
- Provide deterministic project lifecycle under `/files/*` (upload/clone/register/ingest/introspection).
- Keep path safety guarantees centralized (workspace and upload root guards).
- Expose read-friendly project tools used by chat/agent flows.
"""

import io
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import require_files_api_key
from app.services.antivirus_service import clamav_status, recent_av_events, record_av_event
from app.services.job_manager import (
    finish_stage,
    get_job,
    list_jobs,
    serialize_job,
    start_job,
    start_stage,
)
from app.services.project_manifest import (
    infer_file_focus,
    load_project_manifest,
    summarize_manifest,
)
from app.services.project_introspection import (
    build_project_impact_report,
    build_project_improvement_ideas,
    build_project_intelligence_summary,
    build_symbol_rename_plan,
    fuzzy_search_project_files,
    scan_project_symbols,
    summarize_architecture,
)
from app.services.project_store import (
    delete_project as delete_registered_project,
    delete_project_by_path,
    ensure_project_for_path,
    get_project,
    get_project_by_path,
    list_projects,
    register_project,
    update_project,
)
from app.services.upload_inspector import (
    format_upload_summary,
    inspect_upload_tree,
    remember_last_upload,
    resolve_upload_path,
)

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(require_files_api_key)])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Component: runtime config + safety boundaries
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INGEST_SCRIPT = (PROJECT_ROOT / "app/scripts/ingest_repo.py").resolve()
UPLOAD_ROOT = Path(os.getenv("FILES_UPLOAD_ROOT", "data/uploads")).resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.getenv("FILES_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))  # 50MB default
INGEST_TIMEOUT = int(os.getenv("FILES_INGEST_TIMEOUT", "2000"))
INGEST_LOG_DIR = Path(os.getenv("FILES_INGEST_LOG_DIR", "logs")).resolve()
ALLOWED_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
FILES_AV_SCAN = os.getenv("FILES_AV_SCAN", "1") != "0"
FILES_AV_TIMEOUT = int(os.getenv("FILES_AV_TIMEOUT", "15"))
FILES_AV_FAIL_OPEN = os.getenv("FILES_AV_FAIL_OPEN", "1") != "0"
FILES_AV_RETRIES = max(0, int(os.getenv("FILES_AV_RETRIES", "1") or "1"))
FILES_ALLOW_ROOT_PARAM = (os.getenv("FILES_ALLOW_ROOT_PARAM", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
FILES_MAX_EDIT_BYTES = int(os.getenv("FILES_MAX_EDIT_BYTES", str(2 * 1024 * 1024)))

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._\-/]+$")
_EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "venv",
    ".venv",
}
_EXCLUDED_FILES = {"aegis.db"}


def ensure_under_upload_root(p: Path) -> Path:
    """Guarantee a path stays inside FILES_UPLOAD_ROOT."""
    resolved = p.resolve()
    # safer than string startswith
    if resolved != UPLOAD_ROOT and UPLOAD_ROOT not in resolved.parents:
        raise HTTPException(status_code=400, detail="Path outside allowed upload root")
    return resolved


def _ensure_under_project_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != PROJECT_ROOT and PROJECT_ROOT not in resolved.parents:
        raise HTTPException(status_code=400, detail="Path outside project root")
    return resolved


def _is_under_upload_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    return resolved != UPLOAD_ROOT and UPLOAD_ROOT in resolved.parents


def _resolve_registered_project_root(project: Dict[str, Any]) -> Path:
    root_value = str(project.get("root_path") or "").strip()
    if not root_value:
        raise HTTPException(status_code=404, detail="Project root not found")
    raw = Path(root_value)
    if _is_under_upload_root(raw):
        return ensure_under_upload_root(raw)
    return _ensure_under_project_root(raw)


def _project_root_from_query(
    *,
    project_id: Optional[str] = None,
    root: Optional[str] = None,
) -> tuple[Path, Optional[Dict[str, Any]]]:
    """Resolve a canonical project root from project_id (preferred) or root (aux)."""
    if project_id:
        project = get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        root_path = _resolve_registered_project_root(project)
        return root_path, project
    root_value = (root or ".").strip() or "."
    return _ensure_under_project_root(PROJECT_ROOT / root_value), None


def _relative_to_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path.resolve())


def _read_utf8_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="File is not a UTF-8 text file") from exc


def _write_utf8_text(path: Path, content: str) -> None:
    payload = str(content or "")
    payload_bytes = len(payload.encode("utf-8"))
    if payload_bytes > FILES_MAX_EDIT_BYTES:
        raise HTTPException(status_code=413, detail="Edited file exceeds max allowed size")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{uuid.uuid4().hex}")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def _note_diff(summary: str, *details: str) -> str:
    lines = [f"# {summary}"]
    for detail in details:
        detail_text = str(detail or "").strip()
        if detail_text:
            lines.append(f"# {detail_text}")
    return "\n".join(lines) + "\n"


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    current = path.parent
    stop_resolved = stop_at.resolve()
    while current != stop_resolved and stop_resolved in current.resolve().parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _stable_batch_ops_payload(operations: List["BatchApplyOperation"]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in operations:
        normalized.append(
            {
                "op": str(item.op or "").strip().lower(),
                "path": str(item.path or "").strip(),
                "content": str(item.content or ""),
                "new_path": str(item.new_path or "").strip() or None,
                "create": bool(item.create),
            }
        )
    return normalized


def _batch_review_token(operations: List["BatchApplyOperation"]) -> str:
    payload = json.dumps(_stable_batch_ops_payload(operations), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preview_batch_operation(
    *,
    item: "BatchApplyOperation",
    project_id: Optional[str],
    root: Optional[str],
) -> Dict[str, Any]:
    op = str(item.op or "").strip().lower()
    if op == "write":
        file_path = _resolve_project_text_file_path(path=item.path, project_id=project_id, root=root)
        file_exists = file_path.exists()
        if file_exists and not file_path.is_file():
            raise HTTPException(status_code=400, detail="Target path is not a file")
        if not file_exists and not item.create:
            raise HTTPException(status_code=404, detail="File not found")
        current_text = _read_utf8_text(file_path) if file_exists else ""
        proposed_text = str(item.content or "")
        diff_text = "".join(
            unified_diff(
                current_text.splitlines(keepends=True),
                proposed_text.splitlines(keepends=True),
                fromfile=_relative_to_workspace(file_path) if file_exists else f"a/{item.path}",
                tofile=_relative_to_workspace(file_path) if file_exists else f"b/{item.path}",
                lineterm="",
            )
        )
        summary = (
            f"Create file {_relative_to_workspace(file_path)}"
            if item.create and not file_exists
            else f"Update file {_relative_to_workspace(file_path)}"
        )
        if not diff_text:
            diff_text = _note_diff(summary, "No textual changes")
        return {
            "op": op,
            "path": _relative_to_workspace(file_path) if file_exists else str(item.path).strip(),
            "changed": current_text != proposed_text,
            "summary": summary,
            "diff": diff_text,
        }
    if op == "delete":
        file_path = _resolve_project_text_file_path(path=item.path, project_id=project_id, root=root)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        current_text = _read_utf8_text(file_path)
        diff_text = "".join(
            unified_diff(
                current_text.splitlines(keepends=True),
                [],
                fromfile=_relative_to_workspace(file_path),
                tofile="/dev/null",
                lineterm="",
            )
        )
        if not diff_text:
            diff_text = _note_diff(f"Delete file {_relative_to_workspace(file_path)}")
        return {
            "op": op,
            "path": _relative_to_workspace(file_path),
            "changed": True,
            "summary": f"Delete file {_relative_to_workspace(file_path)}",
            "diff": diff_text,
        }
    if op == "mkdir":
        dir_path = _resolve_project_path(path=item.path, project_id=project_id, root=root)
        if dir_path.exists() and not dir_path.is_dir():
            raise HTTPException(status_code=400, detail="Target path already exists as a file")
        created = not dir_path.exists()
        summary = (
            f"Create directory {_relative_to_workspace(dir_path)}"
            if created
            else f"Directory already exists: {_relative_to_workspace(dir_path)}"
        )
        return {
            "op": op,
            "path": _relative_to_workspace(dir_path),
            "changed": created,
            "summary": summary,
            "diff": _note_diff(summary),
        }
    if op == "move":
        src_path = _resolve_project_path(path=item.path, project_id=project_id, root=root)
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        dest_clean = str(item.new_path or "").strip()
        if not dest_clean:
            raise HTTPException(status_code=400, detail="Missing new_path")
        dest_path = _resolve_project_path(path=dest_clean, project_id=project_id, root=root)
        if dest_path.exists():
            raise HTTPException(status_code=409, detail="Target path already exists")
        if src_path.is_dir():
            try:
                src_resolved = src_path.resolve()
                dest_resolved = dest_path.resolve(strict=False)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid move target: {exc}") from exc
            if dest_resolved == src_resolved or src_resolved in dest_resolved.parents:
                raise HTTPException(status_code=400, detail="Cannot move a directory into itself")
        summary = f"Move {_relative_to_workspace(src_path)} -> {_relative_to_workspace(dest_path)}"
        return {
            "op": op,
            "path": _relative_to_workspace(src_path),
            "new_path": _relative_to_workspace(dest_path),
            "changed": src_path != dest_path,
            "summary": summary,
            "diff": _note_diff(summary, "Content is unchanged; only the path moves."),
        }
    raise HTTPException(status_code=400, detail=f"Unsupported batch op: {item.op}")


def _build_batch_preview(
    *,
    operations: List["BatchApplyOperation"],
    project_id: Optional[str],
    root: Optional[str],
) -> Dict[str, Any]:
    items = [
        {
            "index": idx,
            **_preview_batch_operation(item=item, project_id=project_id, root=root),
        }
        for idx, item in enumerate(operations)
    ]
    combined_diff = "\n".join(
        str(item.get("diff") or "").rstrip()
        for item in items
        if str(item.get("diff") or "").strip()
    ).strip()
    return {
        "status": "ok",
        "review_token": _batch_review_token(operations),
        "items": items,
        "combined_diff": combined_diff,
        "operation_count": len(items),
        "changed_count": sum(1 for item in items if item.get("changed")),
    }


def _prepare_batch_undo(
    *,
    item: "BatchApplyOperation",
    project_id: Optional[str],
    root: Optional[str],
) -> Dict[str, Any]:
    op = str(item.op or "").strip().lower()
    if op == "write":
        file_path = _resolve_project_text_file_path(path=item.path, project_id=project_id, root=root)
        existed = file_path.exists()
        if existed and not file_path.is_file():
            raise HTTPException(status_code=400, detail="Target path is not a file")
        if not existed and not item.create:
            raise HTTPException(status_code=404, detail="File not found")
        return {
            "op": op,
            "path": str(item.path or "").strip(),
            "target_path": _relative_to_workspace(file_path),
            "existed": existed,
            "content": _read_utf8_text(file_path) if existed else "",
        }
    if op == "delete":
        file_path = _resolve_project_text_file_path(path=item.path, project_id=project_id, root=root)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return {
            "op": op,
            "path": str(item.path or "").strip(),
            "target_path": _relative_to_workspace(file_path),
            "content": _read_utf8_text(file_path),
        }
    if op == "mkdir":
        dir_path = _resolve_project_path(path=item.path, project_id=project_id, root=root)
        if dir_path.exists() and not dir_path.is_dir():
            raise HTTPException(status_code=400, detail="Target path already exists as a file")
        return {
            "op": op,
            "path": str(item.path or "").strip(),
            "target_path": _relative_to_workspace(dir_path),
            "created": not dir_path.exists(),
        }
    if op == "move":
        src_path = _resolve_project_path(path=item.path, project_id=project_id, root=root)
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        dest_clean = str(item.new_path or "").strip()
        if not dest_clean:
            raise HTTPException(status_code=400, detail="Missing new_path")
        dest_path = _resolve_project_path(path=dest_clean, project_id=project_id, root=root)
        if dest_path.exists():
            raise HTTPException(status_code=409, detail="Target path already exists")
        if src_path.is_dir():
            try:
                src_resolved = src_path.resolve()
                dest_resolved = dest_path.resolve(strict=False)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid move target: {exc}") from exc
            if dest_resolved == src_resolved or src_resolved in dest_resolved.parents:
                raise HTTPException(status_code=400, detail="Cannot move a directory into itself")
        return {
            "op": op,
            "path": str(item.path or "").strip(),
            "new_path": dest_clean,
            "target_path": _relative_to_workspace(src_path),
            "rollback_path": _relative_to_workspace(dest_path),
        }
    raise HTTPException(status_code=400, detail=f"Unsupported batch op: {item.op}")


async def _rollback_batch_operations(
    undos: List[Dict[str, Any]],
    *,
    project_id: Optional[str],
    root: Optional[str],
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    ok = True
    project_root, _project = _project_root_from_query(project_id=project_id, root=root)
    for undo in reversed(undos):
        op = str(undo.get("op") or "").strip().lower()
        try:
            if op == "write":
                file_path = _resolve_project_text_file_path(path=str(undo.get("path") or ""), project_id=project_id, root=root)
                if undo.get("existed"):
                    _write_utf8_text(file_path, str(undo.get("content") or ""))
                elif file_path.exists():
                    file_path.unlink()
                    _prune_empty_parents(file_path, project_root)
                results.append({"op": op, "path": undo.get("target_path"), "rolled_back": True})
            elif op == "delete":
                file_path = _resolve_project_text_file_path(path=str(undo.get("path") or ""), project_id=project_id, root=root)
                _write_utf8_text(file_path, str(undo.get("content") or ""))
                results.append({"op": op, "path": undo.get("target_path"), "rolled_back": True})
            elif op == "mkdir":
                if undo.get("created"):
                    dir_path = _resolve_project_path(path=str(undo.get("path") or ""), project_id=project_id, root=root)
                    if dir_path.exists() and dir_path.is_dir():
                        shutil.rmtree(dir_path)
                results.append({"op": op, "path": undo.get("target_path"), "rolled_back": True})
            elif op == "move":
                dest_path = _resolve_project_path(path=str(undo.get("new_path") or ""), project_id=project_id, root=root)
                src_path = _resolve_project_path(path=str(undo.get("path") or ""), project_id=project_id, root=root)
                if dest_path.exists():
                    src_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dest_path), str(src_path))
                results.append({"op": op, "path": undo.get("rollback_path"), "rolled_back": True})
            else:
                raise RuntimeError(f"unsupported-rollback-op:{op}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            results.append(
                {
                    "op": op,
                    "path": undo.get("target_path") or undo.get("rollback_path"),
                    "rolled_back": False,
                    "error": str(exc),
                }
            )
    return {"ok": ok, "results": results}


def _ensure_within_root(root: Path, candidate: Path) -> Path:
    """
    Ensure `candidate` resolves under `root` (prevents ../ traversal escaping project roots).
    """
    try:
        root_resolved = root.resolve()
        cand_resolved = candidate.resolve()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc

    if cand_resolved == root_resolved or root_resolved in cand_resolved.parents:
        return cand_resolved
    raise HTTPException(status_code=400, detail="Path outside project root")


def _normalize_project_relative_content_path(
    project_root: Path,
    clean_path: str,
    *,
    project_id: Optional[str] = None,
) -> str:
    """
    Normalize project content paths that may include workspace/project prefixes.

    Accepted variants (all become project-relative):
    - app/service.py
    - <project_id>/app/service.py
    - data/uploads/<project_id>/app/service.py
    """
    normalized = str(clean_path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    if not normalized:
        return normalized

    root_resolved = project_root.resolve()
    root_rel = _relative_to_workspace(root_resolved).replace("\\", "/").strip("/")
    prefixes: List[str] = []
    if root_rel:
        prefixes.append(root_rel)
    if project_id:
        prefixes.append(str(project_id).replace("\\", "/").strip("/"))
    if root_resolved.name:
        prefixes.append(root_resolved.name)

    lowered = normalized.lower()
    for prefix in prefixes:
        pref = str(prefix or "").strip("/")
        if not pref:
            continue
        pref_low = pref.lower()
        if lowered == pref_low:
            return ""
        if lowered.startswith(pref_low + "/"):
            normalized = normalized[len(pref) + 1 :].lstrip("/")
            lowered = normalized.lower()

    # If caller already passed a workspace-relative path under this root,
    # collapse it to a project-relative path.
    try:
        workspace_candidate = _ensure_under_project_root(PROJECT_ROOT / normalized)
        if workspace_candidate == root_resolved or root_resolved in workspace_candidate.parents:
            normalized = workspace_candidate.relative_to(root_resolved).as_posix()
    except HTTPException:
        pass
    except Exception:
        pass

    return normalized


def _build_tree_node(root: Path, *, max_depth: int = 4, depth: int = 0) -> "TreeNode":
    node = TreeNode(
        name=root.name or _relative_to_workspace(root),
        path=_relative_to_workspace(root),
        type="dir",
        is_dir=True,
        children=[],
    )
    if depth >= max_depth:
        return node
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        entries = []

    for entry in entries:
        if entry.is_dir() and entry.name in _EXCLUDED_DIRS:
            continue
        if entry.is_file() and entry.name in _EXCLUDED_FILES:
            continue
        if entry.is_dir():
            node.children.append(_build_tree_node(entry, max_depth=max_depth, depth=depth + 1))
        else:
            node.children.append(
                TreeNode(
                    name=entry.name,
                    path=_relative_to_workspace(entry),
                    type="file",
                    is_dir=False,
                    children=None,
                )
            )
    return node


def _resolve_project_path(
    *,
    path: str,
    project_id: Optional[str] = None,
    root: Optional[str] = None,
) -> Path:
    clean_path = str(path or "").strip()
    if not clean_path:
        raise HTTPException(status_code=400, detail="Missing path")

    if project_id:
        project_root, project = _project_root_from_query(project_id=project_id, root=None)
        normalized_path = _normalize_project_relative_content_path(
            project_root,
            clean_path,
            project_id=str((project or {}).get("project_id") or project_id),
        )
        candidate = _ensure_within_root(project_root, project_root / normalized_path)
        return ensure_under_upload_root(candidate) if _is_under_upload_root(project_root) else _ensure_under_project_root(candidate)

    if root:
        if not FILES_ALLOW_ROOT_PARAM:
            raise HTTPException(status_code=400, detail="Use project_id (register a root) instead of root= for browsing.")
        root_path, _project = _project_root_from_query(project_id=None, root=root)
        candidate = _ensure_within_root(root_path, root_path / clean_path)
        return ensure_under_upload_root(candidate) if _is_under_upload_root(root_path) else _ensure_under_project_root(candidate)

    if not FILES_ALLOW_ROOT_PARAM:
        raise HTTPException(status_code=400, detail="Use project_id (register a root) instead of browsing repository paths.")
    return _ensure_under_project_root(PROJECT_ROOT / clean_path)


def _resolve_project_text_file_path(
    *,
    path: str,
    project_id: Optional[str] = None,
    root: Optional[str] = None,
) -> Path:
    return _resolve_project_path(path=path, project_id=project_id, root=root)


def _ensure_git_exists() -> None:
    if shutil.which("git") is None:
        raise HTTPException(status_code=500, detail="git is not installed on this system")


def _project_manifest_or_404(project_id: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    manifest = load_project_manifest(project.get("manifest_path") or project.get("root_path") or "")
    if not manifest:
        raise HTTPException(status_code=404, detail="Project manifest not found")
    return project, manifest


def _normalize_project_query_focus(project_root: Path, project_id: str, q: str) -> str:
    query = str(q or "").strip()
    if not query:
        return ""
    normalized = _normalize_project_relative_content_path(project_root, query, project_id=project_id)
    if normalized:
        candidate = project_root / normalized
        try:
            if candidate.exists():
                return normalized
        except Exception:
            pass
    return query


def _guess_python_app_target(manifest: Dict[str, Any]) -> tuple[str, str]:
    file_tree = [str(path) for path in (manifest.get("file_tree") or []) if isinstance(path, str)]
    frameworks = {str(item).lower() for item in (manifest.get("frameworks") or []) if isinstance(item, str)}
    if "main.py" in file_tree:
        return "main", "app"
    if "app.py" in file_tree:
        return "app", "app"
    if "fastapi" in frameworks:
        return "main", "app"
    return "main", "app"


def _build_supported_idea_starter_ops(manifest: Dict[str, Any], idea_id: str) -> List[BatchApplyOperation]:
    idea = str(idea_id or "").strip().lower()
    file_tree = {str(path) for path in (manifest.get("file_tree") or []) if isinstance(path, str)}
    frameworks = {str(item).lower() for item in (manifest.get("frameworks") or []) if isinstance(item, str)}
    project_id = str(manifest.get("project_id") or "project").strip() or "project"

    if idea == "readme":
        lines = [
            f"# {project_id}",
            "",
            "## Overview",
            "",
            "Describe the purpose of this project here.",
            "",
            "## Local Run",
            "",
            "1. Install dependencies.",
            "2. Configure environment variables.",
            "3. Start the main runtime.",
            "",
            "## Architecture",
            "",
            "- Main entrypoints: update this section with the real startup files.",
            "- Main dependencies: update this section with the critical services.",
            "",
            "## Validation",
            "",
            "- Add the commands required for smoke tests and strict verification.",
            "",
        ]
        return [
            BatchApplyOperation(
                op="write",
                path="README.md",
                content="\n".join(lines),
                create=True,
            )
        ]

    if idea == "ci":
        workflow = "\n".join(
            [
                "name: CI",
                "",
                "on:",
                "  push:",
                "  pull_request:",
                "",
                "jobs:",
                "  test:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: actions/setup-python@v5",
                "        with:",
                "          python-version: '3.11'",
                "      - name: Install dependencies",
                "        run: |",
                "          python -m pip install --upgrade pip",
                "          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi",
                "          if [ -f requirements-dev.txt ]; then pip install -r requirements-dev.txt; fi",
                "          if [ -f pyproject.toml ]; then pip install .; fi",
                "          pip install pytest",
                "      - name: Run tests",
                "        run: pytest -q",
                "",
            ]
        )
        return [
            BatchApplyOperation(
                op="mkdir",
                path=".github/workflows",
            ),
            BatchApplyOperation(
                op="write",
                path=".github/workflows/ci.yml",
                content=workflow,
                create=True,
            ),
        ]

    if idea == "tests":
        module_name, app_name = _guess_python_app_target(manifest)
        if "fastapi" in frameworks or any(path.endswith(".py") for path in file_tree):
            body = "\n".join(
                [
                    "from fastapi.testclient import TestClient",
                    "",
                    f"from {module_name} import {app_name}",
                    "",
                    f"client = TestClient({app_name})",
                    "",
                    "",
                    "def test_healthz_smoke():",
                    '    resp = client.get("/healthz")',
                    "    assert resp.status_code == 200",
                    "",
                ]
            )
        else:
            body = "\n".join(
                [
                    "def test_smoke_placeholder():",
                    "    assert True",
                    "",
                ]
            )
        return [
            BatchApplyOperation(op="mkdir", path="tests"),
            BatchApplyOperation(
                op="write",
                path="tests/test_smoke.py",
                content=body,
                create=True,
            ),
        ]

    raise HTTPException(status_code=400, detail="Idea starter not supported")


def validate_repo_url(repo_url: str) -> str:
    u = (repo_url or "").strip()
    if not u:
        raise HTTPException(status_code=400, detail="repo_url is required")

    p = urlparse(u)
    if (p.scheme or "").lower() != "https":
        raise HTTPException(status_code=400, detail="Only HTTPS repo URLs are allowed")

    host = (p.netloc or "").lower()
    if host not in ALLOWED_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=f"Only repos from {', '.join(sorted(ALLOWED_HOSTS))} are allowed",
        )

    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Repo URL must look like https://host/user/repo")

    # allow optional .git (DO NOT require it)
    return u


def _normalize_branch(branch: Optional[str]) -> Optional[str]:
    if not branch:
        return None
    b = branch.strip()

    # UI sometimes sends "(Main)" / "(master)" / "(0)" / "Master"
    if b.startswith("(") and b.endswith(")"):
        b = b[1:-1].strip()

    if not b or b.isdigit():
        return None

    low = b.lower()
    if low in {"main", "master"}:
        return low

    if not _SAFE_BRANCH.match(b):
        return None

    return b


def _detect_default_branch(repo_url: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "ls-remote", "--symref", repo_url, "HEAD"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
        )
        # Example: "ref: refs/heads/main\tHEAD"
        for line in out.splitlines():
            if line.startswith("ref: ") and "\tHEAD" in line:
                ref = line.split()[1].strip()
                if ref.startswith("refs/heads/"):
                    return ref.replace("refs/heads/", "").strip()
    except Exception:
        return None
    return None


def _dir_size_mb(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return int(total / (1024 * 1024))


def _av_scan_error_or_open(status: str, detail: str) -> str:
    if FILES_AV_FAIL_OPEN:
        logger.warning("AV scan fail-open (%s): %s", status, detail)
        return f"fail-open:{status}"
    raise HTTPException(status_code=400, detail=detail)


def _av_scan_path(path: Path) -> str:
    """
    Run a lightweight AV scan (clamdscan/clamscan) on the given path.
    Skips silently if disabled or scanner not found.
    Raises HTTPException on infection or scanner failure.
    """
    scanner_info = clamav_status()
    scanner_name = str(scanner_info.get("scanner") or "")
    started = time.monotonic()
    if not FILES_AV_SCAN:
        record_av_event(path=str(path), status="disabled", detail="AV scan disabled", scanner=scanner_name)
        return "disabled"
    if not path.exists():
        record_av_event(path=str(path), status="missing", detail="Scan target missing", scanner=scanner_name)
        return "missing"

    scanner = shutil.which("clamdscan") or shutil.which("clamscan")
    if not scanner:
        record_av_event(path=str(path), status="scanner-not-found", detail="Scanner not found", scanner=scanner_name)
        return "scanner-not-found"

    size_mb = _dir_size_mb(path)
    # If already too large per upload caps, we would have rejected earlier.
    # Avoid long scans on unexpectedly large trees.
    if size_mb > (MAX_UPLOAD_BYTES // (1024 * 1024) * 2):  # heuristic guard
        status = _av_scan_error_or_open("tree-too-large", "AV scan skipped: tree too large")
        record_av_event(path=str(path), status=status, detail="AV scan skipped: tree too large", scanner=scanner_name)
        return status

    cmd = [scanner, "--infected", "--no-summary", str(path)]
    if "clamdscan" in scanner:
        cmd.insert(1, "--fdpass")

    max_attempts = FILES_AV_RETRIES + 1
    res = None
    for attempt in range(max_attempts):
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=FILES_AV_TIMEOUT,
                check=False,
            )
            break
        except subprocess.TimeoutExpired:
            if attempt + 1 < max_attempts:
                logger.warning(
                    "AV scan timeout (attempt %s/%s), retrying: %s",
                    attempt + 1,
                    max_attempts,
                    path,
                )
                continue
            status = _av_scan_error_or_open("timeout", "AV scan timed out")
            record_av_event(
                path=str(path),
                status=status,
                detail=f"AV scan timed out after {max_attempts} attempt(s)",
                scanner=scanner_name,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            return status
        except Exception:
            # Do not block if scanner crashes; treat as failed scan.
            status = _av_scan_error_or_open("failed", "AV scan failed")
            record_av_event(
                path=str(path),
                status=status,
                detail="AV scan failed",
                scanner=scanner_name,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            return status
    if res is None:
        status = _av_scan_error_or_open("failed", "AV scan failed")
        record_av_event(
            path=str(path),
            status=status,
            detail="AV scan failed",
            scanner=scanner_name,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        return status

    # clamscan/clamdscan: 0=clean, 1=infected, 2=error
    output = (res.stdout or "").strip()
    if res.returncode == 0:
        record_av_event(
            path=str(path),
            status="clean",
            detail=output or "clean",
            scanner=scanner_name,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        return "clean"
    if res.returncode == 1:
        record_av_event(
            path=str(path),
            status="infected",
            detail=output or "infected",
            scanner=scanner_name,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        raise HTTPException(status_code=400, detail=f"Malware detected: {output or 'infected'}")
    status = _av_scan_error_or_open("scan-error", f"AV scan error: {output or 'scan error'}")
    record_av_event(
        path=str(path),
        status=status,
        detail=output or "scan error",
        scanner=scanner_name,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    return status


# ============================================================================
# Request models
# ============================================================================

class IngestRequest(BaseModel):
    path: Optional[str] = None
    background: bool = False
    project_id: Optional[str] = None


class CloneRequest(BaseModel):
    repo_url: str
    branch: Optional[str] = None
    depth: int = Field(1, ge=1, le=50)
    max_mb: int = Field(300, ge=10, le=2000)  # soft limit


class RegisterRootRequest(BaseModel):
    path: str
    project_id: Optional[str] = None


class SaveContentRequest(BaseModel):
    path: str
    content: str
    project_id: Optional[str] = None
    root: Optional[str] = None
    create: bool = False


class RenameContentRequest(BaseModel):
    path: str
    new_path: str
    project_id: Optional[str] = None
    root: Optional[str] = None


class DeleteContentRequest(BaseModel):
    path: str
    project_id: Optional[str] = None
    root: Optional[str] = None


class CreateDirectoryRequest(BaseModel):
    path: str
    project_id: Optional[str] = None
    root: Optional[str] = None


class MovePathRequest(BaseModel):
    path: str
    new_path: str
    project_id: Optional[str] = None
    root: Optional[str] = None


class BatchApplyOperation(BaseModel):
    op: str
    path: str
    content: str = ""
    new_path: Optional[str] = None
    create: bool = False


class BatchApplyRequest(BaseModel):
    project_id: Optional[str] = None
    root: Optional[str] = None
    operations: List[BatchApplyOperation] = Field(default_factory=list)
    review_token: Optional[str] = None


class SymbolRenamePlanRequest(BaseModel):
    symbol: str
    new_symbol: str
    limit: int = 20


class TreeNode(BaseModel):
    name: str
    path: str
    type: str
    is_dir: bool | None = None
    children: List["TreeNode"] | None = None


TreeNode.model_rebuild()


class DeleteProjectRequest(BaseModel):
    path: Optional[str] = None
    project_id: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/upload-zip")
async def upload_zip(
    file: UploadFile = File(...),
    project_name: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """
    What it does:
    - Creates a registered project from a ZIP upload.

    Why it exists:
    - Canonical intake path for user project data before ingest/indexing.

    Called from ->
    - Files panel upload flow and E2E smoke checks

    Calls ->
    - zip extraction + zip-slip validation
    - antivirus scan helper
    - project registry and upload-state services

    Failure/guard behavior:
    - Rejects non-zip payloads, oversized files, and traversal entries.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip")

    raw_name = project_name or file.filename.rsplit(".", 1)[0]
    safe_name = _SAFE_NAME.sub("_", raw_name).strip("_") or "project"
    project_id = f"{safe_name}_{uuid.uuid4().hex[:6]}"

    dest = ensure_under_upload_root(UPLOAD_ROOT / project_id)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    buf = await file.read()
    if MAX_UPLOAD_BYTES and len(buf) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Zip too large")

    try:
        with zipfile.ZipFile(io.BytesIO(buf)) as zf:
            for member in zf.infolist():
                member_norm = member.filename.replace("\\", "/")

                # zip-slip protection
                if member_norm.startswith("/") or ".." in Path(member_norm).parts:
                    raise HTTPException(status_code=400, detail="Invalid zip entry")

                target = ensure_under_upload_root(dest / member_norm)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
        av_status = _av_scan_path(dest)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Corrupt or invalid zip")

    remember_last_upload(dest, source="upload-zip")
    register_project(project_id, dest, source="upload-zip", status="uploaded")

    return {
        "status": "ok",
        "project_id": project_id,
        "path": str(dest),
        "av_status": av_status,
        "hint": "Now call /files/ingest with this path.",
    }


@router.post("/clone")
async def clone_repo(payload: CloneRequest) -> Dict[str, Any]:
    """
    What it does:
    - Clones a public repository into upload storage and registers it as a project.

    Why it exists:
    - Provide deterministic repo onboarding path equivalent to zip upload.

    Called from ->
    - Files panel "Clone repo" flow
    - smoke/e2e project bootstrap scenarios

    Calls ->
    - git clone subprocess with safe branch/depth constraints
    - AV scan + project registry + upload-memory tracking

    Failure/guard behavior:
    - Rejects non-allowed hosts/branches and oversize clones.
    """
    _ensure_git_exists()

    repo_url = validate_repo_url(payload.repo_url)
    branch = _normalize_branch(payload.branch)
    depth = int(payload.depth or 1)

    # project folder
    repo_name = Path(repo_url.rstrip("/")).name.replace(".git", "") or "repo"
    repo_name = _SAFE_NAME.sub("_", repo_name).strip("_") or "repo"
    project_id = f"{repo_name}_{uuid.uuid4().hex[:6]}"
    dest = ensure_under_upload_root(UPLOAD_ROOT / project_id)

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"  # never hang waiting for credentials

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=120,
            check=False,
        )

    # if no branch provided, try default-branch detection
    if not branch:
        branch = _detect_default_branch(repo_url)

    # Attempt 1: clone specifying branch (if we have one)
    if branch:
        cmd1 = ["git", "clone", "--depth", str(depth), "--single-branch", "--branch", branch, repo_url, str(dest)]
        r1 = run(cmd1)
        if r1.returncode == 0:
            size_mb = _dir_size_mb(dest)
            if size_mb > payload.max_mb:
                shutil.rmtree(dest, ignore_errors=True)
                raise HTTPException(status_code=413, detail=f"Repo too large ({size_mb} MB). Increase max_mb or use smaller depth.")
            av_status = _av_scan_path(dest)
            remember_last_upload(dest, source="clone")
            register_project(project_id, dest, source="clone", status="uploaded", metadata={"repo_url": repo_url})
            return {
                "status": "ok",
                "project_id": project_id,
                "path": str(dest),
                "branch_used": branch,
                "av_status": av_status,
            }

    # Attempt 2: clone without specifying branch (lets git choose default)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    cmd2 = ["git", "clone", "--depth", str(depth), repo_url, str(dest)]
    r2 = run(cmd2)
    if r2.returncode != 0:
        raise HTTPException(status_code=400, detail=f"git clone failed:\n{(r2.stdout or '')[:3000]}")

    used = _detect_default_branch(repo_url) or branch or "unknown"
    size_mb = _dir_size_mb(dest)
    if size_mb > payload.max_mb:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=413, detail=f"Repo too large ({size_mb} MB). Increase max_mb or use smaller depth.")

    av_status = _av_scan_path(dest)
    remember_last_upload(dest, source="clone")
    register_project(project_id, dest, source="clone", status="uploaded", metadata={"repo_url": repo_url})

    return {
        "status": "ok",
        "project_id": project_id,
        "path": str(dest),
        "branch_used": used,
        "av_status": av_status,
    }


@router.post("/register-root")
async def register_root(payload: RegisterRootRequest) -> Dict[str, Any]:
    """
    What it does:
    - Registers an existing local directory as a canonical project root.

    Why it exists:
    - Allow workspace-native projects to use the same `/files/*` tooling without upload/clone.

    Called from ->
    - Files panel local-root registration action
    - manual ops/runtime setup flows

    Calls ->
    - workspace/upload root guards
    - canonical project registry + upload-memory tracker

    Failure/guard behavior:
    - Denies paths outside allowed workspace roots.
    """
    raw = Path(payload.path)
    target = raw if raw.is_absolute() else (PROJECT_ROOT / raw)
    target = target.resolve()

    try:
        if _is_under_upload_root(target):
            target = ensure_under_upload_root(target)
        else:
            target = _ensure_under_project_root(target)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Path outside allowed workspace roots")

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    project_id = str((payload.project_id or "").strip() or target.name)
    project = register_project(project_id, target, source="workspace", status="uploaded")
    remember_last_upload(target, source="register-root")
    return {
        "status": "ok",
        "project_id": str(project.get("project_id") or project_id),
        "path": str(target),
        "hint": "Now call /files/ingest with this project_id or path if you want indexed retrieval.",
    }


@router.post("/ingest")
async def ingest_path(body: IngestRequest) -> Dict[str, Any]:
    """
    What it does:
    - Runs ingest pipeline for a registered/local project path and stores manifest.

    Why it exists:
    - Converts uploaded/cloned source trees into searchable project context.

    Called from ->
    - Files ingest UI actions
    - startup/e2e contract checks

    Calls ->
    - app/scripts/ingest_repo.py subprocess
    - project manifest loader + project registry updates
    - optional job manager for background mode

    Failure/guard behavior:
    - Returns `504` on ingest timeout and `500` on ingest execution errors.
    """
    project = get_project(str(body.project_id or "").strip()) if body.project_id else None
    p: Path
    if project:
        p = _resolve_registered_project_root(project)
    else:
        raw_path = str(body.path or "").strip()
        if not raw_path:
            raise HTTPException(status_code=400, detail="path or project_id is required")
        raw = Path(raw_path)
        target = raw if raw.is_absolute() else (PROJECT_ROOT / raw)
        target = target.resolve()
        try:
            p = ensure_under_upload_root(target) if _is_under_upload_root(target) else _ensure_under_project_root(target)
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail="Path outside allowed workspace roots") from exc
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=400, detail="Path does not exist")
        project = get_project_by_path(p) or ensure_project_for_path(
            p,
            source="upload-zip" if _is_under_upload_root(p) else "workspace",
        )

    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="Path does not exist")
    project_id = str(project.get("project_id") or p.name)
    update_project(project_id, status="ingesting")

    def _run_ingest(log_file: Path, *, job_id: str | None = None) -> Dict[str, Any]:
        # Ingest can be heavy (chunk + embed + index); keep timeout configurable.
        if not INGEST_SCRIPT.exists():
            update_project(project_id, status="error")
            raise RuntimeError(f"ingest script not found: {INGEST_SCRIPT}")
        manifest_path = p / ".aegis_manifest.json"
        cmd = [
            sys.executable or "python",
            str(INGEST_SCRIPT),
            "--root",
            str(p),
            "--project-id",
            project_id,
            "--manifest-out",
            str(manifest_path),
        ]
        INGEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        # Ensure ingest logs flush promptly for UI progress.
        env["PYTHONUNBUFFERED"] = "1"
        start = time.monotonic()
        if job_id:
            start_stage(job_id, "spawn_ingest_subprocess", detail="running app/scripts/ingest_repo.py")
        with log_file.open("a", encoding="utf-8") as lf:
            lf.write(f"[$] {' '.join(cmd)}\n")
            lf.flush()
            try:
                proc = subprocess.Popen(
                    cmd,
                    text=True,
                    stdout=lf,
                    stderr=lf,
                    env=env,
                    start_new_session=True,
                )
                while True:
                    rc = proc.poll()
                    if rc is not None:
                        break
                    if INGEST_TIMEOUT and time.monotonic() - start > INGEST_TIMEOUT:
                        proc.kill()
                        proc.wait(timeout=5)
                        raise RuntimeError("ingest timed out")
                    time.sleep(0.5)
            except RuntimeError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"ingest failed: {exc}") from exc

        if job_id:
            finish_stage(
                job_id,
                "spawn_ingest_subprocess",
                status="success" if proc.returncode == 0 else "error",
                detail=f"exit={proc.returncode}",
            )

        if proc.returncode != 0:
            update_project(project_id, status="error")
            raise RuntimeError("ingest failed (see log)")

        if job_id:
            start_stage(job_id, "load_manifest")
        manifest = load_project_manifest(manifest_path)
        if job_id:
            finish_stage(job_id, "load_manifest", status="success", detail="ok" if manifest else "missing")
        chunk_count = 0
        if isinstance(manifest, dict):
            stats = manifest.get("stats") if isinstance(manifest.get("stats"), dict) else {}
            chunk_count = int(stats.get("chunk_count") or 0)
        if job_id:
            start_stage(job_id, "update_project_registry")
        update_project(
            project_id,
            status="ingested",
            manifest_path=str(manifest_path),
            last_ingest_at=int(time.time()),
            chunk_count=chunk_count,
        )
        if job_id:
            finish_stage(job_id, "update_project_registry", status="success", detail=f"chunks={chunk_count}")

        return {
            "status": "ok",
            "project_id": project_id,
            "ingested_path": str(p),
            "manifest_path": str(manifest_path),
            "log_path": str(log_file),
        }

    if body.background:
        job_id = uuid.uuid4().hex[:10]
        log_file = INGEST_LOG_DIR / f"ingest_{job_id}.log"
        job = start_job(
            lambda: _run_ingest(log_file, job_id=job_id),
            kind="ingest",
            job_id=job_id,
            meta={"log_path": str(log_file), "path": str(p), "project_id": project_id},
        )
        return {"status": "queued", "job_id": job.id, "project_id": project_id}

    try:
        log_file = INGEST_LOG_DIR / f"ingest_sync_{uuid.uuid4().hex[:8]}.log"
        return _run_ingest(log_file)
    except RuntimeError as exc:
        msg = str(exc)
        if "timed out" in msg:
            raise HTTPException(status_code=504, detail=msg) from exc
        raise HTTPException(status_code=500, detail=msg) from exc


@router.get("/describe")
async def describe_upload(
    path: str = Query(..., min_length=3),
    sample_limit: int = Query(60, ge=5, le=300),
) -> Dict[str, Any]:
    resolved = resolve_upload_path(path)
    if resolved is None:
        raise HTTPException(status_code=400, detail="Invalid upload path")
    info = inspect_upload_tree(resolved, sample_limit=sample_limit)
    return {
        "status": "ok",
        "path": str(resolved),
        "summary_es": format_upload_summary(info, lang="es"),
        "summary_en": format_upload_summary(info, lang="en"),
        "info": info,
    }


@router.get("/projects")
async def projects(
    limit: int = Query(25, ge=1, le=200),
) -> Dict[str, Any]:
    """List registered projects (source of truth for UI selection)."""
    return {"items": list_projects(limit=limit)}


@router.get("/av/status")
async def av_status() -> Dict[str, Any]:
    return {"status": "ok", "clamav": clamav_status()}


@router.get("/av/recent")
async def av_recent(
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    return {"status": "ok", "items": recent_av_events(limit=limit)}


@router.get("/projects/{project_id}")
async def project_detail(
    project_id: str,
    lang: str = Query("es"),
) -> Dict[str, Any]:
    """
    What it does:
    - Returns canonical project metadata + manifest summary.

    Why it exists:
    - Single project-detail endpoint consumed by UI and tooling.

    Called from ->
    - Project selector/details panel
    - architecture and dependency exploration flows

    Calls ->
    - project registry + manifest summary utilities
    """
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    manifest = load_project_manifest(project.get("manifest_path") or project.get("root_path") or "")
    return {
        "status": "ok",
        "project": project,
        "manifest": manifest,
        "summary": summarize_manifest(manifest, lang=lang) if manifest else None,
        "architecture_summary": summarize_architecture(manifest.get("architecture") or {}, lang=lang) if manifest and isinstance(manifest.get("architecture"), dict) else None,
        "intelligence": build_project_intelligence_summary(_resolve_registered_project_root(project), manifest=manifest) if manifest else None,
    }


@router.get("/projects/{project_id}/entrypoints")
async def project_entrypoints(project_id: str) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    return {
        "status": "ok",
        "project_id": project_id,
        "items": list((manifest.get("entrypoints") or [])[:30]),
        "project": project,
    }


@router.get("/projects/{project_id}/dependencies")
async def project_dependencies(project_id: str) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    return {
        "status": "ok",
        "project_id": project_id,
        "items": list((manifest.get("package_files") or [])[:40]),
        "frameworks": list((manifest.get("frameworks") or [])[:20]),
        "project": project,
    }


@router.get("/projects/{project_id}/configs")
async def project_configs(project_id: str) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    return {
        "status": "ok",
        "project_id": project_id,
        "items": list((manifest.get("config_files") or [])[:40]),
        "project": project,
    }


@router.get("/projects/{project_id}/architecture")
async def project_architecture(
    project_id: str,
    lang: str = Query("es"),
) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    architecture = manifest.get("architecture") if isinstance(manifest.get("architecture"), dict) else {}
    return {
        "status": "ok",
        "project_id": project_id,
        "architecture": architecture,
        "summary": summarize_architecture(architecture, lang=lang),
        "project": project,
    }


@router.get("/projects/{project_id}/ideas")
async def project_improvement_ideas(
    project_id: str,
    lang: str = Query("es"),
) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    return {
        "status": "ok",
        "project_id": project_id,
        "items": build_project_improvement_ideas(manifest, lang=lang),
        "project": project,
    }


@router.get("/projects/{project_id}/intelligence")
async def project_intelligence(project_id: str) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    root = _resolve_registered_project_root(project)
    return {
        "status": "ok",
        "project_id": project_id,
        "summary": build_project_intelligence_summary(root, manifest=manifest),
        "project": project,
    }


@router.get("/projects/{project_id}/impact")
async def project_impact(
    project_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=20),
) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    root = _resolve_registered_project_root(project)
    focus = _normalize_project_query_focus(root, project_id, q)
    return {
        "status": "ok",
        "project_id": project_id,
        "report": build_project_impact_report(root, manifest=manifest, q=focus, limit=limit),
        "project": project,
    }


@router.post("/projects/{project_id}/rename_plan")
async def project_symbol_rename_plan(
    project_id: str,
    req: SymbolRenamePlanRequest,
) -> Dict[str, Any]:
    project, manifest = _project_manifest_or_404(project_id)
    root = _resolve_registered_project_root(project)
    try:
        plan = build_symbol_rename_plan(
            root,
            manifest=manifest,
            symbol=req.symbol,
            new_symbol=req.new_symbol,
            limit=max(1, min(int(req.limit or 20), 40)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid rename plan: {exc}") from exc
    return {
        "status": "ok",
        "project_id": project_id,
        "plan": plan,
        "project": project,
    }


@router.get("/tree", response_model=TreeNode)
async def project_tree(
    root: str = Query(".", description="Relative directory from workspace root"),
    project_id: Optional[str] = Query(None),
    max_depth: int = Query(4, ge=1, le=10),
) -> TreeNode:
    """
    What it does:
    - Returns bounded filesystem tree for a project root.

    Why it exists:
    - Powers deterministic browsing without exposing arbitrary host paths.

    Called from ->
    - Files panel tree view

    Calls ->
    - project-root resolver + protected tree builder
    """
    if not project_id and not FILES_ALLOW_ROOT_PARAM:
        raise HTTPException(status_code=400, detail="Use project_id (register a root) instead of root= for browsing.")
    root_path, _project = _project_root_from_query(project_id=project_id, root=root)
    if not root_path.exists() or not root_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    return _build_tree_node(root_path, max_depth=max_depth)


@router.get("/content")
async def project_content(
    path: str = Query(..., min_length=1, description="Relative file path"),
    project_id: Optional[str] = Query(None),
    root: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """
    What it does:
    - Returns raw text file contents from a validated project path.

    Why it exists:
    - Enables excerpt/symbol inspection while enforcing workspace boundaries.

    Called from ->
    - File preview UI
    - project excerpt/symbol flows in chat runtime

    Calls ->
    - root/path guards + filesystem reader

    Failure/guard behavior:
    - Blocks path traversal and non-text decoding failures.
    """
    file_path = _resolve_project_text_file_path(path=path, project_id=project_id, root=root)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="File is not a text file") from exc
    return {"path": _relative_to_workspace(file_path), "content": text}


@router.post("/content/save")
async def save_project_content(req: SaveContentRequest) -> Dict[str, Any]:
    """
    What it does:
    - Saves updated text content back to a validated project file.

    Why it exists:
    - Enables in-window editing while preserving project-root guards.

    Failure/guard behavior:
    - Only writes inside a registered/safe project root and rejects oversized payloads.
    """
    file_path = _resolve_project_text_file_path(path=req.path, project_id=req.project_id, root=req.root)
    file_exists = file_path.exists()
    if file_exists and not file_path.is_file():
        raise HTTPException(status_code=400, detail="Target path is not a file")
    if not file_exists and not req.create:
        raise HTTPException(status_code=404, detail="File not found")
    current_text = ""
    if file_exists:
        try:
            current_text = file_path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="File is not a UTF-8 text file") from exc

    content = str(req.content or "")
    payload_bytes = len(content.encode("utf-8"))
    if payload_bytes > FILES_MAX_EDIT_BYTES:
        raise HTTPException(status_code=413, detail="Edited file exceeds max allowed size")
    if content == current_text:
        return {
            "status": "ok",
            "path": _relative_to_workspace(file_path),
            "saved": False,
            "created": False,
            "content_bytes": payload_bytes,
        }

    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp.{uuid.uuid4().hex}")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(file_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass

    return {
        "status": "ok",
        "path": _relative_to_workspace(file_path),
        "saved": True,
        "created": not file_exists,
        "content_bytes": payload_bytes,
        "updated_at_ms": int(time.time() * 1000),
    }


@router.post("/content/diff")
async def diff_project_content(req: SaveContentRequest) -> Dict[str, Any]:
    """
    What it does:
    - Builds a unified diff preview for a proposed file edit/create.

    Why it exists:
    - Lets the UI preview exact code changes before writing to disk.
    """
    file_path = _resolve_project_text_file_path(path=req.path, project_id=req.project_id, root=req.root)
    file_exists = file_path.exists()
    if file_exists and not file_path.is_file():
        raise HTTPException(status_code=400, detail="Target path is not a file")
    if not file_exists and not req.create:
        raise HTTPException(status_code=404, detail="File not found")

    current_text = ""
    if file_exists:
        try:
            current_text = file_path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="File is not a UTF-8 text file") from exc
    proposed_text = str(req.content or "")
    diff_text = "".join(
        unified_diff(
            current_text.splitlines(keepends=True),
            proposed_text.splitlines(keepends=True),
            fromfile=_relative_to_workspace(file_path) if file_exists else f"a/{req.path}",
            tofile=_relative_to_workspace(file_path) if file_exists else f"b/{req.path}",
            lineterm="",
        )
    )
    return {
        "status": "ok",
        "path": _relative_to_workspace(file_path) if file_exists else str(req.path).strip(),
        "exists": file_exists,
        "create": bool(req.create and not file_exists),
        "changed": current_text != proposed_text,
        "diff": diff_text,
    }


@router.post("/content/rename")
async def rename_project_content(req: RenameContentRequest) -> Dict[str, Any]:
    """
    What it does:
    - Renames a file inside the active/registered project root.

    Why it exists:
    - Lets the Files workspace complete a common code-edit operation without leaving guarded paths.
    """
    src_path = _resolve_project_text_file_path(path=req.path, project_id=req.project_id, root=req.root)
    if not src_path.exists() or not src_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    dest_clean = str(req.new_path or "").strip()
    if not dest_clean:
        raise HTTPException(status_code=400, detail="Missing new_path")
    dest_path = _resolve_project_text_file_path(path=dest_clean, project_id=req.project_id, root=req.root)

    if dest_path == src_path:
        return {
            "status": "ok",
            "renamed": False,
            "path": _relative_to_workspace(src_path),
            "new_path": _relative_to_workspace(dest_path),
        }
    if dest_path.exists():
        raise HTTPException(status_code=409, detail="Target path already exists")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    old_rel = _relative_to_workspace(src_path)
    src_path.replace(dest_path)
    return {
        "status": "ok",
        "renamed": True,
        "path": old_rel,
        "new_path": _relative_to_workspace(dest_path),
        "updated_at_ms": int(time.time() * 1000),
    }


@router.post("/content/delete")
async def delete_project_content(req: DeleteContentRequest) -> Dict[str, Any]:
    """
    What it does:
    - Deletes a file inside the active/registered project root.

    Why it exists:
    - Keeps destructive editor operations inside the same guarded Files API contract.
    """
    file_path = _resolve_project_text_file_path(path=req.path, project_id=req.project_id, root=req.root)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    rel_path = _relative_to_workspace(file_path)
    file_path.unlink()
    return {
        "status": "ok",
        "deleted": True,
        "path": rel_path,
        "updated_at_ms": int(time.time() * 1000),
    }


@router.post("/path/mkdir")
async def create_project_directory(req: CreateDirectoryRequest) -> Dict[str, Any]:
    """
    What it does:
    - Creates a directory inside the active/registered project root.

    Why it exists:
    - Lets the Files workspace create project structure without leaving guarded paths.
    """
    dir_path = _resolve_project_path(path=req.path, project_id=req.project_id, root=req.root)
    if dir_path.exists():
        if not dir_path.is_dir():
            raise HTTPException(status_code=400, detail="Target path already exists as a file")
        return {
            "status": "ok",
            "created": False,
            "path": _relative_to_workspace(dir_path),
        }

    dir_path.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "created": True,
        "path": _relative_to_workspace(dir_path),
        "updated_at_ms": int(time.time() * 1000),
    }


@router.post("/path/move")
async def move_project_path(req: MovePathRequest) -> Dict[str, Any]:
    """
    What it does:
    - Moves or renames a file/directory inside the active/registered project root.

    Why it exists:
    - Supports folder moves/renames and file relocations from the guarded Files workspace.
    """
    src_path = _resolve_project_path(path=req.path, project_id=req.project_id, root=req.root)
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    dest_clean = str(req.new_path or "").strip()
    if not dest_clean:
        raise HTTPException(status_code=400, detail="Missing new_path")
    dest_path = _resolve_project_path(path=dest_clean, project_id=req.project_id, root=req.root)
    if dest_path == src_path:
        return {
            "status": "ok",
            "moved": False,
            "path": _relative_to_workspace(src_path),
            "new_path": _relative_to_workspace(dest_path),
            "is_dir": src_path.is_dir(),
        }
    if dest_path.exists():
        raise HTTPException(status_code=409, detail="Target path already exists")
    if src_path.is_dir():
        try:
            src_resolved = src_path.resolve()
            dest_resolved = dest_path.resolve(strict=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid move target: {exc}") from exc
        if dest_resolved == src_resolved or src_resolved in dest_resolved.parents:
            raise HTTPException(status_code=400, detail="Cannot move a directory into itself")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    old_rel = _relative_to_workspace(src_path)
    shutil.move(str(src_path), str(dest_path))
    return {
        "status": "ok",
        "moved": True,
        "path": old_rel,
        "new_path": _relative_to_workspace(dest_path),
        "is_dir": dest_path.is_dir(),
        "updated_at_ms": int(time.time() * 1000),
    }


@router.post("/batch/preview")
async def preview_batch_project_changes(req: BatchApplyRequest) -> Dict[str, Any]:
    """
    What it does:
    - Builds a reviewed preview for a structured multi-file change set.

    Why it exists:
    - Lets the Files workspace preview and lock the exact payload before apply.
    """
    operations = list(req.operations or [])
    if not operations:
        raise HTTPException(status_code=400, detail="No operations provided")
    return _build_batch_preview(
        operations=operations,
        project_id=req.project_id,
        root=req.root,
    )


@router.post("/batch/apply")
async def batch_apply_project_changes(req: BatchApplyRequest) -> Dict[str, Any]:
    """
    What it does:
    - Applies multiple guarded file-system operations in one request.

    Why it exists:
    - Lets the Files workspace apply structured multi-file changes deterministically.
    """
    operations = list(req.operations or [])
    if not operations:
        raise HTTPException(status_code=400, detail="No operations provided")
    if req.review_token:
        expected_review_token = _batch_review_token(operations)
        if str(req.review_token or "").strip() != expected_review_token:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "review_token does not match the current batch payload",
                    "review_required": True,
                },
            )

    applied: List[Dict[str, Any]] = []
    prepared_undos: List[Dict[str, Any]] = []
    try:
        for idx, item in enumerate(operations):
            op = str(item.op or "").strip().lower()
            prepared_undos.append(
                _prepare_batch_undo(
                    item=item,
                    project_id=req.project_id,
                    root=req.root,
                )
            )
            if op == "write":
                result = await save_project_content(
                    SaveContentRequest(
                        project_id=req.project_id,
                        root=req.root,
                        path=item.path,
                        content=item.content,
                        create=bool(item.create),
                    )
                )
            elif op == "delete":
                result = await delete_project_content(
                    DeleteContentRequest(
                        project_id=req.project_id,
                        root=req.root,
                        path=item.path,
                    )
                )
            elif op == "mkdir":
                result = await create_project_directory(
                    CreateDirectoryRequest(
                        project_id=req.project_id,
                        root=req.root,
                        path=item.path,
                    )
                )
            elif op == "move":
                result = await move_project_path(
                    MovePathRequest(
                        project_id=req.project_id,
                        root=req.root,
                        path=item.path,
                        new_path=str(item.new_path or ""),
                    )
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported batch op: {item.op}")
            result = dict(result)
            result["op"] = op
            result["index"] = idx
            applied.append(result)
    except HTTPException as exc:
        rollback = await _rollback_batch_operations(
            prepared_undos,
            project_id=req.project_id,
            root=req.root,
        )
        detail = exc.detail
        message = detail if isinstance(detail, str) else detail.get("message") or str(detail)
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "message": f"Batch apply failed and rollback {'succeeded' if rollback['ok'] else 'partially failed'}: {message}",
                "failed_index": len(applied),
                "rolled_back": rollback["ok"],
                "rollback_results": rollback["results"],
            },
        ) from exc

    return {
        "status": "ok",
        "applied_count": len(applied),
        "results": applied,
        "reviewed": bool(req.review_token),
        "updated_at_ms": int(time.time() * 1000),
    }


@router.post("/projects/{project_id}/ideas/{idea_id}/apply")
async def apply_project_idea_starter(project_id: str, idea_id: str) -> Dict[str, Any]:
    """
    What it does:
    - Applies a deterministic starter change-set for supported improvement ideas.

    Why it exists:
    - Turns selected repo-improvement ideas into guarded code/file changes directly from the Files workspace.
    """
    _project, manifest = _project_manifest_or_404(project_id)
    operations = _build_supported_idea_starter_ops(manifest, idea_id)
    result = await batch_apply_project_changes(
        BatchApplyRequest(
            project_id=project_id,
            operations=operations,
        )
    )
    result["idea_id"] = str(idea_id or "").strip().lower()
    return result


@router.post("/delete_project")
async def delete_project_endpoint(req: DeleteProjectRequest) -> Dict[str, Any]:
    """
    What it does:
    - Removes a registered project from metadata and deletes upload-backed data when eligible.

    Why it exists:
    - Provide one canonical deletion path used by UI and agent approval flows.

    Called from ->
    - Files panel project delete action
    - chat tool execution (`delete_project`) after approval

    Calls ->
    - project registry lookup/removal
    - guarded filesystem delete for upload-root projects

    Failure/guard behavior:
    - Prevents deletion outside upload root and returns explicit HTTP errors on guard failures.
    """
    project = None
    target: Path

    if req.project_id:
        project = get_project(str(req.project_id).strip())
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        target = _resolve_registered_project_root(project)
    elif req.path:
        raw = Path(req.path)
        tentative = raw if raw.is_absolute() else (PROJECT_ROOT / raw)
        tentative = tentative.resolve()
        if not _is_under_upload_root(tentative):
            raise HTTPException(status_code=400, detail="Path outside uploads directory")
        if not tentative.exists() or not tentative.is_dir():
            raise HTTPException(status_code=404, detail="Project not found")
        target = tentative
        project = get_project_by_path(target)
    else:
        raise HTTPException(status_code=400, detail="project_id or path is required")

    project_id = str((project or {}).get("project_id") or "").strip()
    deleted_path = False
    if _is_under_upload_root(target):
        try:
            shutil.rmtree(target, ignore_errors=False)
            deleted_path = True
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to delete project: {exc}") from exc
    if project_id:
        delete_registered_project(project_id)
    else:
        delete_project_by_path(target)

    return {
        "status": "ok",
        "project_id": project_id or None,
        "path": str(target),
        "deleted_path": deleted_path,
        "unregistered_only": not deleted_path,
    }


@router.get("/projects/{project_id}/files")
async def project_files(
    project_id: str,
    q: str = Query("", description="Optional substring filter"),
    limit: int = Query(80, ge=1, le=500),
) -> Dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    manifest = load_project_manifest(project.get("manifest_path") or project.get("root_path") or "")
    if not manifest:
        raise HTTPException(status_code=404, detail="Project manifest not found")
    ranked = fuzzy_search_project_files(manifest, q=q, limit=limit)
    items = [str(row.get("path") or "") for row in ranked if str(row.get("path") or "").strip()]
    return {
        "status": "ok",
        "project_id": project_id,
        "items": items[:limit],
        "matches": ranked[:limit],
        "focus": infer_file_focus(q, manifest) if (q or "").strip() else None,
    }


@router.get("/projects/{project_id}/symbols")
async def project_symbols(
    project_id: str,
    q: str = Query("", description="Optional symbol/file filter"),
    limit: int = Query(80, ge=1, le=300),
) -> Dict[str, Any]:
    """Search symbols in project scope, with deterministic file-match fallback."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    manifest = load_project_manifest(project.get("manifest_path") or project.get("root_path") or "")
    # Local import to avoid pulling FAISS/embeddings at server import time.
    from app.services.retrieval_service import list_project_symbols

    items = list_project_symbols(project_id, q=q, limit=limit)
    if not items:
        try:
            root = _resolve_registered_project_root(project)
            items = scan_project_symbols(root, manifest=manifest, q=q, limit=limit)
        except Exception:
            items = []
    # Final deterministic fallback: if symbol scan finds nothing, return best file matches so the UI/E2E
    # can still guide the user to relevant locations (especially for tiny projects).
    if not items and (q or "").strip() and isinstance(manifest, dict):
        try:
            ranked = fuzzy_search_project_files(manifest, q=q, limit=limit)
            file_items: list[dict] = []
            for row in ranked[: max(1, limit)]:
                path = str(row.get("path") or "").strip()
                if not path:
                    continue
                file_items.append(
                    {
                        "symbol": Path(path).stem,
                        "path": path,
                        "language": language_for_path(Path(path)),
                        "line_start": 1,
                        "line_end": 1,
                        "kind": "file_match",
                        "score": row.get("score"),
                    }
                )
            items = file_items
        except Exception:
            items = []
    return {
        "status": "ok",
        "project_id": project_id,
        "items": items,
    }


@router.get("/projects/{project_id}/excerpt")
async def project_excerpt(
    project_id: str,
    path: str = Query(..., min_length=1),
    start: int = Query(1, ge=1),
    lines: int = Query(80, ge=1, le=400),
) -> Dict[str, Any]:
    """Return line window excerpt for deterministic code evidence in agent flows."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    root = _resolve_registered_project_root(project)
    candidate = _ensure_within_root(root, root / path)
    target = ensure_under_upload_root(candidate) if _is_under_upload_root(root) else _ensure_under_project_root(candidate)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        all_lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}") from exc
    start_idx = max(0, start - 1)
    chunk = all_lines[start_idx : start_idx + lines]
    return {
        "status": "ok",
        "project_id": project_id,
        "path": path,
        "start": start,
        "lines": chunk,
    }


@router.get("/ingest/status")
async def ingest_status(job_id: str = Query(..., min_length=3)) -> Dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return serialize_job(job)


@router.get("/ingest/jobs")
async def ingest_jobs(
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    jobs = list_jobs(limit=limit, kind="ingest")
    return {"items": [serialize_job(job) for job in jobs]}


@router.get("/ingest/recent")
async def ingest_recent(
    tail: int = Query(120, ge=10, le=2000),
) -> Dict[str, Any]:
    jobs = list_jobs(limit=1, kind="ingest")
    job = jobs[0] if jobs else None
    log_path = str(((job.meta or {}) if job else {}).get("log_path") or "").strip()
    if not log_path:
        candidates = sorted(
            list(INGEST_LOG_DIR.glob("ingest_*.log")) + list(INGEST_LOG_DIR.glob("ingest_sync_*.log")),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        if not candidates:
            raise HTTPException(status_code=404, detail="No ingest jobs found")
        log_path = str(candidates[0].resolve())

    target = Path(log_path).resolve()
    logs_dir = INGEST_LOG_DIR.resolve()
    if not str(target).startswith(str(logs_dir)):
        raise HTTPException(status_code=400, detail="Log path outside allowed directory")
    if not target.exists() or not target.is_file():
        return {"job": serialize_job(job) if job else None, "path": str(target), "lines": []}

    try:
        with target.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read log: {exc}") from exc
    return {"job": serialize_job(job) if job else None, "path": str(target), "lines": lines[-tail:]}


@router.get("/ingest/log")
async def ingest_log(
    job_id: str = Query(..., min_length=3),
    tail: int = Query(200, ge=10, le=2000),
) -> Dict[str, Any]:
    """Read ingest job log tail from guarded logs directory."""
    job = get_job(job_id)
    if not job:
        # Allow log access after reloads by checking the conventional log path.
        fallback = INGEST_LOG_DIR / f"ingest_{job_id}.log"
        if fallback.exists():
            target = fallback.resolve()
            logs_dir = INGEST_LOG_DIR.resolve()
            if not str(target).startswith(str(logs_dir)):
                raise HTTPException(status_code=400, detail="Log path outside allowed directory")
            try:
                with target.open("r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                return {"job_id": job_id, "path": str(target), "lines": lines[-tail:]}
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"Cannot read log: {exc}")
        raise HTTPException(status_code=404, detail="Job not found")
    log_path = (job.meta or {}).get("log_path")
    if not log_path:
        raise HTTPException(status_code=404, detail="No log available for job")

    target = Path(log_path).resolve()
    logs_dir = INGEST_LOG_DIR.resolve()
    if not str(target).startswith(str(logs_dir)):
        raise HTTPException(status_code=400, detail="Log path outside allowed directory")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    try:
        with target.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return {"job_id": job_id, "path": str(target), "lines": lines[-tail:]}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Cannot read log: {exc}")
