from app.api import chat as chat_api
from app.memory import get_conversation_state, get_or_create_conversation, update_memory
from app.models.llm_utils import build_answer_style_contract, build_messages, detect_build_intent, is_code_question, rewrite_contextual_query
from app.services import session_state as session_state_mod
from app.services.session_state import build_comp_snapshot, replan_session_state, update_session_state


def test_session_state_tracks_goal_stack_and_constraints():
    conv_id = get_or_create_conversation(None)
    update_memory(
        conv_id,
        "Build a concise login system with Angular frontend and Python backend",
        "```python\nprint('ok')\n```",
        mode="code",
    )
    state = get_conversation_state(conv_id)
    assert state["frontend"] == "angular"
    assert state["backend"] == "python"
    assert "login" in (state.get("goal") or "").lower()
    assert state["answer_style"]["concise"] is True
    assert state["last_artifact_kind"] == "login_flow"
    assert "print('ok')" in (state.get("last_artifact_snippet") or "")
    assert (state.get("last_artifact_lang") or "") in {"python", "py"}
    assert state["next_step"]


def test_contextual_query_reuses_session_goal():
    state = {
        "goal": "build login flow with angular frontend and python backend",
        "current_topic": "login flow",
        "backend": "python",
        "frontend": "angular",
        "entities": ["jwt", "auth"],
        "last_web_query": "",
        "answer_style": {},
    }
    query = rewrite_contextual_query("best JWT library?", session_state=state)
    q = query.lower()
    assert "login" in q
    assert "angular" in q
    assert "python" in q
    assert "jwt" in q


def test_contextual_query_does_not_drag_previous_world_query_into_new_topic():
    state = {
        "goal": "Where is russia ?",
        "current_topic": "Where is russia ?",
        "backend": None,
        "frontend": None,
        "entities": [],
        "last_web_query": "Where is russia",
        "answer_style": {},
    }
    query = rewrite_contextual_query(
        "Ok what u can toll me about actual war of usa whit iran?",
        session_state=state,
    ).lower()
    assert "iran" in query
    assert "usa" in query
    assert "russia" not in query


def test_contextual_query_reuses_previous_web_query_only_for_referential_followup():
    state = {
        "goal": "Where is russia ?",
        "current_topic": "Where is russia ?",
        "backend": None,
        "frontend": None,
        "entities": [],
        "last_web_query": "actual war usa iran",
        "answer_style": {},
    }
    query = rewrite_contextual_query(
        "Ok and today on 2026 hows going that ?",
        session_state=state,
    ).lower()
    assert "actual war usa iran" in query
    assert "2026" in query
    assert "russia" not in query


def test_build_messages_includes_session_state_and_answer_contract():
    session_state = {
        "goal": "build login flow",
        "current_topic": "jwt auth",
        "backend": "python",
        "frontend": "angular",
        "entities": ["jwt", "auth"],
        "constraints": ["concise"],
        "open_questions": ["best jwt package?"],
        "answer_style": {"concise": True, "code_first": True, "delta_only": True, "no_redundancy": True},
    }
    msgs = build_messages(
        "conv-test",
        "best JWT library?",
        history_messages=[{"role": "user", "content": "We are building login"}, {"role": "assistant", "content": "Use JWT"}],
        summary_override="login discussion",
        session_state=session_state,
    )
    system = msgs[0]["content"]
    assert "Semantic conversation contract" in system
    assert "Structured session context" in system
    assert "Session goal: build login flow" in system
    assert "Response style rules" in system
    assert "answer only the delta" in system.lower()


def test_answer_style_contract_enforces_concise_default():
    contract = build_answer_style_contract("where is russia?", session_state={"answer_style": {"concise": True}})
    assert "at most 5 short sentences" in contract
    assert "Do not repeat context already established" in contract



def test_conversational_act_classifier_detects_act_and_source_policy():
    greeting = session_state_mod.classify_conversational_act("hola", session_state={})
    definition = session_state_mod.classify_conversational_act("what is a login?", session_state={})
    run_question = session_state_mod.classify_conversational_act("can I run this analysis?", session_state={})
    execute = session_state_mod.classify_conversational_act("run analysis on this repo", session_state={})

    assert greeting["act"] == "greeting"
    assert greeting["source_policy"] == "local"
    assert definition["act"] == "definition"
    assert definition["subject"]
    assert run_question["act"] == "question_about_run"
    assert run_question["allow_run"] is False
    assert execute["act"] == "execute_analysis"
    assert execute["allow_run"] is True


