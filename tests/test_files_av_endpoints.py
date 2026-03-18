from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import files as files_api
from app.services.antivirus_service import clamav_status, recent_av_events


def test_files_av_status_and_recent():
    status_payload = clamav_status()
    assert isinstance(status_payload, dict)
    assert "status" in status_payload

    recent_payload = recent_av_events(limit=5)
    assert isinstance(recent_payload, list)


def test_av_scan_path_retries_timeout_then_succeeds(tmp_path, monkeypatch):
    target = tmp_path / "scan_dir"
    target.mkdir()
    (target / "x.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(files_api, "FILES_AV_SCAN", True)
    monkeypatch.setattr(files_api, "FILES_AV_FAIL_OPEN", False)
    monkeypatch.setattr(files_api, "FILES_AV_RETRIES", 1)
    monkeypatch.setattr(files_api, "FILES_AV_TIMEOUT", 1)
    monkeypatch.setattr(files_api, "_dir_size_mb", lambda _p: 1)
    monkeypatch.setattr(files_api, "clamav_status", lambda: {"scanner": "clamscan"})
    monkeypatch.setattr(files_api.shutil, "which", lambda name: "/usr/bin/clamscan" if name == "clamscan" else None)
    monkeypatch.setattr(files_api, "record_av_event", lambda **_kwargs: None)

    calls = {"n": 0}

    def _run(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd="clamscan", timeout=1)
        return SimpleNamespace(returncode=0, stdout="clean")

    monkeypatch.setattr(files_api.subprocess, "run", _run)
    result = files_api._av_scan_path(target)
    assert result == "clean"
    assert calls["n"] == 2


def test_av_scan_path_timeout_retries_exhausted_fail_closed(tmp_path, monkeypatch):
    target = tmp_path / "scan_dir"
    target.mkdir()
    (target / "x.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(files_api, "FILES_AV_SCAN", True)
    monkeypatch.setattr(files_api, "FILES_AV_FAIL_OPEN", False)
    monkeypatch.setattr(files_api, "FILES_AV_RETRIES", 1)
    monkeypatch.setattr(files_api, "FILES_AV_TIMEOUT", 1)
    monkeypatch.setattr(files_api, "_dir_size_mb", lambda _p: 1)
    monkeypatch.setattr(files_api, "clamav_status", lambda: {"scanner": "clamscan"})
    monkeypatch.setattr(files_api.shutil, "which", lambda name: "/usr/bin/clamscan" if name == "clamscan" else None)
    monkeypatch.setattr(files_api, "record_av_event", lambda **_kwargs: None)

    calls = {"n": 0}

    def _run(*_args, **_kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="clamscan", timeout=1)

    monkeypatch.setattr(files_api.subprocess, "run", _run)
    with pytest.raises(HTTPException) as exc:
        files_api._av_scan_path(target)
    assert exc.value.status_code == 400
    assert "AV scan timed out" in str(exc.value.detail)
    assert calls["n"] == 2
