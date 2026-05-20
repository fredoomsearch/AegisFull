from __future__ import annotations

from app.api import chat as chat_api


def test_non_project_question_with_active_project_prefers_web_only():
    source_plan = chat_api._decide_source_plan(
        "where is russia?",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
            "next_tool": "project_excerpt",
        },
    )
    assert source_plan == "web_only"


def test_generic_code_prompt_with_active_project_prefers_web_only():
    source_plan = chat_api._decide_source_plan(
        "build a login page with angular and python backend",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
    )
    assert source_plan == "web_only"


def test_generic_backend_structure_prompt_with_active_project_prefers_web_only():
    source_plan = chat_api._decide_source_plan(
        "how to structure backend folders in python?",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
            "next_tool": "project_excerpt",
            "current_task": "review authentication flow",
        },
    )
    assert source_plan == "web_only"


def test_pasted_code_blob_with_active_project_prefers_local_only():
    source_plan = chat_api._decide_source_plan(
        (
            "from __future__ import annotations\n"
            "import os\n"
            "def login(user: str) -> bool:\n"
            "    return bool(user)\n"
            "class AuthService:\n"
            "    pass\n"
            "what does this do?"
        ),
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={"active_project_id": "demo-project"},
    )
    assert source_plan == "local_only"


def test_attachment_blob_wrapped_around_project_question_stays_local():
    raw = (
        "what u can tell me about active project ?\n\n"
        "[Attachment context image: trust1.png]\n"
        "Local visual analysis (no external services):\n"
        "For programming questions: produce COMPLETE runnable code."
    )
    source_plan = chat_api._decide_source_plan(
        raw,
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
            "next_tool": "project_manifest",
        },
    )
    assert source_plan == "local_only"
    plan = chat_api._build_turn_plan(
        message=raw,
        mode_value="chat",
        source_plan=source_plan,
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
            "next_tool": "project_manifest",
        },
    )
    assert plan.get("next_tool") in {"project_manifest", "project_excerpt"}
    assert bool(plan.get("ambiguous_route")) is False


def test_web_mode_with_active_project_scope_prefers_local_plus_web():
    source_plan = chat_api._decide_source_plan(
        "can u explain me all the tree of active project?",
        mode_value="web",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "next_tool": "project_manifest",
        },
    )
    assert source_plan == "local+web"


def test_web_mode_with_attachment_context_stays_local_only():
    source_plan = chat_api._decide_source_plan(
        "what is that image?\n\n[Attachment context image: trust1.png]\nDetected text: example",
        mode_value="web",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=False,
        session_state={},
    )
    assert source_plan == "local_only"


def test_repo_file_prompt_without_active_project_stays_local_only():
    source_plan = chat_api._decide_source_plan(
        "read main.py",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=False,
        session_state={},
    )
    assert source_plan == "local_only"


def test_repo_tree_prompt_without_active_project_stays_local_only():
    source_plan = chat_api._decide_source_plan(
        "show files inside repo",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=False,
        session_state={},
    )
    assert source_plan == "local_only"


def test_missing_evidence_skips_attachment_context_questions():
    resp = chat_api._maybe_missing_evidence_response(
        "what is that image?\n\n[Attachment context image: trust1.png]\nDetected text: example",
        "en",
        {
            "missing_evidence": ["file_or_symbol_focus"],
            "active_project_id": "demo-project",
        },
        source_plan="local_only",
    )
    assert resp is None


def test_routing_clarification_skipped_for_attachment_context():
    resp = chat_api._maybe_routing_clarification_response(
        "what is that image?\n\n[Attachment context image: trust1.png]\nDetected text: example",
        "en",
        {
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
        source_plan="local_only",
        mode_value="chat",
        force_web=False,
    )
    assert resp is None


def test_followup_more_specific_with_active_project_stays_local():
    source_plan = chat_api._decide_source_plan(
        "can u be more specific maybe?",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "next_tool": "project_manifest",
        },
    )
    assert source_plan == "local_only"


def test_followup_folder_listing_with_active_project_stays_local():
    source_plan = chat_api._decide_source_plan(
        "que carpetas hay?",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "next_tool": "project_manifest",
        },
    )
    assert source_plan == "local_only"


def test_directory_named_followup_with_active_project_stays_local(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_load_active_project_manifest",
        lambda _state: {"file_tree": ["api/routes.py", "services/auth_service.py"]},
    )
    source_plan = chat_api._decide_source_plan(
        "and services?",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "next_tool": "project_manifest",
            "current_task": "explain the active project",
        },
    )
    assert source_plan == "local_only"


def test_routing_clarification_skipped_for_explicit_build_intent():
    resp = chat_api._maybe_routing_clarification_response(
        "build a login page with angular and python backend",
        "en",
        {
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
        source_plan="local_only",
        mode_value="chat",
        force_web=False,
    )
    assert resp is None


def test_routing_clarification_when_ambiguous_general_prompt():
    resp = chat_api._maybe_routing_clarification_response(
        "what is this?",
        "en",
        {
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
        source_plan="local_only",
        mode_value="chat",
        force_web=False,
    )
    assert resp is not None
    assert resp.get("tool_kind") == "routing_clarification"


def test_routing_clarification_skipped_for_clear_project_prompt_without_prefix(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_maybe_active_project_response",
        lambda *_args, **_kwargs: "Project summary",
    )
    resp = chat_api._maybe_routing_clarification_response(
        "can you explain each part of this project?",
        "en",
        {
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
        source_plan="local_only",
        mode_value="chat",
        force_web=False,
    )
    assert resp is None


def test_routing_clarification_skipped_for_project_followup_prompt():
    resp = chat_api._maybe_routing_clarification_response(
        "can u explain better?",
        "en",
        {
            "active_project_id": "demo-project",
            "next_tool": "project_manifest",
        },
        source_plan="local_only",
        mode_value="chat",
        force_web=False,
    )
    assert resp is None


def test_local_plus_web_prefers_web_route_for_generic_prompt():
    prefer_web = chat_api._should_prefer_web_route(
        "search how to build a login page with angular and python backend",
        source_plan="local+web",
        mode_value="chat",
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
    )
    assert prefer_web is True


def test_local_override_disables_web_route_preference():
    prefer_web = chat_api._should_prefer_web_route(
        "use local only and explain this project",
        source_plan="local+web",
        mode_value="chat",
        force_web=False,
        force_local=True,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
        },
    )
    assert prefer_web is False


def test_local_plus_web_keeps_local_route_for_explicit_project_scope():
    prefer_web = chat_api._should_prefer_web_route(
        "project: explain app/auth.py in this repo",
        source_plan="local+web",
        mode_value="chat",
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
    )
    assert prefer_web is False


def test_turn_plan_flags_ambiguous_low_confidence_local_route():
    plan = chat_api._build_turn_plan(
        message="where is russia?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
        },
    )
    assert bool(plan.get("ambiguous_route")) is True
    assert float(plan.get("routing_confidence") or 1.0) < 0.45


def test_turn_plan_keeps_high_confidence_for_explicit_project_scope():
    plan = chat_api._build_turn_plan(
        message="project: explain app/auth.py in this repo",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={"active_project_id": "demo-project"},
    )
    assert bool(plan.get("ambiguous_route")) is False
    assert float(plan.get("routing_confidence") or 0.0) >= 0.45
