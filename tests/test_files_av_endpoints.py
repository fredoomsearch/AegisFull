from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace
import zipfile

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


def test_files_av_fail_open_defaults_closed():
    assert files_api.FILES_AV_FAIL_OPEN is False


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


def test_extract_zip_archive_rejects_too_many_entries(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("one.txt", "1")
        zf.writestr("two.txt", "2")
    buf.seek(0)

    upload_root = tmp_path / "uploads"
    upload_root.mkdir(exist_ok=True)
    monkeypatch.setattr(files_api, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(files_api, "FILES_MAX_ZIP_ENTRIES", 1)

    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(HTTPException) as exc:
            files_api._extract_zip_archive(zf, files_api.UPLOAD_ROOT / "pytest_zip_limit")
    assert exc.value.status_code == 413
    assert "too many entries" in str(exc.value.detail).lower()


def test_extract_zip_archive_rejects_expanded_size(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("large.txt", "x" * 32)
    buf.seek(0)

    upload_root = tmp_path / "uploads"
    upload_root.mkdir(exist_ok=True)
    monkeypatch.setattr(files_api, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(files_api, "FILES_MAX_UNZIPPED_BYTES", 8)

    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(HTTPException) as exc:
            files_api._extract_zip_archive(zf, files_api.UPLOAD_ROOT / "pytest_zip_size")
    assert exc.value.status_code == 413
    assert "beyond allowed size" in str(exc.value.detail).lower()
