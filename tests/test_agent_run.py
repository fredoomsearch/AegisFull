import uuid
from pathlib import Path

import pytest

from app.services.project_manifest import save_project_manifest
from app.services.project_store import register_project


@pytest.mark.anyio
async def test_agent_run_aggregates_evidence_without_llm(tmp_path: Path):
    import httpx
    import main

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "auth.py").write_text(
        "def auth_token(user_id: str) -> str:\n    return f'tok-{user_id}'\n",
        encoding="utf-8",
    )
    (tmp_path / "api.py").write_text("from auth import auth_token\n", encoding="utf-8")
    register_project(project_id, tmp_path, source="workspace", status="uploaded")

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        r = await client.post(
            f"/chat/{conv_id}/agent_run",
            json={
                "message": "where is auth_token defined?",
                "use_web": False,
                "max_iterations": 3,
                "max_total_tool_calls": 8,
                "max_tool_retries": 2,
                "tool_retry_backoff_ms": 10,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        assert payload.get("conversation_id") == conv_id
        assert isinstance(payload.get("iterations"), list)
        assert isinstance(payload.get("evidence"), list)
        assert isinstance(payload.get("iterations_completed"), int)
        assert isinstance(payload.get("total_tool_calls"), int)
        assert isinstance(payload.get("budget_exhausted"), bool)
        assert isinstance(payload.get("stop_reason"), str)
        text = payload.get("response") or ""
        assert "auth.py" in text or "api.py" in text

        r_turns = await client.get(f"/chat/{conv_id}/turns")
        assert r_turns.status_code == 200
        turns_payload = r_turns.json()
        items = turns_payload.get("items") or []
        assert items
        last = items[-1] if isinstance(items[-1], dict) else {}
        turn_items = last.get("items") if isinstance(last.get("items"), list) else []
        run_start = next((it for it in turn_items if isinstance(it, dict) and it.get("kind") == "run_start"), None)
        assert isinstance(run_start, dict)
        run_payload = run_start.get("payload") if isinstance(run_start.get("payload"), dict) else {}
        assert run_payload.get("max_tool_retries") == 2
        assert run_payload.get("tool_retry_backoff_ms") == 10


@pytest.mark.anyio
async def test_agent_run_stop_reason_no_tool_candidates():
    import httpx
    import main

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            f"/chat/{conv_id}/agent_run",
            json={
                "message": "hello",
                "use_web": False,
                "max_iterations": 2,
                "max_total_tool_calls": 8,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        iterations = payload.get("iterations") or []
        assert iterations
        assert iterations[0].get("stop_candidate") == "no_tool_candidates"
        assert payload.get("stop_reason") == "no_tool_candidates"
        assert payload.get("budget_exhausted") is False

        r_turns = await client.get(f"/chat/{conv_id}/turns")
        assert r_turns.status_code == 200
        items = (r_turns.json().get("items") or [])
        assert items
        last = items[-1] if isinstance(items[-1], dict) else {}
        planner_loop = ((last.get("response_context") or {}).get("planner_loop") or {})
        assert planner_loop.get("stop_reason") == "no_tool_candidates"
        turn_items = last.get("items") if isinstance(last.get("items"), list) else []
        run_stop = next((it for it in turn_items if isinstance(it, dict) and it.get("kind") == "run_stop"), None)
        assert isinstance(run_stop, dict)
        assert ((run_stop.get("payload") or {}).get("reason")) == "no_tool_candidates"


@pytest.mark.anyio
async def test_agent_run_stop_reason_plan_satisfied(tmp_path: Path):
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

        r = await client.post(
            f"/chat/{conv_id}/agent_run",
            json={
                "message": "what files are in this project?",
                "use_web": False,
                "max_iterations": 3,
                "max_total_tool_calls": 8,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        iterations = payload.get("iterations") or []
        assert iterations
        assert iterations[-1].get("stop_candidate") == "plan_satisfied"
        assert payload.get("stop_reason") == "plan_satisfied"
        assert payload.get("budget_exhausted") is False

        r_turns = await client.get(f"/chat/{conv_id}/turns")
        assert r_turns.status_code == 200
        items = (r_turns.json().get("items") or [])
        assert items
        last = items[-1] if isinstance(items[-1], dict) else {}
        planner_loop = ((last.get("response_context") or {}).get("planner_loop") or {})
        assert planner_loop.get("stop_reason") == "plan_satisfied"


@pytest.mark.anyio
async def test_agent_run_stop_reason_budget_exhausted():
    import httpx
    import main

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            f"/chat/{conv_id}/agent_run",
            json={
                "message": "show clamav status and show last ingest log",
                "use_web": False,
                "max_iterations": 3,
                "max_total_tool_calls": 1,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        iterations = payload.get("iterations") or []
        assert iterations
        assert iterations[-1].get("budget_exhausted") is True
        assert iterations[-1].get("stop_candidate") == "budget_exhausted"
        assert payload.get("stop_reason") == "budget_exhausted"
        assert payload.get("budget_exhausted") is True

        r_turns = await client.get(f"/chat/{conv_id}/turns")
        assert r_turns.status_code == 200
        items = (r_turns.json().get("items") or [])
        assert items
        last = items[-1] if isinstance(items[-1], dict) else {}
        planner_loop = ((last.get("response_context") or {}).get("planner_loop") or {})
        assert planner_loop.get("stop_reason") == "budget_exhausted"
        turn_items = last.get("items") if isinstance(last.get("items"), list) else []
        run_stop = next((it for it in turn_items if isinstance(it, dict) and it.get("kind") == "run_stop"), None)
        assert isinstance(run_stop, dict)
        assert ((run_stop.get("payload") or {}).get("reason")) == "budget_exhausted"


@pytest.mark.anyio
async def test_agent_run_stop_reason_no_new_evidence_after_web(monkeypatch):
    import httpx
    import main
    from app.api import chat as chat_api

    async def _fake_web_context(*_args, **_kwargs):  # noqa: ANN001
        return [], "", {"status": "unavailable", "source": "unavailable", "provider": "none"}

    monkeypatch.setattr(chat_api, "_build_web_context", _fake_web_context)

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            f"/chat/{conv_id}/agent_run",
            json={
                "message": "latest angular login docs",
                "use_web": True,
                "max_iterations": 3,
                "max_total_tool_calls": 6,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        iterations = payload.get("iterations") or []
        assert iterations
        assert iterations[-1].get("stop_candidate") == "no_new_evidence_after_web"
        assert payload.get("stop_reason") == "no_new_evidence_after_web"

        r_turns = await client.get(f"/chat/{conv_id}/turns")
        assert r_turns.status_code == 200
        items = (r_turns.json().get("items") or [])
        assert items
        last = items[-1] if isinstance(items[-1], dict) else {}
        planner_loop = ((last.get("response_context") or {}).get("planner_loop") or {})
        assert planner_loop.get("stop_reason") == "no_new_evidence_after_web"


@pytest.mark.anyio
async def test_agent_run_stop_reason_max_iterations_reached(tmp_path: Path, monkeypatch):
    import httpx
    import main
    from app.api import chat as chat_api

    project_id = f"proj_{uuid.uuid4().hex[:6]}"
    (tmp_path / "app.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    save_project_manifest(tmp_path, project_id, chunk_count=1, chunked_files=1)
    register_project(project_id, tmp_path, source="workspace", status="uploaded")
    conv_id = str(uuid.uuid4())

    def _fake_plan(**_kwargs):  # noqa: ANN001
        return {
            "mode": "agent",
            "source_plan": "local_only",
            "force_web": False,
            "current_task": "review project",
            "current_subtask": "collect manifest evidence",
            "next_step": "collect more evidence",
            "next_tool": "project_manifest",
            "missing_evidence": ["extra_local_confirmation"],
            "tool_candidates": ["project_manifest"],
            "tool_risks": {"project_manifest": "safe"},
            "approval_required": [],
            "actions": [{"tool": "project_manifest", "risk": "safe", "args": {}}],
            "next_action": {"tool": "project_manifest", "risk": "safe", "args": {}},
            "llm_required": False,
            "steps": ["project_manifest"],
        }

    monkeypatch.setattr(chat_api, "_build_turn_plan", _fake_plan)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(f"/chat/{conv_id}/project", json={"project_id": project_id})
        assert r.status_code == 200

        r = await client.post(
            f"/chat/{conv_id}/agent_run",
            json={
                "message": "continue analysis",
                "use_web": False,
                "max_iterations": 3,
                "max_total_tool_calls": 20,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        assert payload.get("iterations_completed") == 3
        iterations = payload.get("iterations") or []
        assert len(iterations) == 3
        assert payload.get("stop_reason") == "max_iterations_reached"
        assert iterations[-1].get("stop_candidate") == "max_iterations_reached"

        r_turns = await client.get(f"/chat/{conv_id}/turns")
        assert r_turns.status_code == 200
        items = (r_turns.json().get("items") or [])
        assert items
        last = items[-1] if isinstance(items[-1], dict) else {}
        planner_loop = ((last.get("response_context") or {}).get("planner_loop") or {})
        assert planner_loop.get("stop_reason") == "max_iterations_reached"
