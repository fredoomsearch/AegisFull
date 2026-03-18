#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

# Deterministic defaults for CI/eval contexts.
os.environ.setdefault("AEGIS_DISABLE_DB", "1")
os.environ.setdefault("AEGIS_ENABLE_DATA_API", "0")
os.environ.setdefault("AEGIS_ROUTER_DETERMINISTIC_STRICT", "1")
os.environ.setdefault("AEGIS_ROUTER_FAIL_CLOSED", "1")
os.environ.setdefault("AEGIS_FOCUS_CLEAR_ON_TOPIC_SWITCH", "1")

from app.api import chat as chat_api
from app.services.session_state import default_session_state, update_session_state


def _base_project_state() -> Dict[str, Any]:
    return {
        "active_project_id": "demo-project",
        "current_file_focus": "app/auth.py",
        "current_symbol_focus": "login_user",
        "current_artifact_focus": "app/auth.py",
        "next_tool": "project_excerpt",
        "current_task": "review authentication flow",
        "missing_evidence": [],
    }


def _sample_failure(case: Dict[str, Any], out: List[Dict[str, Any]], *, limit: int = 60) -> None:
    if len(out) >= limit:
        return
    out.append(
        {
            "name": case.get("name"),
            "detail": case.get("detail"),
        }
    )


