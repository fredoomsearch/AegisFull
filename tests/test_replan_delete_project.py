from app.services.session_state import replan_session_state


def test_replan_delete_project_clears_active_project():
    state = {
        "active_project_id": "demo-project",
        "current_file_focus": "app/auth.py",
        "current_symbol_focus": "auth",
        "missing_evidence": [],
        "current_task": "cleanup",
    }
    next_state = replan_session_state(state, tool_name="delete_project", success=True, detail="ok", mode="tool", response_emitted=True)
    assert next_state.get("active_project_id") in {None, ""}
    assert next_state.get("current_file_focus") in {None, ""}
    assert next_state.get("current_symbol_focus") in {None, ""}
    assert "active_project" in (next_state.get("missing_evidence") or [])