def test_session_state_routes_greeting_to_llm_synthesis():
    state = update_session_state(None, "hola", "", mode="chat", active_project_id=None)
    assert state["conversation_act"] == "greeting"
    assert state["source_policy"] == "local"
    assert state["next_tool"] == "llm_synthesis"
    assert "answer directly" in state["next_step"].lower()


def test_session_state_routes_identity_and_capability_chat_to_llm_synthesis():
    identity = update_session_state(None, "who are you", "", mode="chat", active_project_id=None)
    capability = update_session_state(None, "what can you do", "", mode="chat", active_project_id=None)

    assert identity["conversation_act"] == "help"
    assert identity["source_policy"] == "local"
    assert identity["next_tool"] == "llm_synthesis"

    assert capability["conversation_act"] == "help"
    assert capability["source_policy"] == "local"
    assert capability["next_tool"] == "llm_synthesis"


def test_session_state_routes_internet_access_chat_to_local_help():
    internet = update_session_state(None, "do you have access to internet?", "", mode="chat", active_project_id=None)

    assert internet["conversation_act"] == "help"
    assert internet["source_policy"] == "local"
    assert internet["next_tool"] == "llm_synthesis"


def test_session_state_routes_acknowledgement_to_local_llm_synthesis():
    ack = update_session_state(None, "ok thanks", "", mode="chat", active_project_id=None)

    assert ack["conversation_act"] == "acknowledgement"
    assert ack["source_policy"] == "local"
    assert ack["next_tool"] == "llm_synthesis"


def test_session_state_routes_web_definition_to_web_search():
    state = update_session_state(None, "what is the capital of japan?", "", mode="chat", active_project_id=None)
    assert state["conversation_act"] == "definition"
    assert state["source_policy"] == "web"
    assert state["web_required"] is True
    assert state["next_tool"] == "web_search"


def test_session_state_routes_analysis_to_llm_synthesis_and_allows_run():
    state = update_session_state(None, "run analysis on this repo", "", mode="chat", active_project_id=None)
    assert state["conversation_act"] == "execute_analysis"
    assert state["allow_run"] is True
    assert state["next_tool"] == "llm_synthesis"


def test_comp_snapshot_combines_semantic_and_planner_state():
    state = update_session_state(None, "what is the capital of japan?", "", mode="chat", active_project_id=None)
    comp = build_comp_snapshot(
        state,
        plan={
            "next_tool": "web_search",
            "next_step": "fetch supporting web evidence",
            "llm_required": True,
            "routing_confidence": 0.7,
        },
    )
    assert comp["controller"] == "comp"
    assert comp["act"] == "definition"
    assert comp["route_mode"] == "web"
    assert comp["next_tool"] == "web_search"
    assert comp["planner"]["routing_confidence"] == 0.7
    assert comp["quantitative"]["gate"] == "review"
    assert comp["quantitative"]["confidence_bucket"] == "medium"


def test_build_messages_includes_last_artifact_snippet_for_continuity():
    session_state = {
        "goal": "build login flow",
        "answer_style": {"delta_only": True, "code_first": True},
        "last_artifact": "login endpoint",
        "last_artifact_kind": "api_endpoint",
        "last_artifact_lang": "python",
        "last_artifact_snippet": "from fastapi import APIRouter\nrouter = APIRouter()\n",
    }
    msgs = build_messages(
        "conv-test",
        "now add validation",
        history_messages=[{"role": "user", "content": "build login endpoint"}, {"role": "assistant", "content": "ok"}],
        summary_override="login",
        session_state=session_state,
    )
    system = msgs[0]["content"]
    assert "Last artifact snippet" in system
    assert "fastapi" in system.lower()


def test_prepare_web_query_uses_conversation_context():
    conv_id = get_or_create_conversation(None)
    update_memory(
        conv_id,
        "I am building a login page with Angular frontend and Python backend",
        "Noted.",
        mode="code",
    )
    state = get_conversation_state(conv_id)
    query = chat_api._prepare_web_query("best JWT library?", session_state=state).lower()
    assert "login" in query
    assert "angular" in query
    assert "python" in query


