from __future__ import annotations

"""
In-process background job registry.

Why this module exists:
- Track ingest/ops jobs with deterministic status transitions.
- Provide stage-level telemetry for UI/log endpoints.
"""

import time
import uuid
from dataclasses import asdict, dataclass, field
from threading import Lock, Thread
from typing import Any, Callable, Dict, Optional
from app.services.progress_tracker import snapshot_progress
from app.services.phase_progress_manager import set_stage_progress
from app.services.progress_snapshot_service import emit_progress_snapshot


# Map common job stage name fragments to formal phase headings in PROGRESO_FASES.md
# The keys are lowercase fragments to match against stage names; values are exact headings
PHASE_NAME_MAP: Dict[str, str] = {
    "context": "Fase 1 — Context Aggregator",
    "validation": "Fase 2 — Validation Layer (Anti-hallucination)",
    "project": "Fase 3 — Project Knowledge Graph",
    "memory": "Fase 4 — Unified Memory Layer",
    "hybrid": "Fase 5 — Hybrid Model Reasoning",
    "tool": "Fase 6 — Tool Result Persistence / Cache",
}


def _map_stage_to_phase(stage_name: str) -> str | None:
    if not stage_name:
        return None
    lower = str(stage_name).lower()
    for frag, heading in PHASE_NAME_MAP.items():
        if frag in lower:
            return heading
    return None


@dataclass
class Job:
    id: str
    kind: str = "generic"
    status: str = "queued"  # queued | running | success | error
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict] = None
    meta: Dict[str, Any] = field(default_factory=dict)


_jobs: dict[str, Job] = {}
_threads: dict[str, Thread] = {}
_lock = Lock()


def _set_job(job_id: str, **updates: object) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = time.time()


def _stage_list(job: Job) -> list[dict]:
    stages = job.meta.get("stages")
    if isinstance(stages, list):
        return stages
    stages = []
    job.meta["stages"] = stages
    return stages


def start_stage(job_id: str, name: str, *, detail: str = "") -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        stages = _stage_list(job)
        now = time.time()
        stages.append(
            {
                "name": str(name),
                "status": "running",
                "started_at": now,
                "finished_at": None,
                "detail": str(detail or ""),
            }
        )
        job.updated_at = now
        try:
            # Record stage progress at start (0%) using phase_progress_manager
            set_stage_progress(str(name), 0, note="stage started")
        except Exception:
            pass


def finish_stage(job_id: str, name: str, *, status: str = "success", detail: str = "") -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        stages = _stage_list(job)
        now = time.time()
        target = None
        for st in reversed(stages):
            if str(st.get("name") or "") == str(name) and st.get("finished_at") in (None, 0, ""):
                target = st
                break
        if target is None:
            target = {
                "name": str(name),
                "status": "running",
                "started_at": now,
                "finished_at": None,
                "detail": "",
            }
            stages.append(target)
        target["status"] = str(status or "success")
        target["finished_at"] = now
        if detail:
            target["detail"] = str(detail)
        job.updated_at = now
        try:
            # Record stage progress at finish (100% or 0 on failure)
            pct = 100 if str(status) == "success" else 0
            set_stage_progress(str(name), pct, note=str(detail) or "stage finished")
        except Exception:
            pass


def start_job(
    fn: Callable[[], Dict],
    kind: str = "generic",
    job_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Job:
    """Create and execute an async job with tracked lifecycle state."""
    job_id = job_id or uuid.uuid4().hex[:10]
    job = Job(id=job_id, kind=kind, meta=meta or {})
    with _lock:
        _jobs[job_id] = job

    def _runner() -> None:
        _set_job(job_id, status="running", started_at=time.time())
        try:
            result = fn()
            _set_job(job_id, status="success", result=result)
        except Exception as exc:  # noqa: BLE001
            _set_job(job_id, status="error", error=str(exc))
        finally:
            _set_job(job_id, finished_at=time.time())

    thread = Thread(target=_runner, name=f"job-{kind}-{job_id}", daemon=True)
    with _lock:
        _threads[job_id] = thread
    thread.start()
    return job


def get_job(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)


def list_jobs(limit: int = 20, kind: Optional[str] = None) -> list[Job]:
    with _lock:
        jobs = list(_jobs.values())
    if kind:
        jobs = [job for job in jobs if job.kind == kind]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs[:limit]


def serialize_job(job: Job) -> Dict:
    """Convert internal Job dataclass into API-friendly payload."""
    return asdict(job)


def wait_for_jobs(timeout_s: float = 1.0) -> Dict[str, int]:
    deadline = time.time() + max(0.0, float(timeout_s))
    with _lock:
        threads = list(_threads.items())

    alive = 0
    for job_id, thread in threads:
        remaining = deadline - time.time()
        if remaining > 0 and thread.is_alive():
            thread.join(remaining)
        if thread.is_alive():
            alive += 1
            continue
        with _lock:
            _threads.pop(job_id, None)

    return {"tracked": len(threads), "alive": alive}
