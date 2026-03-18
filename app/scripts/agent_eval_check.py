#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

# Keep evals deterministic and quiet in environments without DB wiring.
os.environ.setdefault("AEGIS_DISABLE_DB", "1")
os.environ.setdefault("AEGIS_ENABLE_DATA_API", "0")

from app.api import chat as chat_api
from app.services.session_state import replan_session_state


def run_agent_eval_cases() -> Dict[str, Any]:
    cases: List[Dict[str, Any]] = []

    missing_state = {
        "missing_evidence": ["active_project"],
        "current_task": "inspect backend architecture",
    }
    missing_resp = chat_api._maybe_missing_evidence_response(
        "where is auth handled in this backend?",
        "en",
        missing_state,
        source_plan="local_only",
    )
    cases.append(
        {
            "name": "missing_project_evidence",
            "ok": bool(missing_resp and missing_resp.get("tool_kind") == "missing_evidence"),
            "detail": missing_resp.get("tool_kind") if missing_resp else "no-response",
        }
    )

    source_plan = chat_api._decide_source_plan(
        "show me the code",
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
    cases.append(
        {
            "name": "local_focus_prefers_local_only",
            "ok": source_plan == "local_only",
            "detail": source_plan,
        }
    )

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
    cases.append(
        {
            "name": "symbol_focus_prefers_symbol_tool",
            "ok": plan.get("next_tool") == "project_symbols" and plan.get("llm_required") is False,
            "detail": {"next_tool": plan.get("next_tool"), "llm_required": plan.get("llm_required")},
        }
    )
    cases.append(
        {
            "name": "plan_includes_risk_metadata",
            "ok": isinstance(plan.get("tool_risks"), dict) and isinstance(plan.get("approval_required"), list),
            "detail": {"tool_risks": bool(plan.get("tool_risks")), "approval_required": plan.get("approval_required")},
        }
    )
    cases.append(
        {
            "name": "plan_includes_suggested_actions",
            "ok": isinstance(plan.get("actions"), list) and bool(plan.get("actions")),
            "detail": {"actions": plan.get("actions")[:2] if isinstance(plan.get("actions"), list) else None},
        }
    )

    replanned = replan_session_state(
        {
            "active_project_id": "demo-project",
            "current_task": "review auth flow",
            "next_tool": "web_search",
            "missing_evidence": ["fresh_web_context"],
            "last_user_request": "latest JWT docs",
        },
        tool_name="web_search",
        success=False,
        detail="unavailable",
        mode="web",
    )
    cases.append(
        {
            "name": "failed_web_replans_to_project",
            "ok": replanned.get("next_tool") == "project_manifest",
            "detail": replanned.get("next_tool"),
        }
    )

    context = chat_api._build_response_context(
        source_plan="local_only",
        active_project_id="demo-project",
        lang="en",
        session_state={
            "current_task": "build login flow",
            "current_subtask": "inspect auth implementation",
            "next_step": "open app/auth.py",
            "next_tool": "project_excerpt",
            "current_artifact_focus": "login flow",
        },
        used_local=True,
        plan={
            "tool_candidates": ["project_excerpt", "project_symbols"],
            "llm_required": False,
            "actions": [{"tool": "project_excerpt", "label_en": "Open excerpt", "label_es": "Abrir extracto", "args": {"path": "app/auth.py"}}],
        },
    )
    cases.append(
        {
            "name": "response_context_exposes_planner_fields",
            "ok": context.get("next_tool") == "project_excerpt" and context.get("llm_required") is False,
            "detail": {"next_tool": context.get("next_tool"), "llm_required": context.get("llm_required")},
        }
    )
    cases.append(
        {
            "name": "response_context_carries_actions",
            "ok": isinstance(context.get("actions"), list) and bool(context.get("actions")),
            "detail": {"actions_count": len(context.get("actions") or [])},
        }
    )

    fallback_source_plan = chat_api._decide_source_plan(
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
    cases.append(
        {
            "name": "failed_web_prefers_local_plus_web",
            "ok": fallback_source_plan in {"local+web", "web_only"},
            "detail": fallback_source_plan,
        }
    )

    followup_replanned = replan_session_state(
        {
            "active_project_id": "demo-project",
            "current_task": "review auth flow",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
            "next_tool": "project_manifest",
        },
        tool_name="project_manifest",
        success=True,
        detail="app/auth.py",
        mode="chat",
        response_emitted=True,
    )
    cases.append(
        {
            "name": "direct_project_response_sets_followup_excerpt",
            "ok": followup_replanned.get("next_tool") == "project_excerpt",
            "detail": followup_replanned.get("next_tool"),
        }
    )

    delete_plan = chat_api._build_turn_plan(
        message="delete this project",
        mode_value="agent",
        source_plan="local_only",
        has_active_project=True,
        force_web=False,
        session_state={"active_project_id": "demo-project"},
    )
    cases.append(
        {
            "name": "delete_project_requires_approval",
            "ok": "delete_project" in (delete_plan.get("approval_required") or []),
            "detail": delete_plan.get("approval_required"),
        }
    )

    forced_web_plan = chat_api._decide_source_plan(
        "check latest angular docs",
        mode_value="chat",
        force_web=True,
        is_crypto_mode=False,
        has_active_project=True,
        session_state={"active_project_id": "demo-project"},
    )
    cases.append(
        {
            "name": "force_web_enables_web_usage",
            "ok": forced_web_plan in {"web_only", "local+web"},
            "detail": forced_web_plan,
        }
    )

    web_success_followup = replan_session_state(
        {
            "active_project_id": "demo-project",
            "current_task": "review login flow",
            "current_subtask": "inspect auth implementation",
            "current_file_focus": "app/auth.py",
            "current_artifact_focus": "app/auth.py",
            "next_tool": "web_search",
            "missing_evidence": ["fresh_web_context"],
        },
        tool_name="web_search",
        success=True,
        detail="live",
        mode="web",
        response_emitted=True,
    )
    cases.append(
        {
            "name": "web_success_followup_prefers_local_tool",
            "ok": web_success_followup.get("next_tool") in {"project_excerpt", "project_symbols", "project_manifest"},
            "detail": web_success_followup.get("next_tool"),
        }
    )

    project_failure_needs_focus = replan_session_state(
        {
            "active_project_id": "demo-project",
            "current_task": "trace login bug",
            "next_tool": "project_excerpt",
            "missing_evidence": [],
        },
        tool_name="project_excerpt",
        success=False,
        detail="file not found",
        mode="chat",
    )
    cases.append(
        {
            "name": "project_failure_requests_file_or_symbol_focus",
            "ok": "file_or_symbol_focus" in (project_failure_needs_focus.get("missing_evidence") or []),
            "detail": project_failure_needs_focus.get("missing_evidence"),
        }
    )

    delete_success = replan_session_state(
        {
            "active_project_id": "demo-project",
            "current_task": "cleanup workspace",
            "current_file_focus": "app/auth.py",
            "current_symbol_focus": "auth_token",
            "next_tool": "delete_project",
            "missing_evidence": [],
        },
        tool_name="delete_project",
        success=True,
        detail="deleted",
        mode="tool",
    )
    cases.append(
        {
            "name": "delete_project_success_clears_project_binding",
            "ok": not delete_success.get("active_project_id") and "active_project" in (delete_success.get("missing_evidence") or []),
            "detail": {
                "active_project_id": delete_success.get("active_project_id"),
                "missing_evidence": delete_success.get("missing_evidence"),
            },
        }
    )

    llm_failure_replans = replan_session_state(
        {
            "active_project_id": "demo-project",
            "current_task": "summarize architecture",
            "next_tool": "llm_synthesis",
            "missing_evidence": [],
        },
        tool_name="llm_synthesis",
        success=False,
        detail="timeout",
        mode="chat",
    )
    cases.append(
        {
            "name": "llm_failure_keeps_followup_step",
            "ok": bool(str(llm_failure_replans.get("next_step") or "").strip()),
            "detail": {
                "next_tool": llm_failure_replans.get("next_tool"),
                "next_step": llm_failure_replans.get("next_step"),
            },
        }
    )

    passed = sum(1 for case in cases if case["ok"])
    return {
        "ok": passed == len(cases),
        "passed": passed,
        "total": len(cases),
        "cases": cases,
    }


def main() -> int:
    result = run_agent_eval_cases()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
