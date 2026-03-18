from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from app.api import files as files_api
from app.services.project_manifest import save_project_manifest
from app.services.project_store import delete_project, get_project


class _FakeProc:
    def __init__(self, cmd, **kwargs):
        self.cmd = list(cmd)
        self.returncode = 0
        try:
            root = Path(self.cmd[self.cmd.index("--root") + 1])
            project_id = str(self.cmd[self.cmd.index("--project-id") + 1])
            manifest_out = Path(self.cmd[self.cmd.index("--manifest-out") + 1])
            save_project_manifest(root, project_id, chunk_count=4, chunked_files=2, target=manifest_out)
        except Exception:
            self.returncode = 1

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = 1


def test_ingest_accepts_workspace_paths(monkeypatch):
    root = Path("tmp") / f"workspace_ingest_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    project_id = root.name

    monkeypatch.setattr(files_api.subprocess, "Popen", _FakeProc)

    try:
        registered = asyncio.run(files_api.register_root(files_api.RegisterRootRequest(path=str(root), project_id=project_id)))
        assert registered["project_id"] == project_id

        result = asyncio.run(
            files_api.ingest_path(
                files_api.IngestRequest(project_id=project_id, background=False)
            )
        )
        assert result["status"] == "ok"
        assert result["project_id"] == project_id
        project = get_project(project_id)
        assert project is not None
        assert project.get("status") == "ingested"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        delete_project(project_id)


def test_ingest_uses_absolute_ingest_script_path(monkeypatch):
    root = Path("tmp") / f"workspace_ingest_abs_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def ping():\n    return 'ok'\n", encoding="utf-8")
    project_id = root.name
    captured: dict[str, list[str]] = {}

    class _CaptureProc:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = list(cmd)
            self.returncode = 0
            root_arg = Path(captured["cmd"][captured["cmd"].index("--root") + 1])
            proj_arg = str(captured["cmd"][captured["cmd"].index("--project-id") + 1])
            manifest_arg = Path(captured["cmd"][captured["cmd"].index("--manifest-out") + 1])
            save_project_manifest(root_arg, proj_arg, chunk_count=2, chunked_files=1, target=manifest_arg)

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = 1

    monkeypatch.setattr(files_api.subprocess, "Popen", _CaptureProc)

    try:
        asyncio.run(files_api.register_root(files_api.RegisterRootRequest(path=str(root), project_id=project_id)))
        result = asyncio.run(files_api.ingest_path(files_api.IngestRequest(project_id=project_id, background=False)))
        assert result["status"] == "ok"
        cmd = captured.get("cmd") or []
        assert len(cmd) >= 2
        assert Path(cmd[1]).is_absolute()
        assert cmd[1].endswith("app/scripts/ingest_repo.py")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        delete_project(project_id)
