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


def test_chat_uses_quick_tree_when_project_manifest_is_not_ready():
    root = Path("tmp") / f"tool_tree_fallback_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "README.md").write_text("# Tool Tree Fallback\n", encoding="utf-8")
    project_id = root.name
    project_store.register_project(project_id, root, source="workspace", status="ingesting")

    try:
        payload = chat_api._maybe_project_file_response(
            "can u explain me all the tree of active project?",
            "en",
            {"active_project_id": project_id},
            preferred_tool="project_files",
        )
        assert payload is not None
        assert payload["tool_kind"] == "project_status"
        assert "still getting ready" in payload["response"].lower()
        assert "quick project tree" in payload["response"].lower()
        assert "app/service.py" in payload["response"]
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
    (root / "app" / "routes.py").write_text(
        "from fastapi import APIRouter\nfrom app.service import login\nrouter = APIRouter()\n@router.get('/login')\ndef login_route():\n    return login()\n",
        encoding="utf-8",
    )
    (root / "app" / "main.py").write_text(
        "from fastapi import FastAPI\nfrom app.routes import router\napp = FastAPI()\napp.include_router(router, prefix='/auth')\n",
        encoding="utf-8",
    )
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
        assert "Project impact:" in payload["response"]
        assert "/auth/login" in payload["response"]
        assert "def login()" in payload["response"]
        assert payload["tool_kind"] == "file_excerpt"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_reuses_file_focus_for_project_clarifier_followup(monkeypatch):
    root = Path("tmp") / f"tool_focus_clarifier_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "app" / "routes.py").write_text(
        "from fastapi import APIRouter\nfrom app.service import login\nrouter = APIRouter()\n@router.get('/login')\ndef login_route():\n    return login()\n",
        encoding="utf-8",
    )
    (root / "app" / "main.py").write_text(
        "from fastapi import FastAPI\nfrom app.routes import router\napp = FastAPI()\napp.include_router(router, prefix='/auth')\n",
        encoding="utf-8",
    )
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=1)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "can u be more specific maybe?",
            "en",
            {
                "active_project_id": project_id,
                "current_file_focus": "app/service.py",
                "current_artifact_focus": "app/service.py",
                "next_tool": "project_excerpt",
                "current_task": "explain the login implementation",
            },
        )
        assert payload is not None
        assert payload["tool_kind"] == "file_excerpt"
        assert "File app/service.py:" in payload["response"]
        assert "def login()" in payload["response"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_reuses_folder_focus_for_project_clarifier_followup(monkeypatch):
    root = Path("tmp") / f"tool_folder_clarifier_{uuid.uuid4().hex[:8]}"
    (root / "api").mkdir(parents=True, exist_ok=True)
    (root / "services").mkdir(parents=True, exist_ok=True)
    (root / "api" / "routes.py").write_text("def health():\n    return True\n", encoding="utf-8")
    (root / "services" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=2, chunked_files=2)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "can u be more specific maybe?",
            "en",
            {
                "active_project_id": project_id,
                "current_file_focus": "api",
                "current_artifact_focus": "api",
                "next_tool": "project_files",
                "current_task": "explore api folder",
            },
        )
        assert payload is not None
        assert payload["tool_kind"] == "project_files"
        assert "Files under api:" in payload["response"]
        assert "api/routes.py" in payload["response"]
        assert "services/auth_service.py" not in payload["response"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_uses_named_directory_followup_for_project_folder(monkeypatch):
    root = Path("tmp") / f"tool_named_folder_{uuid.uuid4().hex[:8]}"
    (root / "api").mkdir(parents=True, exist_ok=True)
    (root / "services").mkdir(parents=True, exist_ok=True)
    (root / "api" / "routes.py").write_text("def health():\n    return True\n", encoding="utf-8")
    (root / "services" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=2, chunked_files=2)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "and services?",
            "en",
            {
                "active_project_id": project_id,
                "next_tool": "project_manifest",
                "current_task": "explain the active project",
            },
        )
        assert payload is not None
        assert payload["tool_kind"] == "project_files"
        assert "Files under services:" in payload["response"]
        assert "services/auth_service.py" in payload["response"]
        assert "api/routes.py" not in payload["response"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_uses_contextual_file_followup_inside_active_folder(monkeypatch):
    root = Path("tmp") / f"tool_contextual_file_{uuid.uuid4().hex[:8]}"
    (root / "api").mkdir(parents=True, exist_ok=True)
    (root / "services").mkdir(parents=True, exist_ok=True)
    (root / "api" / "routes.py").write_text("def health():\n    return True\n", encoding="utf-8")
    (root / "services" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=2, chunked_files=2)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "and routes?",
            "en",
            {
                "active_project_id": project_id,
                "current_file_focus": "api",
                "current_artifact_focus": "api",
                "next_tool": "project_files",
                "current_task": "explore api folder",
            },
        )
        assert payload is not None
        assert payload["tool_kind"] == "file_excerpt"
        assert "File api/routes.py:" in payload["response"]
        assert "def health()" in payload["response"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_chat_uses_parent_folder_tree_for_file_expansion_followup(monkeypatch):
    root = Path("tmp") / f"tool_parent_tree_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "app" / "routes.py").write_text("def health():\n    return True\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=2, chunked_files=2)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "what else is there?",
            "en",
            {
                "active_project_id": project_id,
                "current_file_focus": "app/service.py",
                "current_artifact_focus": "app/service.py",
                "next_tool": "project_excerpt",
                "current_task": "inspect auth implementation",
            },
        )
        assert payload is not None
        assert payload["tool_kind"] == "project_files"
        assert "Files under app:" in payload["response"]
        assert "app/routes.py" in payload["response"]
        assert "File app/service.py:" not in payload["response"]
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


