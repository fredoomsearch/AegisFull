from app.api import chat as chat_api


def test_build_turn_plan_includes_tool_risks_and_approval_required():
    plan = chat_api._build_turn_plan(
        message="show last ingest log",
        mode_value="agent",
        source_plan="local_only",
        has_active_project=False,
        force_web=False,
        session_state={},
    )
    assert isinstance(plan, dict)
    assert "tool_risks" in plan
    assert "approval_required" in plan
    assert isinstance(plan["tool_risks"], dict)
    assert isinstance(plan["approval_required"], list)
    # Known tools should have known risk labels.
    if "ingest_log" in (plan.get("tool_candidates") or []):
        assert plan["tool_risks"].get("ingest_log") in {"safe", "unknown"}


def test_delete_project_requires_approval_when_active_project_present():
    plan = chat_api._build_turn_plan(
        message="please delete this project",
        mode_value="agent",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={"active_project_id": "demo-project"},
    )
    candidates = plan.get("tool_candidates") or []
    assert "delete_project" in candidates
    assert "delete_project" in (plan.get("approval_required") or [])
    assert (plan.get("tool_risks") or {}).get("delete_project") == "sensitive"


def test_build_turn_plan_includes_structured_actions_for_ui():
    plan = chat_api._build_turn_plan(
        message="what does this project contain? show architecture",
        mode_value="agent",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={"active_project_id": "demo-project", "current_symbol_focus": "auth"},
    )
    actions = plan.get("actions") or []
    assert isinstance(actions, list)
    assert actions, "expected at least one suggested action"
    first = actions[0]
    assert isinstance(first, dict)
    assert first.get("tool")
    assert "label_en" in first and "label_es" in first

    tools = {a.get("tool") for a in actions if isinstance(a, dict)}
    # For project questions, we should suggest at least manifest summary.
    assert "project_manifest" in tools


def test_response_context_carries_actions_for_chat_ui():
    plan = chat_api._build_turn_plan(
        message="show me the code in that file",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={"active_project_id": "demo-project", "current_file_focus": "app/auth.py"},
    )
    ctx = chat_api._build_response_context(
        source_plan="local_only",
        active_project_id="demo-project",
        lang="en",
        session_state={"active_project_id": "demo-project", "current_file_focus": "app/auth.py", "next_step": "inspect auth"},
        plan=plan,
        used_local=True,
        used_manifest=True,
        raw_sources=None,
    )
    assert isinstance(ctx, dict)
    assert isinstance(ctx.get("actions"), list)
