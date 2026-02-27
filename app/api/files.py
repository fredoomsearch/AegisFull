from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import require_files_api_key
from app.services.job_manager import get_job, list_jobs, serialize_job, start_job
from app.services.upload_inspector import (
    format_upload_summary,
    inspect_upload_tree,
    remember_last_upload,
    resolve_upload_path,
)

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(require_files_api_key)])
logger = logging.getLogger(__name__)

UPLOAD_ROOT = Path(os.getenv("FILES_UPLOAD_ROOT", "data/uploads")).resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.getenv("FILES_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))  # 50MB default
INGEST_TIMEOUT = int(os.getenv("FILES_INGEST_TIMEOUT", "2000"))
INGEST_LOG_DIR = Path(os.getenv("FILES_INGEST_LOG_DIR", "logs")).resolve()
ALLOWED_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
FILES_AV_SCAN = os.getenv("FILES_AV_SCAN", "1") != "0"
FILES_AV_TIMEOUT = int(os.getenv("FILES_AV_TIMEOUT", "15"))
FILES_AV_FAIL_OPEN = os.getenv("FILES_AV_FAIL_OPEN", "1") != "0"

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._\-/]+$")


def ensure_under_upload_root(p: Path) -> Path:
    resolved = p.resolve()
    # safer than string startswith
    if resolved != UPLOAD_ROOT and UPLOAD_ROOT not in resolved.parents:
        raise HTTPException(status_code=400, detail="Path outside allowed upload root")
    return resolved


def _ensure_git_exists() -> None:
    if shutil.which("git") is None:
        raise HTTPException(status_code=500, detail="git is not installed on this system")


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
    if not FILES_AV_SCAN:
        return "disabled"
    if not path.exists():
        return "missing"

    scanner = shutil.which("clamdscan") or shutil.which("clamscan")
    if not scanner:
        return "scanner-not-found"

    size_mb = _dir_size_mb(path)
    # If already too large per upload caps, we would have rejected earlier.
    # Avoid long scans on unexpectedly large trees.
    if size_mb > (MAX_UPLOAD_BYTES // (1024 * 1024) * 2):  # heuristic guard
        return _av_scan_error_or_open("tree-too-large", "AV scan skipped: tree too large")

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
        return _av_scan_error_or_open("timeout", "AV scan timed out")
    except Exception:
        # Do not block if scanner crashes; treat as failed scan.
        return _av_scan_error_or_open("failed", "AV scan failed")

    # clamscan/clamdscan: 0=clean, 1=infected, 2=error
    output = (res.stdout or "").strip()
    if res.returncode == 0:
        return "clean"
    if res.returncode == 1:
        raise HTTPException(status_code=400, detail=f"Malware detected: {output or 'infected'}")
    return _av_scan_error_or_open("scan-error", f"AV scan error: {output or 'scan error'}")


# ============================================================================
# Request models
# ============================================================================

class IngestRequest(BaseModel):
    path: str
    background: bool = False


class CloneRequest(BaseModel):
    repo_url: str
    branch: Optional[str] = None
    depth: int = Field(1, ge=1, le=50)
    max_mb: int = Field(300, ge=10, le=2000)  # soft limit


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/upload-zip")
async def upload_zip(
    file: UploadFile = File(...),
    project_name: Optional[str] = Query(None),
) -> Dict[str, Any]:
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

    return {
        "status": "ok",
        "project_id": project_id,
        "path": str(dest),
        "av_status": av_status,
        "hint": "Now call /files/ingest with this path.",
    }


@router.post("/clone")
async def clone_repo(payload: CloneRequest) -> Dict[str, Any]:
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

    return {
        "status": "ok",
        "project_id": project_id,
        "path": str(dest),
        "branch_used": used,
        "av_status": av_status,
    }


@router.post("/ingest")
async def ingest_path(body: IngestRequest) -> Dict[str, Any]:
    p = ensure_under_upload_root(Path(body.path))
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="Path does not exist")

    def _run_ingest(log_file: Path) -> Dict[str, Any]:
        # Ingest can be heavy (chunk + embed + index); keep timeout configurable.
        
        cmd = [sys.executable or "python", "app/scripts/ingest_repo.py", "--root", str(p)]
        INGEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        # Ensure ingest logs flush promptly for UI progress.
        env["PYTHONUNBUFFERED"] = "1"
        start = time.monotonic()
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

        if proc.returncode != 0:
            raise RuntimeError("ingest failed (see log)")

        return {
            "status": "ok",
            "ingested_path": str(p),
            "log_path": str(log_file),
        }

    if body.background:
        job_id = uuid.uuid4().hex[:10]
        log_file = INGEST_LOG_DIR / f"ingest_{job_id}.log"
        job = start_job(
            lambda: _run_ingest(log_file),
            kind="ingest",
            job_id=job_id,
            meta={"log_path": str(log_file), "path": str(p)},
        )
        return {"status": "queued", "job_id": job.id}

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


@router.get("/ingest/log")
async def ingest_log(
    job_id: str = Query(..., min_length=3),
    tail: int = Query(200, ge=10, le=2000),
) -> Dict[str, Any]:
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