def test_chat_explains_project_html_file_with_summary(monkeypatch):
    root = Path("tmp") / f"tool_html_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    (root / "portfolio_updated_new_quant.html").write_text(
        (
            "<!doctype html><html lang='en'><head>"
            "<title>Julian Grajales | Portfolio</title>"
            "<meta name='description' content='Portfolio of Julian Grajales - Full-Stack and Data Developer.' />"
            "</head><body><section>NEW · QUANT TERMINAL</section></body></html>"
        ),
        encoding="utf-8",
    )
    (root / "README.txt").write_text("Updated portfolio package.\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=2, chunked_files=1)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        monkeypatch.setattr(
            "app.api.chat.generate_response",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
        )
        payload = chat_api._maybe_project_file_response(
            "explain portfolio_updated_new_quant.html",
            "en",
            {"active_project_id": project_id},
        )
        assert payload is not None
        assert payload["tool_kind"] == "file_excerpt"
        assert "html page" in payload["response"].lower()
        assert "portfolio" in payload["response"].lower()
        assert "quant terminal" in payload["response"].lower()
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


def test_turn_plan_prefers_project_manifest_for_global_project_question_after_file_focus():
    plan = chat_api._build_turn_plan(
        message="EXPLICAME EL PROYECTO ACTIVO",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "src/app/app.routes.ts",
            "current_artifact_focus": "src/app/app.routes.ts",
            "next_tool": "project_excerpt",
        },
    )
    assert plan.get("next_tool") == "project_manifest"


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


