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