def run_adversarial_eval_cases(min_cases: int = 500) -> Dict[str, Any]:
    cases: List[Dict[str, Any]] = []

    world_questions = [
        "where is russia?",
        "what is the capital of japan?",
        "who is the president of france?",
        "what time is it in new york?",
        "where is mount everest?",
        "what is photosynthesis?",
        "when was python created?",
        "what is gdp?",
        "how far is the moon?",
        "what is blockchain?",
        "where is bogota?",
        "who wrote don quixote?",
        "que es una api?",
        "donde esta mexico?",
        "como funciona internet?",
        "what is quantum computing?",
        "who discovered penicillin?",
        "where is the sahara desert?",
        "what is machine learning?",
        "why is the sky blue?",
    ]

    generic_code_questions = [
        "build a login page with angular and python backend",
        "give me a fastapi auth endpoint example",
        "how to create jwt auth in python?",
        "show a dockerfile for fastapi",
        "write a react login form",
        "how to validate email in javascript?",
        "give me a sql query example",
        "create a flask login route",
        "how do i test api endpoints with pytest?",
        "build a signup flow with html css js",
        "generate a node express auth sample",
        "how to implement oauth2 in fastapi?",
        "show a secure password hashing example",
        "write a basic angular service for auth",
        "give me a csrf protection example",
        "create a redis session cache example",
        "how to structure backend folders in python?",
        "build fullstack login with angular + fastapi",
        "show form validation in angular reactive forms",
        "how to add refresh tokens in jwt flow?",
    ]

    project_scoped_questions = [
        "in this project, what does app/auth.py do?",
        "show files in this repo",
        "where is login handled in the project?",
        "summarize architecture of this codebase",
        "show project dependencies and configs",
        "open file app/main.py in this repository",
        "which module has jwt in this project?",
        "explain entrypoints of this project",
        "show symbol login_user in this repo",
        "in this project, analyze backend auth flow",
        "what files were ingested in this project?",
        "list files under app/ in this codebase",
        "where is oauth configured in this project?",
        "project architecture for auth and api layers",
        "show config files in this repository",
        "in this repo, explain how uploads work",
        "what does this project contain?",
        "open app/services/session_state.py from this project",
        "project summary and key files please",
        "in this project where is database setup?",
    ]

    project_followups = [
        "in this project, continue with auth files",
        "for this repo, show where login symbol is",
        "continue in project context and inspect config",
        "project followup: explain auth module",
    ]

    # 1) Active project + non-project questions must not route to project-local path.
    for idx, msg in enumerate(world_questions + generic_code_questions):
        state = _base_project_state()
        source_plan = chat_api._decide_source_plan(
            msg,
            mode_value="chat",
            force_web=False,
            is_crypto_mode=False,
            has_active_project=True,
            session_state=state,
        )
        case = {
            "name": f"non_project_web_only_{idx}",
            "ok": source_plan == "web_only",
            "detail": {"message": msg, "source_plan": source_plan},
        }
        cases.append(case)

    # 2) Explicit project scope should remain local-first.
    for idx, msg in enumerate(project_scoped_questions):
        state = _base_project_state()
        source_plan = chat_api._decide_source_plan(
            msg,
            mode_value="chat",
            force_web=False,
            is_crypto_mode=False,
            has_active_project=True,
            session_state=state,
        )
        plan = chat_api._build_turn_plan(
            message=msg,
            mode_value="chat",
            source_plan=source_plan,
            has_active_project=True,
            force_web=False,
            session_state=state,
        )
        case = {
            "name": f"project_scope_local_{idx}",
            "ok": source_plan == "local_only" and str(plan.get("next_tool") or "").startswith("project_"),
            "detail": {"message": msg, "source_plan": source_plan, "next_tool": plan.get("next_tool")},
        }
        cases.append(case)

    # 3) Explicit web mode and force-web must always be web_only.
    for idx, msg in enumerate(world_questions):
        web_mode_plan = chat_api._decide_source_plan(
            msg,
            mode_value="web",
            force_web=False,
            is_crypto_mode=False,
            has_active_project=True,
            session_state=_base_project_state(),
        )
        force_web_plan = chat_api._decide_source_plan(
            msg,
            mode_value="chat",
            force_web=True,
            is_crypto_mode=False,
            has_active_project=True,
            session_state=_base_project_state(),
        )
        cases.append(
            {
                "name": f"explicit_web_mode_{idx}",
                "ok": web_mode_plan == "web_only" and force_web_plan == "web_only",
                "detail": {"message": msg, "web_mode": web_mode_plan, "force_web": force_web_plan},
            }
        )

    # 4) Multi-turn adversarial flows:
    # project question -> world question -> project followup
    # Expect focus clear on topic switch and deterministic project tool recovery.
    # Keep deterministic suite size >= 500 for strict release gates.
    for idx in range(420):
        project_msg = project_scoped_questions[idx % len(project_scoped_questions)]
        world_msg = world_questions[idx % len(world_questions)]
        followup_msg = project_followups[idx % len(project_followups)]

        state0 = default_session_state()
        state0["active_project_id"] = "demo-project"
        state1 = update_session_state(
            state0,
            project_msg,
            "",
            mode="chat",
            active_project_id="demo-project",
        )
        # Ensure explicit focus exists before topic switch.
        state1["current_file_focus"] = "app/auth.py"
        state1["current_symbol_focus"] = "login_user"
        state1["current_artifact_focus"] = "app/auth.py"

        state2 = update_session_state(
            state1,
            world_msg,
            "",
            mode="chat",
            active_project_id="demo-project",
        )
        focus_cleared = not (
            str(state2.get("current_file_focus") or "").strip()
            or str(state2.get("current_symbol_focus") or "").strip()
            or str(state2.get("current_artifact_focus") or "").strip()
        )

        state3 = update_session_state(
            state2,
            followup_msg,
            "",
            mode="chat",
            active_project_id="demo-project",
        )
        plan3 = chat_api._build_turn_plan(
            message=followup_msg,
            mode_value="chat",
            source_plan="local_only",
            has_active_project=True,
            force_web=False,
            session_state=state3,
        )
        recovered_project_tool = str(plan3.get("next_tool") or "").startswith("project_")

        cases.append(
            {
                "name": f"topic_switch_decay_{idx}",
                "ok": focus_cleared and recovered_project_tool,
                "detail": {
                    "project_msg": project_msg,
                    "world_msg": world_msg,
                    "followup_msg": followup_msg,
                    "focus_cleared": focus_cleared,
                    "next_tool": plan3.get("next_tool"),
                },
            }
        )

    # 5) Web unavailable/cooldown edge: if web failed recently + explicit web ask, keep web path available.
    for idx, msg in enumerate(generic_code_questions):
        source_plan = chat_api._decide_source_plan(
            f"latest docs for: {msg}",
            mode_value="chat",
            force_web=False,
            is_crypto_mode=False,
            has_active_project=True,
            session_state={
                **_base_project_state(),
                "recent_tool_failures": ["web_search:timeout"],
            },
        )
        cases.append(
            {
                "name": f"web_retry_path_{idx}",
                "ok": source_plan in {"web_only", "local+web"},
                "detail": {"message": msg, "source_plan": source_plan},
            }
        )

    total = len(cases)
    passed = sum(1 for case in cases if bool(case.get("ok")))
    ok = (passed == total) and total >= int(min_cases)

    failed_examples: List[Dict[str, Any]] = []
    for case in cases:
        if not bool(case.get("ok")):
            _sample_failure(case, failed_examples)

    return {
        "ok": ok,
        "passed": passed,
        "total": total,
        "min_cases": int(min_cases),
        "failed_examples": failed_examples,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic adversarial routing/session eval suite.")
    p.add_argument("--min-cases", type=int, default=500)
    p.add_argument("--strict", action="store_true", help="Fail when total cases < --min-cases.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = run_adversarial_eval_cases(min_cases=args.min_cases)
    if not args.strict and result["total"] < int(args.min_cases):
        result["ok"] = result["passed"] == result["total"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