def test_generic_followup_text_is_not_misclassified_as_code_or_build():
    message = "Ok and today on 2026 hows going that ?"
    assert is_code_question(message) is False
    assert bool(detect_build_intent(message).get("is_build")) is False


def test_session_state_tracks_missing_evidence_for_project_questions():
    conv_id = get_or_create_conversation(None)
    update_memory(
        conv_id,
        "Where is auth handled in this backend?",
        "Need project context first.",
        mode="chat",
    )
    state = get_conversation_state(conv_id)
    assert "active_project" in state["missing_evidence"]


def test_session_state_tracks_missing_evidence_for_imperative_project_request():
    state = update_session_state(
        None,
        "explain the active project",
        "",
        mode="chat",
        active_project_id=None,
    )
    assert "active_project" in state["missing_evidence"]


def test_turn_plan_fail_closes_imperative_project_request_without_active_project():
    state = update_session_state(
        None,
        "explain the active project",
        "",
        mode="chat",
        active_project_id=None,
    )
    plan = chat_api._build_turn_plan(
        message="explain the active project",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=False,
        force_web=False,
        session_state=state,
    )
    assert "active_project" in plan["missing_evidence"]
    assert plan["llm_required"] is False


def test_missing_evidence_response_handles_imperative_project_request():
    state = update_session_state(
        None,
        "explain the active project",
        "",
        mode="chat",
        active_project_id=None,
    )
    payload = chat_api._maybe_missing_evidence_response(
        "explain the active project",
        "en",
        state,
        source_plan="local_only",
    )
    assert payload is not None
    assert payload["tool_kind"] == "missing_evidence"
    assert "active project" in payload["response"].lower()


def test_session_state_does_not_require_project_for_generic_login_definition():
    state = update_session_state(
        None,
        "what's a login?",
        "",
        mode="chat",
        active_project_id=None,
    )
    assert "active_project" not in (state.get("missing_evidence") or [])


def test_turn_plan_uses_operational_planner_state_for_local_project_questions():
    state = update_session_state(
        None,
        "Where is auth handled in this backend?",
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    plan = chat_api._build_turn_plan(
        message="Where is auth handled in this backend?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state=state,
    )
    assert plan["current_task"]
    assert plan["next_step"]
    assert plan["next_tool"] in {"project_manifest", "project_excerpt", "project_symbols"}
    assert plan["llm_required"] is False
    assert "project_manifest" in plan["tool_candidates"]


def test_turn_plan_prefers_symbol_search_from_existing_focus():
    plan = chat_api._build_turn_plan(
        message="where is that handled?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_task": "review auth flow",
            "current_symbol_focus": "login",
            "current_artifact_focus": "login",
        },
    )
    assert plan["next_tool"] == "project_symbols"
    assert plan["llm_required"] is False


def test_turn_plan_prefers_symbol_search_for_explicit_symbol_lookup():
    plan = chat_api._build_turn_plan(
        message="where is auth_token defined?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_task": "inspect auth flow",
        },
    )
    assert plan["next_tool"] == "project_symbols"
    assert "project_symbols" in plan["tool_candidates"]
    assert plan["llm_required"] is False


def test_turn_plan_prefers_excerpt_from_existing_file_focus():
    plan = chat_api._build_turn_plan(
        message="show me the code",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_task": "inspect auth implementation",
            "current_file_focus": "app/service.py",
            "current_artifact_focus": "app/service.py",
        },
    )
    assert plan["next_tool"] == "project_excerpt"
    assert plan["llm_required"] is False


