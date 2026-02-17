from __future__ import annotations

"""
Support tools for AEGIS, exposed under /tools:

  - GET  /tools/tree
  - GET  /tools/content
  - POST /tools/docs/summary
  - POST /tools/upload_project

These endpoints help the assistant inspect project structure and content.
"""

import io
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from app.api.deps import require_api_key

logger = logging.getLogger(__name__)

# Repo root: two levels up from this file (…/app/api/toolssupport.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Keep uploads in the same root as /files/upload-zip so /files/ingest accepts them.
UPLOADS_DIR = Path(os.getenv("FILES_UPLOAD_ROOT", "data/uploads")).resolve()
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = int(os.getenv("FILES_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
FILES_AV_SCAN = os.getenv("FILES_AV_SCAN", "1") != "0"
FILES_AV_TIMEOUT = int(os.getenv("FILES_AV_TIMEOUT", "15"))

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "venv",
    ".venv",
    "data",
    "nginx",
}
EXCLUDED_FILES = {"aegis.db"}

router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(require_api_key)])


# ==========
# Schemas
# ==========

class TreeNode(BaseModel):
    name: str
    path: str          # path relative to PROJECT_ROOT
    type: str          # "file" or "dir"
    # Compat: algunos frontends esperan is_dir (bool)
    is_dir: bool | None = None
    children: List["TreeNode"] | None = None


TreeNode.update_forward_refs()


class DocsRequest(BaseModel):
    paths: List[str]   # relative paths from PROJECT_ROOT (e.g. "app/api/chat.py")
    lang: str = "es"


class DocsSummary(BaseModel):
    lang: str
    file_count: int
    total_lines: int
    preview: str


class DeleteProjectRequest(BaseModel):
    path: str


# ==========
# Helpers
# ==========

def _embedding_api():
    if (os.getenv("AEGIS_DISABLE_EMBEDDINGS", "0") or "0").lower() in {"1", "true", "yes", "on"}:
        return None
    try:
        from app.services import embedding_service

        return embedding_service
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding service unavailable: %s", exc)
        return None

def _is_safe_path(path: Path) -> bool:
    """Ensure the requested path is inside PROJECT_ROOT (no directory traversal)."""
    try:
        path = path.resolve()
        return PROJECT_ROOT in path.parents or path == PROJECT_ROOT
    except Exception:
        return False


def _is_safe_upload_path(path: Path) -> bool:
    """Ensure the requested path is inside the uploads directory."""
    try:
        path = path.resolve()
        return UPLOADS_DIR in path.parents and path != UPLOADS_DIR
    except Exception:
        return False


def _build_tree(root: Path, max_depth: int = 4, depth: int = 0) -> TreeNode:
    rel = root.relative_to(PROJECT_ROOT)
    node = TreeNode(
        name=root.name or str(rel),
        path=str(rel),
        type="dir",
        is_dir=True,
        children=[],
    )

    if depth >= max_depth:
        return node

    try:
        for entry in sorted(
            root.iterdir(),
            key=lambda p: (p.is_file(), p.name.lower()),
        ):
            if entry.is_dir() and entry.name in EXCLUDED_DIRS:
                continue
            if entry.is_file() and entry.name in EXCLUDED_FILES:
                continue

            if entry.is_dir():
                child = _build_tree(entry, max_depth=max_depth, depth=depth + 1)
                node.children.append(child)
            else:
                rel_child = entry.relative_to(PROJECT_ROOT)
                node.children.append(
                    TreeNode(
                        name=entry.name,
                        path=str(rel_child),
                        type="file",
                        is_dir=False,
                        children=None,
                    )
                )
    except PermissionError:
        # Ignore directories we can't read
        pass

    return node


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


def _av_scan_path(path: Path) -> None:
    """
    Reuse the same lightweight AV scan used in /files. Skips silently if disabled.
    """
    if not FILES_AV_SCAN:
        return
    if not path.exists():
        return

    scanner = shutil.which("clamdscan") or shutil.which("clamscan")
    if not scanner:
        return

    size_mb = _dir_size_mb(path)
    if size_mb > (MAX_UPLOAD_BYTES // (1024 * 1024) * 2):
        raise HTTPException(status_code=400, detail="AV scan skipped: tree too large")

    cmd = [scanner, "--infected", "--no-summary", str(path)]
    if "clamdscan" in scanner:
        cmd.insert(1, "--fdpass")

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=FILES_AV_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=400, detail="AV scan timed out")
    except Exception:
        raise HTTPException(status_code=400, detail="AV scan failed")

    output = (res.stdout or "").strip()
    if res.returncode == 0:
        return
    if res.returncode == 1:
        raise HTTPException(status_code=400, detail=f"Malware detected: {output or 'infected'}")
    raise HTTPException(status_code=400, detail=f"AV scan error: {output or 'scan error'}")