def test_project_file_response_yields_to_manifest_for_global_project_question():
    root = Path("tmp") / f"tool_global_project_{uuid.uuid4().hex[:8]}"
    (root / "src" / "app").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app" / "app.routes.ts").write_text(
        "export const routes = [];\n",
        encoding="utf-8",
    )
    (root / "src" / "app" / "app.module.ts").write_text(
        "export class AppModule {}\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Angular Front\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=3)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        payload = chat_api._maybe_project_file_response(
            "EXPLICAME EL PROYECTO ACTIVO",
            "es",
            {
                "active_project_id": project_id,
                "current_file_focus": "src/app/app.routes.ts",
                "current_artifact_focus": "src/app/app.routes.ts",
                "next_tool": "project_excerpt",
            },
            preferred_tool="project_excerpt",
        )
        assert payload is None
        manifest_payload = chat_api._maybe_active_project_response(
            "EXPLICAME EL PROYECTO ACTIVO",
            "es",
            {
                "active_project_id": project_id,
                "current_file_focus": "src/app/app.routes.ts",
                "current_artifact_focus": "src/app/app.routes.ts",
                "next_tool": "project_excerpt",
            },
        )
        assert isinstance(manifest_payload, str)
        assert "Desglose por carpetas:" in manifest_payload
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_active_project_response_returns_deeper_architecture_breakdown():
    root = Path("tmp") / f"tool_arch_{uuid.uuid4().hex[:8]}"
    (root / "api").mkdir(parents=True, exist_ok=True)
    (root / "services").mkdir(parents=True, exist_ok=True)
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "api" / "routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/health')\ndef health():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "services" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (root / "models" / "user.py").write_text("class User:\n    pass\n", encoding="utf-8")
    (root / "main.py").write_text(
        "from fastapi import FastAPI\nfrom api.routes import router\napp = FastAPI()\napp.include_router(router, prefix='/api')\n",
        encoding="utf-8",
    )
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=4, chunked_files=4)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        payload = chat_api._maybe_active_project_response(
            "can you explain the architecture totally?",
            "en",
            {"active_project_id": project_id},
        )
        assert isinstance(payload, str)
        assert "Folder breakdown:" in payload
        assert "Runtime surfaces:" in payload
        assert "api" in payload
        assert "services" in payload
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_active_project_clarifier_reuses_previous_project_context():
    root = Path("tmp") / f"tool_arch_clarifier_{uuid.uuid4().hex[:8]}"
    (root / "api").mkdir(parents=True, exist_ok=True)
    (root / "services").mkdir(parents=True, exist_ok=True)
    (root / "api" / "routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/health')\ndef health():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "services" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (root / "main.py").write_text(
        "from fastapi import FastAPI\nfrom api.routes import router\napp = FastAPI()\napp.include_router(router, prefix='/api')\n",
        encoding="utf-8",
    )
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=3, chunked_files=3)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        payload = chat_api._maybe_active_project_response(
            "can u be more specific maybe?",
            "en",
            {
                "active_project_id": project_id,
                "next_tool": "project_manifest",
                "current_task": "explain the active project",
            },
        )
        assert isinstance(payload, str)
        assert "Folder breakdown:" in payload
        assert "Runtime surfaces:" in payload
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_project_files_response_respects_requested_folder():
    root = Path("tmp") / f"tool_folder_{uuid.uuid4().hex[:8]}"
    (root / "api").mkdir(parents=True, exist_ok=True)
    (root / "services").mkdir(parents=True, exist_ok=True)
    (root / "api" / "routes.py").write_text("def health():\n    return True\n", encoding="utf-8")
    (root / "services" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    project_id = root.name
    save_project_manifest(root, project_id, chunk_count=2, chunked_files=2)
    project_store.register_project(project_id, root, source="workspace", status="ingested")

    try:
        payload = chat_api._maybe_project_file_response(
            "what is inside api folder?",
            "en",
            {"active_project_id": project_id},
        )
        assert payload is not None
        assert payload["tool_kind"] == "project_files"
        assert "Files under api:" in payload["response"]
        assert "api/routes.py" in payload["response"]
        assert "services/auth_service.py" not in payload["response"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_upload_summary_ignores_attachment_context_noise():
    payload = chat_api._maybe_local_upload_summary_response(
        "what is that image? [Attachment context image: trust1.png] content data/uploads/proj_bad\x00noise",
        "en",
    )
    assert payload is None


def test_append_db_message_rolls_back_after_failure():
    class DummyDB:
        def __init__(self):
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True

    class DummyCrud:
        @staticmethod
        def append_message(_db, _conv_id, _role, _content):
            raise ValueError("A string literal cannot contain NUL (0x00) characters.")

    db = DummyDB()
    ok = chat_api._append_db_message(db, DummyCrud(), "conv-1", "user", "bad\x00message")
    assert ok is False
    assert db.rolled_back is True


def test_extract_crypto_symbol_normalizes_to_binance_pair():
    assert chat_api._extract_crypto_symbol("btcusdt") == "BTCUSDT"
    assert chat_api._extract_crypto_symbol("btc") == "BTCUSDT"
    assert chat_api._extract_crypto_symbol("eth/usdc") == "ETHUSDC"


def test_extract_crypto_horizon_reads_h_notation_and_minutes_text():
    assert chat_api._extract_crypto_horizon("BTCUSDT H=2m") == 2
    assert chat_api._extract_crypto_horizon("predice btc para los proximos 5 minutos") == 5
    assert chat_api._extract_crypto_horizon("explain last prediction") is None


def test_detect_crypto_followup_intent_handles_price_explain_and_trade_projection():
    assert chat_api._detect_crypto_followup_intent("BTCUSDT H=5m cual sera el precio mas aproximado") == "price"
    assert chat_api._detect_crypto_followup_intent("BTCUSDT H=2m explica la ultima prediccion") == "explain"
    assert chat_api._detect_crypto_followup_intent("BTCUSDT H=5m si vendo 0.111 btc que podria esperar") == "trade_projection"


def test_build_crypto_context_filters_by_horizon(monkeypatch):
    captured = {}

    def _fake_pairs(*, limit=5, symbol=None, horizon_minutes=None, **_kwargs):
        captured["symbol"] = symbol
        captured["horizon_minutes"] = horizon_minutes
        return [{"decision": "HOLD", "probability_up": 0.52, "current_price": 68180.0, "ts": 1}]

    monkeypatch.setattr(chat_api, "pair_predictions_with_outcomes", _fake_pairs)
    monkeypatch.setattr(chat_api, "_prediction_stats", lambda symbol, horizon_minutes=None: {"accuracy": 0.61})
    monkeypatch.setattr(chat_api, "list_trades", lambda limit=200, symbol=None: [])
    monkeypatch.setattr(chat_api, "compute_pnl", lambda *_a, **_k: {"per_symbol": {}})

    context = chat_api._build_crypto_context("BTCUSDT", horizon_minutes=2)
    assert captured["symbol"] == "BTCUSDT"
    assert captured["horizon_minutes"] == 2
    assert "last BTCUSDT: HOLD" in context


def test_crypto_direct_response_explains_latest_prediction_without_llm(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_resolve_crypto_prediction_row",
        lambda symbol, horizon_minutes, force_fresh=False: (
            {
                "id": "pred_1234567890",
                "symbol": symbol,
                "horizon_minutes": horizon_minutes,
                "current_price": 68180.0,
                "predicted_price": 68203.07,
                "probability_up": 0.522,
                "decision": "HOLD",
                "ts": 1712000000,
                "outcome": {"actual_price": 68183.33, "delta_pct": 0.0003, "hit": True},
            },
            "history",
        ),
    )
    payload = chat_api._maybe_crypto_direct_response("BTCUSDT H=2m explica la ultima prediccion", "es")
    assert payload is not None
    assert payload["tool_kind"] == "crypto_explain"
    assert "Predicción BTCUSDT H=2m" in payload["response"]
    assert "Precio estimado: 68203.07" in payload["response"]
    assert "Última comparación cerrada:" in payload["response"]
    assert "Lectura: HOLD" in payload["response"]
    assert payload["prediction_ref"]["log_id"] == "pred_1234567890"
    assert payload["prediction_ref"]["symbol"] == "BTCUSDT"
    assert payload["prediction_ref"]["horizon_minutes"] == 2
    assert payload["prediction_ref"]["source"] == "history"


def test_crypto_direct_response_projects_sell_quantity(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_resolve_crypto_prediction_row",
        lambda symbol, horizon_minutes, force_fresh=False: (
            {
                "symbol": symbol,
                "horizon_minutes": horizon_minutes,
                "current_price": 68242.19,
                "predicted_price": 68264.01,
                "probability_up": 0.521,
                "decision": "HOLD",
            },
            "history",
        ),
    )
    payload = chat_api._maybe_crypto_direct_response(
        "BTCUSDT H=5m si vendo 0.11111 btc que podria esperar",
        "es",
    )
    assert payload is not None
    assert payload["tool_kind"] == "crypto_trade_projection"
    assert "Escenario SELL con 0.11111 BTC:" in payload["response"]
    assert "Valor ahora:" in payload["response"]
    assert "Valor estimado al horizonte:" in payload["response"]
    assert "saldrías antes de una subida estimada" in payload["response"]