def test_session_focus_decay_clears_stale_file_focus():
    state = {
        "active_project_id": "demo-project",
        "current_file_focus": "app/service.py",
        "current_artifact_focus": "app/service.py",
        "focus_turn_budget": 1,
        "focus_last_touch_ms": 0,
        "next_tool": "project_excerpt",
    }
    updated = update_session_state(
        state,
        "where is russia?",
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    assert updated.get("current_file_focus") in {None, ""}
    assert updated.get("current_symbol_focus") in {None, ""}
    assert updated.get("current_artifact_focus") in {None, ""}
    assert updated.get("next_tool") != "project_excerpt"


def test_session_focus_decay_keeps_focus_on_referential_followup():
    state = {
        "active_project_id": "demo-project",
        "current_file_focus": "app/service.py",
        "current_artifact_focus": "app/service.py",
        "focus_turn_budget": 1,
        "focus_last_touch_ms": 0,
    }
    updated = update_session_state(
        state,
        "show that code",
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    assert updated.get("current_file_focus") == "app/service.py"
    assert int(updated.get("focus_turn_budget") or 0) >= 1


def test_session_focus_ttl_expiry_clears_focus(monkeypatch):
    monkeypatch.setattr(session_state_mod, "FOCUS_TTL_MS", 1)
    state = {
        "active_project_id": "demo-project",
        "current_file_focus": "app/service.py",
        "current_artifact_focus": "app/service.py",
        "focus_turn_budget": 3,
        "focus_last_touch_ms": 1,
    }
    updated = update_session_state(
        state,
        "random question",
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    assert updated.get("current_file_focus") in {None, ""}


def test_source_plan_prefers_local_when_project_focus_already_exists():
    source_plan = chat_api._decide_source_plan(
        "show me the code",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "current_file_focus": "app/service.py",
            "current_artifact_focus": "app/service.py",
            "next_tool": "project_excerpt",
        },
    )
    assert source_plan == "local_only"


def test_source_plan_falls_back_to_local_plus_web_after_recent_web_failures():
    source_plan = chat_api._decide_source_plan(
        "latest jwt docs",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "recent_tool_failures": ["web_search:unavailable"],
        },
    )
    assert source_plan == "local+web"


def test_source_plan_web_mode_stays_web_only_to_avoid_project_hijack():
    source_plan = chat_api._decide_source_plan(
        "latest jwt docs",
        mode_value="web",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={
            "active_project_id": "demo-project",
            "recent_tool_failures": ["web_search:unavailable"],
        },
    )
    assert source_plan == "web_only"


def test_source_plan_keeps_social_chat_local_even_when_web_mode_is_requested():
    source_plan = chat_api._decide_source_plan(
        "what can you do",
        mode_value="web",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=False,
        session_state={},
    )
    assert source_plan == "local_only"


def test_strip_attachment_context_keeps_only_user_query():
    raw = (
        "what u can toll me about active project ?\n\n"
        "[Attachment context image: trust1.png]\n"
        "Local visual analysis (no external services):\n"
        "- Resolution: 1868x997.\n"
        "For programming questions: produce COMPLETE runnable code."
    )
    assert chat_api._strip_attachment_context(raw) == "what u can toll me about active project ?"


def test_attachment_context_does_not_force_code_or_build_intent():
    raw = (
        "what u can toll me about active project ?\n\n"
        "[Attachment context image: trust1.png]\n"
        "Local visual analysis (no external services):\n"
        "For programming questions: produce COMPLETE runnable code."
    )
    routing = chat_api._strip_attachment_context(raw)
    assert is_code_question(routing) is False
    assert bool(detect_build_intent(routing).get("is_build")) is False


def test_source_plan_ignores_attachment_context_for_active_project_question():
    raw = (
        "what u can toll me about active project ?\n\n"
        "[Attachment context image: trust1.png]\n"
        "Local visual analysis (no external services):\n"
        "For programming questions: produce COMPLETE runnable code."
    )
    source_plan = chat_api._decide_source_plan(
        chat_api._strip_attachment_context(raw),
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


def test_missing_evidence_response_requires_active_project_before_guessing():
    state = update_session_state(
        None,
        "Where is auth handled in this backend?",
        "",
        mode="chat",
        active_project_id=None,
    )
    payload = chat_api._maybe_missing_evidence_response(
        "Where is auth handled in this backend?",
        "en",
        state,
        source_plan="local_only",
    )
    assert payload is not None
    assert payload["tool_kind"] == "missing_evidence"
    assert "active project" in payload["response"].lower()


def test_response_context_exposes_planner_and_artifact_fields():
    state = {
        "current_task": "build login flow",
        "current_subtask": "pick jwt package",
        "next_step": "inspect auth files",
        "next_tool": "project_manifest",
        "missing_evidence": ["active_project"],
        "last_artifact": "login flow",
        "last_artifact_kind": "login_flow",
        "current_artifact_focus": "login flow",
        "recent_tool_failures": ["web_search:unavailable"],
    }
    context = chat_api._build_response_context(
        source_plan="local_only",
        active_project_id=None,
        lang="en",
        session_state=state,
        used_local=False,
        plan={"tool_candidates": ["project_manifest", "project_excerpt"], "llm_required": False},
    )
    assert context["current_task"] == "build login flow"
    assert context["current_subtask"] == "pick jwt package"
    assert context["next_step"] == "inspect auth files"
    assert context["next_tool"] == "project_manifest"
    assert context["last_artifact_kind"] == "login_flow"
    assert context["current_artifact_focus"] == "login flow"
    assert context["recent_tool_failures"] == ["web_search:unavailable"]
    assert context["tool_candidates"] == ["project_manifest", "project_excerpt"]
    assert context["llm_required"] is False


def test_response_context_exposes_crypto_prediction_reference():
    context = chat_api._build_response_context(
        source_plan="local_only",
        active_project_id=None,
        lang="en",
        session_state={"current_symbol_focus": "BTCUSDT"},
        used_local=True,
        effective_tool="crypto_explain",
        effective_tool_status="ok",
        crypto_prediction_ref={
            "log_id": "pred_1234567890",
            "symbol": "btcusdt",
            "horizon_minutes": 2,
            "ts": 1712000000,
            "source": "history",
            "decision": "hold",
        },
    )
    assert context["crypto_prediction_ref"] == {
        "log_id": "pred_1234567890",
        "symbol": "BTCUSDT",
        "horizon_minutes": 2,
        "ts": 1712000000,
        "source": "history",
        "decision": "HOLD",
    }


def test_replan_session_state_switches_from_failed_web_to_local_project():
    state = {
        "active_project_id": "demo-project",
        "current_task": "review auth flow",
        "next_tool": "web_search",
        "missing_evidence": ["fresh_web_context"],
        "last_user_request": "latest JWT docs",
    }
    replanned = replan_session_state(
        state,
        tool_name="web_search",
        success=False,
        detail="unavailable",
        mode="web",
    )
    assert replanned["next_tool"] == "project_manifest"
    assert "web_search:unavailable" in replanned["recent_tool_failures"]


def test_topic_switch_clears_stale_web_failure_context():
    state = {
        "goal": "review auth flow",
        "current_topic": "review auth flow",
        "current_task": "review auth flow",
        "last_web_query": "latest jwt docs",
        "last_web_sources": ["https://example.com/jwt"],
        "last_web_findings": ["jwt docs"],
        "recent_tool_failures": ["web_search:unavailable", "project_excerpt:missing path"],
    }
    updated = update_session_state(
        state,
        "what is the capital of japan?",
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    assert updated["last_web_query"] == ""
    assert updated["last_web_sources"] == []
    assert updated["last_web_findings"] == []
    assert "web_search:unavailable" not in (updated.get("recent_tool_failures") or [])
    assert "project_excerpt:missing path" in (updated.get("recent_tool_failures") or [])
    source_plan = chat_api._decide_source_plan(
        "what is the capital of japan?",
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=True,
        session_state=updated,
    )
    assert source_plan == "web_only"


def test_replan_session_state_after_direct_project_response_sets_followup_focus():
    state = {
        "active_project_id": "demo-project",
        "current_task": "review auth flow",
        "current_file_focus": "app/auth.py",
        "current_artifact_focus": "app/auth.py",
        "next_tool": "project_manifest",
    }
    replanned = replan_session_state(
        state,
        tool_name="project_manifest",
        success=True,
        detail="answered from local project context",
        mode="chat",
        response_emitted=True,
    )
    assert replanned["next_tool"] == "project_excerpt"
    assert "app/auth.py" in replanned["next_step"]
    assert "app/auth.py" in replanned["current_subtask"]


def test_replan_session_state_after_broad_project_response_keeps_manifest_followup():
    state = {
        "active_project_id": "demo-project",
        "current_task": "explain the active project",
        "current_topic": "active project overview",
        "next_tool": "project_manifest",
    }
    replanned = replan_session_state(
        state,
        tool_name="project_manifest",
        success=True,
        detail="answered from local project context",
        mode="chat",
        response_emitted=True,
    )
    assert replanned["next_tool"] == "project_manifest"
    assert replanned["next_step"]
    assert "project" in replanned["next_step"].lower()


def test_replan_session_state_after_project_files_response_keeps_folder_followup():
    state = {
        "active_project_id": "demo-project",
        "current_task": "explore api folder",
        "current_file_focus": "api",
        "current_artifact_focus": "api",
        "next_tool": "project_files",
    }
    replanned = replan_session_state(
        state,
        tool_name="project_files",
        success=True,
        detail="listed folder contents",
        mode="chat",
        response_emitted=True,
    )
    assert replanned["next_tool"] == "project_files"
    assert "folder api" in replanned["next_step"].lower()


def test_replan_session_state_after_llm_response_keeps_artifact_continuity():
    state = {
        "current_task": "build login flow",
        "current_artifact_focus": "login flow",
        "last_artifact": "login flow",
        "last_artifact_kind": "login_flow",
    }
    replanned = replan_session_state(
        state,
        tool_name="llm_synthesis",
        success=True,
        detail="assistant response generated",
        mode="code",
        response_emitted=True,
    )
    assert replanned["next_step"]
    assert "login flow" in replanned["next_step"]


def test_local_evidence_exhausted_response_blocks_llm_guessing():
    state = {
        "active_project_id": "demo-project",
        "current_task": "find auth implementation",
        "next_tool": "project_excerpt",
    }
    payload = chat_api._maybe_local_evidence_exhausted_response(
        "Where is auth handled in this backend?",
        "en",
        state,
        plan={"llm_required": False},
        source_plan="local_only",
        has_active_project=True,
    )
    assert payload is not None
    assert payload["tool_kind"] == "local_evidence_exhausted"
    assert "enough local evidence" in payload["response"].lower()


def test_web_evidence_exhausted_response_blocks_web_only_guessing():
    state = {
        "next_tool": "web_search",
        "last_web_query": "best jwt library angular python",
    }
    payload = chat_api._maybe_web_evidence_exhausted_response(
        "best JWT library?",
        "en",
        state,
        source_plan="web_only",
        web_meta={"status": "unavailable", "source": "none", "attempted": True},
        raw_sources=[],
        has_active_project=False,
        web_query="best jwt library angular python",
    )
    assert payload is not None
    assert payload["tool_kind"] == "web_evidence_exhausted"
    assert "web evidence" in payload["response"].lower()


def test_web_evidence_exhausted_response_prefers_local_project_when_available():
    state = {
        "active_project_id": "demo-project",
        "next_tool": "project_manifest",
    }
    payload = chat_api._maybe_web_evidence_exhausted_response(
        "latest jwt docs",
        "en",
        state,
        source_plan="local+web",
        web_meta={"status": "error", "source": "none", "attempted": True},
        raw_sources=[],
        has_active_project=True,
        web_query="latest jwt docs",
    )
    assert payload is not None
    assert payload["tool_kind"] == "web_evidence_exhausted"
    assert "local project" in payload["response"].lower()


def test_web_evidence_exhausted_response_allows_local_programming_fallback():
    state = {
        "next_tool": "web_search",
        "last_web_query": "python sort function list",
    }
    payload = chat_api._maybe_web_evidence_exhausted_response(
        "Ok can u search how is builded a sort function whit python this for handle a list?",
        "en",
        state,
        source_plan="web_only",
        web_meta={"status": "unavailable", "source": "none", "attempted": True},
        raw_sources=[],
        has_active_project=False,
        web_query="python sort function list",
    )
    assert payload is None


def test_followup_state_keeps_artifact_and_focus():
    state = update_session_state(
        None,
        "Build a login endpoint with FastAPI",
        "```python\n@app.post('/login')\ndef login(): ...\n```",
        mode="code",
        active_project_id="demo-project",
    )
    followup = update_session_state(
        state,
        "show me the code inside that file",
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    assert followup["current_task"]
    assert followup["last_artifact"]
    assert followup["current_subtask"]


def test_project_clarifier_followup_keeps_local_project_manifest_context():
    state = update_session_state(
        {
            "active_project_id": "demo-project",
            "current_task": "explain the active project",
            "current_topic": "project overview",
            "next_tool": "project_manifest",
        },
        "can u be more specific maybe?",
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    assert state["next_tool"] == "project_manifest"
    assert state["active_project_id"] == "demo-project"
    assert state["next_step"]


def test_turn_plan_prefers_project_files_for_folder_focus_followup():
    plan = chat_api._build_turn_plan(
        message="can u be more specific maybe?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_task": "explore api folder",
            "current_file_focus": "api",
            "current_artifact_focus": "api",
            "next_tool": "project_files",
        },
    )
    assert plan["next_tool"] == "project_files"
    assert "project_files" in plan["tool_candidates"]


def test_turn_plan_prefers_project_files_for_named_directory_followup(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_load_active_project_manifest",
        lambda _state: {"file_tree": ["api/routes.py", "services/auth_service.py"]},
    )
    plan = chat_api._build_turn_plan(
        message="and services?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_task": "explain the active project",
            "next_tool": "project_manifest",
        },
    )
    assert plan["next_tool"] == "project_files"
    assert "project_files" in plan["tool_candidates"]


def test_turn_plan_prefers_excerpt_for_contextual_file_followup(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_load_active_project_manifest",
        lambda _state: {"file_tree": ["api/routes.py", "services/auth_service.py"]},
    )
    plan = chat_api._build_turn_plan(
        message="and routes?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_task": "explore api folder",
            "current_file_focus": "api",
            "current_artifact_focus": "api",
            "next_tool": "project_files",
        },
    )
    assert plan["next_tool"] == "project_excerpt"
    assert "project_excerpt" in plan["tool_candidates"]


def test_turn_plan_prefers_parent_folder_tree_for_file_expansion_followup():
    plan = chat_api._build_turn_plan(
        message="what else is there?",
        mode_value="chat",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={
            "active_project_id": "demo-project",
            "current_task": "inspect auth implementation",
            "current_file_focus": "app/service.py",
            "current_artifact_focus": "app/service.py",
            "next_tool": "project_excerpt",
        },
    )
    assert plan["next_tool"] == "project_files"
    assert "project_files" in plan["tool_candidates"]
    assert "project_excerpt" not in plan["tool_candidates"]


def test_followup_state_ignores_attachment_noise_for_project_focus():
    raw = (
        "what u can tell me about active project ?\n\n"
        "[Attachment context image: trust1.png]\n"
        "Local visual analysis (no external services):\n"
        "For programming questions: produce COMPLETE runnable code."
    )
    state = update_session_state(
        None,
        "Build a login endpoint with FastAPI",
        "```python\n@app.post('/login')\ndef login(): ...\n```",
        mode="code",
        active_project_id="demo-project",
    )
    followup = update_session_state(
        state,
        raw,
        "",
        mode="chat",
        active_project_id="demo-project",
    )
    assert "active_project" not in (followup.get("missing_evidence") or [])
    assert followup["next_tool"] in {"project_manifest", "project_excerpt", "project_symbols"}
    assert followup["next_step"]
    assert "attachment context" not in (followup.get("last_user_request") or "").lower()



def test_session_state_records_semantic_contract_fields():
    state = update_session_state(
        None,
        "What is a login flow?",
        "",
        mode="chat",
        active_project_id=None,
    )
    assert state["conversation_act"] == "definition"
    assert state["source_policy"] == "local"
    assert state["web_required"] is False
    assert state["allow_run"] is False
    assert state["override_memory"] is False
    assert state["conversation_subject"]


def test_session_state_tracks_last_mode_across_mode_switches():
    state = update_session_state(
        None,
        "Build a login flow with Angular frontend and Python backend",
        "",
        mode="code",
        active_project_id="demo-project",
    )
    followup = update_session_state(
        state,
        "also show the current project docs",
        "",
        mode="web",
        active_project_id="demo-project",
    )
    assert followup["last_mode"] == "web"
    assert followup["active_project_id"] == "demo-project"
    assert followup["goal"] == state["goal"]


def test_session_state_can_learn_file_focus_from_assistant_response():
    state = update_session_state(
        None,
        "Where is auth handled?",
        "File app/auth.py:\ndef login():\n    return 'ok'\n",
        mode="chat",
        active_project_id="demo-project",
    )
    assert state["current_file_focus"] == "app/auth.py"
    assert state["current_artifact_focus"] == "app/auth.py"