def _extract_zip_safe(buf: bytes, dest: Path) -> None:
    """Extract ZIP into dest, preventing zip-slip path traversal."""
    with zipfile.ZipFile(io.BytesIO(buf)) as zf:
        for member in zf.namelist():
            member_norm = member.replace("\\", "/")
            # Skip absolute paths or parent traversals
            if member_norm.startswith("/") or ".." in Path(member_norm).parts:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid entry in zip: {member}",
                )

            target = (dest / member_norm).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise HTTPException(
                    status_code=400,
                    detail=f"Blocked path: {member}",
                )

            if member_norm.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)


# ==========
# Endpoints
# ==========

@router.get("/tree", response_model=TreeNode)
async def get_tree(
    root: str = Query(".", description="Relative directory from project root"),
    max_depth: int = Query(4, ge=1, le=10),
):
    """Returns a nested tree representation of the project files."""
    root_path = (PROJECT_ROOT / root).resolve()

    if not _is_safe_path(root_path):
        raise HTTPException(status_code=400, detail="Path outside project root")

    if not root_path.exists() or not root_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    return _build_tree(root_path, max_depth=max_depth)


@router.get("/content")
async def get_content(
    path: str = Query(..., description="Relative file path from project root"),
):
    """Returns the raw text content of a file."""
    file_path = (PROJECT_ROOT / path).resolve()

    if not _is_safe_path(file_path):
        raise HTTPException(status_code=400, detail="Path outside project root")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="File is not a text file")

    return {"path": path, "content": text}


@router.get("/embeddings/status")
async def embeddings_status(ensure_loaded: bool = Query(False)) -> dict:
    svc = _embedding_api()
    if svc is None:
        return {"status": "disabled", "detail": "Embeddings disabled for this runtime."}
    return svc.get_embedding_status(ensure_loaded=ensure_loaded)


@router.post("/embeddings/prepare")
async def embeddings_prepare() -> dict:
    svc = _embedding_api()
    if svc is None:
        return {"status": "disabled", "detail": "Embeddings disabled for this runtime."}
    return svc.prepare_embeddings()


@router.post("/docs/summary", response_model=DocsSummary)
async def docs_summary(req: DocsRequest):
    """Reads requested files, counts lines, returns a short preview."""
    all_texts: List[str] = []
    total_lines = 0

    for rel_path in req.paths:
        file_path = (PROJECT_ROOT / rel_path).resolve()
        if not _is_safe_path(file_path):
            raise HTTPException(status_code=400, detail=f"Unsafe path: {rel_path}")
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {rel_path}")

        text = file_path.read_text(encoding="utf-8", errors="ignore")
        all_texts.append(f"# {rel_path}\n{text}")
        total_lines += len(text.splitlines())

    joined = "\n\n".join(all_texts)
    preview_lines = joined.splitlines()[:40]
    preview = "\n".join(preview_lines)

    return DocsSummary(
        lang=req.lang,
        file_count=len(req.paths),
        total_lines=total_lines,
        preview=preview,
    )


@router.post("/upload_project")
async def upload_project(file: UploadFile = File(...)):
    """
    Accept a .zip, extract safely under PROJECT_ROOT/uploads/<id>, and return the root folder.
    """
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported.")

    buf = await file.read()
    if not buf:
        raise HTTPException(status_code=400, detail="Empty file.")

    proj_id = f"project_{uuid4().hex[:8]}"
    dest = (UPLOADS_DIR / proj_id).resolve()
    dest.mkdir(parents=True, exist_ok=False)

    _extract_zip_safe(buf, dest)
    _av_scan_path(dest)

    # Intenta detectar si el zip tenía una carpeta raíz única; si es así, usa esa.
    children = list(dest.iterdir())
    if len(children) == 1 and children[0].is_dir():
        try:
            root_rel = children[0].relative_to(PROJECT_ROOT)
            return {"root": str(root_rel), "path": str(children[0])}
        except ValueError:
            return {"path": str(children[0])}

    try:
        root_rel = dest.relative_to(PROJECT_ROOT)
        return {"root": str(root_rel), "path": str(dest)}
    except ValueError:
        return {"path": str(dest)}


@router.post("/delete_project")
async def delete_project(req: DeleteProjectRequest):
    raw = Path(req.path)
    target = raw if raw.is_absolute() else (PROJECT_ROOT / raw)
    target = target.resolve()

    if not _is_safe_upload_path(target):
        raise HTTPException(status_code=400, detail="Path outside uploads directory")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        shutil.rmtree(target, ignore_errors=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {exc}")

    return {"status": "ok", "path": str(target)}
