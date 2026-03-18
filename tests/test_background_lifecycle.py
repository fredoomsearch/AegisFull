from __future__ import annotations

import time


def test_web_search_warmup_start_stop(monkeypatch):
    from app.services import web_search

    monkeypatch.setattr(web_search, "WARMUP_ON_START", False)
    monkeypatch.setattr(web_search, "WARMUP_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(web_search, "_run_warmup_cycle", lambda: None)
    web_search._warmup_started = False  # type: ignore[attr-defined]
    web_search._warmup_thread = None  # type: ignore[attr-defined]
    web_search._warmup_stop.clear()  # type: ignore[attr-defined]

    web_search.start_background_warmup()
    time.sleep(0.02)
    assert web_search._warmup_thread is not None  # type: ignore[attr-defined]
    assert web_search.stop_background_warmup(timeout_s=1.0) is True


def test_job_manager_wait_for_jobs_cleans_finished_thread():
    from app.services import job_manager

    job = job_manager.start_job(lambda: {"ok": True}, kind="test-cleanup")
    status = job_manager.wait_for_jobs(timeout_s=1.0)
    assert int(status.get("tracked") or 0) >= 1
    assert int(status.get("alive") or 0) == 0
    assert job_manager.get_job(job.id) is not None
