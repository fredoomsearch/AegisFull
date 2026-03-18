import uuid
from pathlib import Path

import pytest

from app.services.project_store import register_project


@pytest.mark.anyio
async def test_agent_step_returns_local_evidence_without_llm(tmp_path: Path):
    import httpx
    import main

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "auth.py").write_text(
        "def auth_token(user_id: str) -> str:\n    return f'tok-{user_id}'\n",
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("from auth import auth_token\n", encoding="utf-8")
    register_project(project_id, tmp_path, source="workspace", status="uploaded")

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        r = await client.post(
            f"/chat/{conv_id}/agent_step",
            json={
                "message": "where is auth_token defined?",
                "use_web": False,
                "max_tool_calls": 3,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        assert payload.get("conversation_id") == conv_id
        text = payload.get("response") or ""
        assert "auth.py" in text or "main.py" in text
