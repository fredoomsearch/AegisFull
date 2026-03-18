import uuid
from pathlib import Path

import httpx
import pytest

from app.services.project_store import register_project


@pytest.mark.anyio
async def test_execute_tool_delete_project_requires_approval(tmp_path: Path):
    import main

    # Arrange: create a tiny "project" and register it
    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    register_project(project_id, tmp_path, source="workspace", status="uploaded")

    # Avoid /chat in tests (can trigger startup/LLM paths depending on env).
    # We only need a stable conversation_id for state binding + turn tracking.
    conv_id = str(uuid.uuid4())

    # NOTE: our httpx version's ASGITransport does not manage lifespan events,
    # which is what we want here (avoid startup/shutdown hangs in TestClient).
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Bind project to conversation
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        # 1) First call should require approval
        r = await client.post(
            f"/chat/{conv_id}/execute_tool",
            json={"tool": "delete_project", "args": {"project_id": project_id}},
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 409
        detail = r.json().get("detail") or {}
        assert detail.get("approval_required") is True
        token = ((detail.get("approval") or {}) if isinstance(detail.get("approval"), dict) else {}).get("token")
        assert token

        # 2) Second call with approval token should execute
        r = await client.post(
            f"/chat/{conv_id}/execute_tool",
            json={"tool": "delete_project", "args": {"project_id": project_id}, "approval_token": token},
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        assert payload.get("tool") == "delete_project"


@pytest.mark.anyio
async def test_execute_tool_returns_followup_plan_context(tmp_path: Path):
    import main

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    register_project(project_id, tmp_path, source="workspace", status="uploaded")
    conv_id = str(uuid.uuid4())

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        r = await client.post(
            f"/chat/{conv_id}/execute_tool",
            json={"tool": "project_files", "args": {"project_id": project_id, "q": "app", "limit": 10}},
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        assert isinstance(ctx.get("tool_candidates"), list)
        assert isinstance(ctx.get("actions"), list)
        assert "source_plan" in ctx
        assert "next_step" in ctx


@pytest.mark.anyio
async def test_execute_tool_can_auto_continue_when_requested(tmp_path: Path, monkeypatch):
    import main
    from app.api import chat as chat_api

    async def _fake_agent_continue(conversation_id, body, request):  # noqa: ANN001
        return chat_api.AgentRunResponse(
            ok=True,
            conversation_id=conversation_id,
            response="continued-ok",
            iterations=[
                {
                    "iteration": 1,
                    "plan": {
                        "source_plan": "local_only",
                        "next_step": "done",
                        "next_tool": None,
                        "tool_candidates": ["project_manifest"],
                        "approval_required": [],
                        "actions": [{"tool": "project_manifest", "risk": "safe", "args": {}}],
                        "llm_required": False,
                    },
                }
            ],
            evidence=[],
            sources=[],
            web_meta={"status": "not-used", "source": "not-used"},
        )

    monkeypatch.setattr(chat_api, "agent_continue", _fake_agent_continue)

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    register_project(project_id, tmp_path, source="workspace", status="uploaded")
    conv_id = str(uuid.uuid4())

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        # Trigger approval first
        r = await client.post(
            f"/chat/{conv_id}/execute_tool",
            json={"tool": "delete_project", "args": {"project_id": project_id}},
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 409
        token = (((r.json().get("detail") or {}).get("approval") or {}).get("token"))
        assert token

        # Approval + auto continuation
        r = await client.post(
            f"/chat/{conv_id}/execute_tool",
            json={
                "tool": "delete_project",
                "args": {"project_id": project_id},
                "approval_token": token,
                "continue_after": True,
                "continue_synthesize": True,
            },
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("continued") is True
        continue_result = payload.get("continue_result") or {}
        assert continue_result.get("continued") is True
        assert continue_result.get("response") == "continued-ok"


@pytest.mark.anyio
async def test_execute_tool_continue_after_reports_skip_reason_when_no_plan(tmp_path: Path, monkeypatch):
    import main
    from app.api import chat as chat_api

    def _fake_replan(*_args, **_kwargs):  # noqa: ANN001
        # Explicitly return a state without next_step/next_tool so continuation is unavailable.
        return {
            "active_project_id": None,
            "next_step": "",
            "next_tool": None,
            "missing_evidence": [],
            "lang": "en",
        }

    monkeypatch.setattr(chat_api, "_replan_conversation_state", _fake_replan)

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    register_project(project_id, tmp_path, source="workspace", status="uploaded")
    conv_id = str(uuid.uuid4())

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        r = await client.post(
            f"/chat/{conv_id}/execute_tool",
            json={
                "tool": "project_files",
                "args": {"project_id": project_id, "q": "app", "limit": 10},
                "continue_after": True,
            },
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("continued") is False
        continue_result = payload.get("continue_result") or {}
        assert continue_result.get("continued") is False
        assert continue_result.get("reason") == "no-continue-plan"
