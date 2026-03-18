import uuid
from pathlib import Path

import pytest

from app.services.project_store import register_project


@pytest.mark.anyio
async def test_agent_step_blocks_on_sensitive_tool_request(tmp_path: Path):
    import httpx
    import main

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    register_project(project_id, tmp_path, source="workspace", status="uploaded")

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        r = await client.post(
            f"/chat/{conv_id}/agent_step",
            json={"message": "delete this project", "use_web": False, "max_tool_calls": 2, "synthesize": False, "lang": "en"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        assert "approval" in str(payload.get("response") or "").lower()
        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        candidates = plan.get("tool_candidates") if isinstance(plan.get("tool_candidates"), list) else []
        assert "delete_project" in candidates
