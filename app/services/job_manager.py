from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from threading import Lock, Thread
from typing import Callable, Dict, Optional


@dataclass
class Job:
    id: str
    kind: str = "generic"
    status: str = "queued"  # queued | running | success | error
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict] = None
    meta: Dict[str, str] = field(default_factory=dict)


_jobs: dict[str, Job] = {}
_lock = Lock()


def _set_job(job_id: str, **updates: object) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            setattr(job, key, value)


def start_job(
    fn: Callable[[], Dict],
    kind: str = "generic",
    job_id: Optional[str] = None,
    meta: Optional[Dict[str, str]] = None,
) -> Job:
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

    Thread(target=_runner, daemon=True).start()
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
    return asdict(job)
