from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.api import chat as chat_api
from app.services import project_store
from app.services.project_manifest import save_project_manifest


def test_chat_answers_from_project_tools_before_llm(monkeypatch):
    root = Path("tmp") / f"tool_first_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "README.md").write_text("# Tool First\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=1)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "what files are inside app?",
            "en",
            {"active_project_id": project_id},
        )
        assert payload is not None
        assert "app/service.py" in payload["response"]
        assert payload["used_manifest"] is True
        assert payload["used_local"] is True
        assert payload["tool_kind"] == "project_files"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_answers_clamav_status_before_llm(monkeypatch):
    monkeypatch.setattr(
        "app.api.chat.generate_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
    )
    monkeypatch.setattr(
        "app.api.chat.clamav_status",
        lambda: {"status": "ready", "scanner": "clamscan", "reachable": True, "detail": "ok"},
    )
    monkeypatch.setattr(
        "app.api.chat.recent_av_events",
        lambda limit=5: [{"ts": 1, "status": "clean", "path": "/tmp/demo"}],
    )
    payload = chat_api._maybe_operations_response("show last clamav log", "en")
    assert payload is not None
    assert "ClamAV" in payload["response"]
    assert "clean" in payload["response"]
    assert payload["tool_kind"] == "clamav_status"


def test_chat_reuses_file_focus_for_followup_excerpt(monkeypatch):
    root = Path("tmp") / f"tool_focus_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "README.md").write_text("# Tool Focus\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=1)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "show me that code",
            "en",
            {"active_project_id": project_id, "current_file_focus": "app/service.py"},
        )
        assert payload is not None
        assert "File app/service.py:" in payload["response"]
        assert "def login()" in payload["response"]
        assert payload["tool_kind"] == "file_excerpt"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_prefers_planned_symbol_search_for_followup(monkeypatch):
    root = Path("tmp") / f"tool_symbol_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "README.md").write_text("# Tool Symbol\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=1)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "where is that handled?",
            "en",
            {"active_project_id": project_id, "current_symbol_focus": "login"},
            preferred_tool="project_symbols",
        )
        assert payload is not None
        assert "Matches for login:" in payload["response"]
        assert payload["tool_kind"] == "symbol_search"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_ignores_stale_file_focus_for_unrelated_question(monkeypatch):
    root = Path("tmp") / f"tool_unrelated_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "README.md").write_text("# Tool Unrelated\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=1)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "where is russia?",
            "en",
            {"active_project_id": project_id, "current_file_focus": "app/service.py"},
            preferred_tool="project_excerpt",
        )
        assert payload is None
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_turn_plan_does_not_keep_stale_project_tool_for_unrelated_question():
    plan = chat_api._build_turn_plan(
        message="where is russia?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "next_tool": "project_excerpt",
        },
    )
    assert plan.get("next_tool") != "project_excerpt"
    assert bool(plan.get("llm_required")) is True


def test_active_project_response_understands_each_part_prompt():
    root = Path("tmp") / f"tool_parts_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "README.md").write_text("# Tool Parts\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=1)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        payload = chat_api._maybe_active_project_response(
            "can you explain each part of this project?",
            "en",
            {"active_project_id": project_id},
        )
        assert isinstance(payload, str)
        assert payload.strip()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_extract_crypto_symbol_normalizes_to_binance_pair():
    assert chat_api._extract_crypto_symbol("btcusdt") == "BTCUSDT"
    assert chat_api._extract_crypto_symbol("btc") == "BTCUSDT"
    assert chat_api._extract_crypto_symbol("eth/usdc") == "ETHUSDC"
