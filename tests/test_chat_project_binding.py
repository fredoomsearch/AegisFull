from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.services.project_manifest import save_project_manifest
from app.services.project_store import delete_project, register_project


@pytest.mark.anyio
async def test_bind_project_clears_planner_context_fields(tmp_path: Path):
    import httpx
    import main

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "app.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    save_project_manifest(tmp_path, project_id, chunk_count=1, chunked_files=1)
    register_project(project_id, tmp_path, source="workspace", status="uploaded")

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200
        state = (r.json() or {}).get("state") or {}

    try:
        assert state.get("active_project_id") == project_id
        assert state.get("current_file_focus") in {None, ""}
        assert state.get("current_symbol_focus") in {None, ""}
        assert state.get("current_task") in {"", None}
        assert state.get("current_subtask") in {"", None}
        assert state.get("current_topic") in {"", None}
        assert state.get("next_step") in {"", None}
        assert state.get("next_tool") in {None, ""}
        assert state.get("current_artifact_focus") in {None, ""}
        assert state.get("last_artifact") in {None, ""}
        assert state.get("last_artifact_kind") in {None, ""}
        assert state.get("last_artifact_lang") in {None, ""}
        assert state.get("last_artifact_snippet") in {None, ""}
        assert state.get("missing_evidence") == []
        assert state.get("recent_tool_failures") == []
        assert state.get("open_questions") == []
    finally:
        delete_project(project_id)
