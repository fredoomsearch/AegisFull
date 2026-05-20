from __future__ import annotations

"""
Structured conversation/session state utilities.

Why this module exists:
- Keep planner hints and conversational focus deterministic between turns.
- Normalize and trim state so agent routing remains stable.
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict
from app.services.input_normalizer import strip_attachment_context
from app.utils.runtime_helpers import compact as _compact

MAX_LIST_ITEMS = max(1, int(os.getenv("AEGIS_SESSION_MAX_ITEMS", "8")))
MAX_TEXT_CHARS = max(24, int(os.getenv("AEGIS_SESSION_MAX_TEXT_CHARS", "180")))
FOCUS_TURN_BUDGET = max(1, int(os.getenv("AEGIS_FOCUS_TURN_BUDGET", "3")))
FOCUS_TTL_MS = max(60_000, int(os.getenv("AEGIS_FOCUS_TTL_MS", "900000")))
FOCUS_CLEAR_ON_TOPIC_SWITCH = (os.getenv("AEGIS_FOCUS_CLEAR_ON_TOPIC_SWITCH", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}

_PROJECT_SCOPE_STRICT_HINTS: tuple[str, ...] = (
    "project",
    "proyecto",
    "repo",
    "repository",
    "codebase",
    "file",
    "files",
    "archivo",
    "archivos",
    "path",
    "ruta",
    "folder",
    "carpeta",
    "entrypoint",
    "dependencies",
    "dependencias",
    "config",
    "configs",
    "symbol",
    "function",
    "class",
    "module",
    "ingest",
    "uploaded zip",
)


class SessionState(TypedDict, total=False):
    """Canonical per-conversation planner/context state."""
    goal: str
    current_topic: str
    current_task: str
    current_subtask: str
    next_step: str
    next_tool: Optional[str]
    backend: Optional[str]
    frontend: Optional[str]
    active_project_id: Optional[str]
    current_file_focus: Optional[str]
    current_symbol_focus: Optional[str]
    entities: List[str]
    constraints: List[str]
    open_questions: List[str]
    previous_decisions: List[str]
    missing_evidence: List[str]
    last_artifact: Optional[str]
    last_artifact_kind: Optional[str]
    last_artifact_lang: Optional[str]
    last_artifact_snippet: Optional[str]
    current_artifact_focus: Optional[str]
    recent_tool_failures: List[str]
    last_web_query: str
    last_web_sources: List[str]
    last_web_findings: List[str]
    last_user_request: str
    last_mode: str
    conversation_act: str
    conversation_subject: str
    source_policy: str
    web_required: bool
    allow_run: bool
    override_memory: bool
    focus_turn_budget: int
    focus_last_touch_ms: int
    answer_style: Dict[str, bool]
    pending_approval: Optional[Dict[str, Any]]


_BACKEND_PATTERNS: Dict[str, tuple[str, ...]] = {
    "fastapi": ("fastapi",),
    "flask": ("flask",),
    "django": ("django",),
    "python": ("python backend", "python api", "backend in python", "python"),
    "node": ("node", "nodejs", "express"),
    "spring": ("spring", "spring boot", "springboot", "java backend"),
}

_FRONTEND_PATTERNS: Dict[str, tuple[str, ...]] = {
    "angular": ("angular",),
    "react": ("react",),
    "vue": ("vue",),
    "html": ("html", "vanilla js", "plain js", "javascript"),
}

_ENTITY_PATTERNS: tuple[str, ...] = (
    "jwt",
    "oauth",
    "auth",
    "login",
    "signup",
    "form",
    "api",
    "endpoint",
    "crud",
    "upload",
    "web search",
    "embedding",
    "faiss",
    "crypto",
    "prediction",
    "chart",
    "news",
)

_CONSTRAINT_PATTERNS: Dict[str, tuple[str, ...]] = {
    "concise": ("concise", "short", "brief", "resume", "resumen", "corto", "breve"),
    "code_first": ("code first", "codigo primero", "código primero", "just code", "solo codigo", "solo código"),
    "no_opinions": (
        "without opinions",
        "sin opiniones",
        "no opinions",
        "without unnecessary aspects",
        "sin aspectos innecesarios",
    ),
    "step_by_step": ("step by step", "paso a paso"),
}

_QUESTION_PREFIXES = (
    "how",
    "what",
    "why",
    "which",
    "can",
    "could",
    "would",
    "should",
    "is",
    "are",
    "como",
    "cómo",
    "que",
    "qué",
    "por que",
    "por qué",
    "cual",
    "cuál",
    "puedes",
    "podrias",
    "podrías",
)

_FOLLOWUP_PREFIXES = (
    "and ",
    "also ",
    "now ",
    "then ",
    "what about",
    "how about",
    "continue",
    "go ahead",
    "for angular",
    "for python",
    "and for",
    "also for",
    "now for",
    "y ",
    "tambien ",
    "también ",
    "entonces ",
    "sigue",
    "continua",
    "continúa",
    "y para",
)

_PROJECT_CLARIFICATION_HINTS: tuple[str, ...] = (
    "be more specific",
    "more specific",
    "more detail",
    "more details",
    "can you explain better",
    "can u explain better",
    "explain better",
    "elaborate",
    "expand that",
    "expand on that",
    "tell me more",
    "go deeper",
    "puedes ser mas especific",
    "puedes ser más especific",
    "podrias ser mas especific",
    "podrías ser más especific",
    "mas especific",
    "más especific",
    "mas detalle",
    "más detalle",
    "explica mejor",
    "dime mas",
    "dime más",
    "que mas",
    "qué más",
    "que mas hay",
    "qué más hay",
    "que mas tiene",
    "qué más tiene",
    "what else is there",
    "what else is inside",
    "what else is in there",
    "what else do we have",
    "show me the rest",
    "show the rest",
    "mas profundo",
    "más profundo",
)

_ARTIFACT_TASKS: Dict[str, tuple[str, ...]] = {
    "login_flow": ("login", "signup", "auth", "jwt", "oauth"),
    "api_endpoint": ("endpoint", "api", "route", "controller"),
    "ui_component": ("component", "button", "form", "page", "screen", "angular", "react", "html"),
    "file_ingest": ("upload", "zip", "ingest", "repo", "repository", "files"),
    "crypto_flow": ("crypto", "prediction", "ohlcv", "chart", "signal"),
}

_SYMBOL_FOCUS_STOPWORDS = {
    "that",
    "this",
    "it",
    "those",
    "these",
    "same",
    "here",
    "there",
    "where",
    "donde",
    "dónde",
    "esto",
    "eso",
    "esta",
    "ese",
    "mismo",
}


def default_session_state() -> SessionState:
    """Create baseline state with safe defaults for all planner fields."""
    return {
        "goal": "",
        "current_topic": "",
        "current_task": "",
        "current_subtask": "",
        "next_step": "",
        "next_tool": None,
        "backend": None,
        "frontend": None,
        "active_project_id": None,
        "current_file_focus": None,
        "current_symbol_focus": None,
        "entities": [],
        "constraints": [],
        "open_questions": [],
        "previous_decisions": [],
        "missing_evidence": [],
        "last_artifact": None,
        "last_artifact_kind": None,
        "last_artifact_lang": None,
        "last_artifact_snippet": None,
        "current_artifact_focus": None,
        "recent_tool_failures": [],
        "last_web_query": "",
        "last_web_sources": [],
        "last_web_findings": [],
        "last_user_request": "",
        "last_mode": "",
        "conversation_act": "other",
        "conversation_subject": "",
        "source_policy": "local",
        "web_required": False,
        "allow_run": False,
        "override_memory": False,
        "focus_turn_budget": FOCUS_TURN_BUDGET,
        "focus_last_touch_ms": 0,
        "pending_approval": None,
        "answer_style": {
            "concise": True,
            "code_first": False,
            "delta_only": False,
            "no_redundancy": True,
            "no_unsolicited_opinions": True,
        },
    }


def normalize_session_state(raw: Optional[Dict[str, Any]]) -> SessionState:
    """Sanitize persisted/raw state into canonical SessionState shape."""
    base = default_session_state()
    if not isinstance(raw, dict):
        return base
    for key in (
        "goal",
        "current_topic",
        "current_task",
        "current_subtask",
        "next_step",
        "next_tool",
        "backend",
        "frontend",
        "active_project_id",
        "current_file_focus",
        "current_symbol_focus",
        "last_artifact",
        "last_artifact_kind",
        "last_artifact_lang",
        "last_artifact_snippet",
        "current_artifact_focus",
        "last_web_query",
        "last_user_request",
        "last_mode",
        "conversation_act",
        "conversation_subject",
        "source_policy",
    ):
        value = raw.get(key)
        if isinstance(value, str):
            base[key] = _trim_text(value)
        elif value is None and key in {
            "backend",
            "frontend",
            "active_project_id",
            "current_file_focus",
            "current_symbol_focus",
            "last_artifact",
            "last_artifact_kind",
            "last_artifact_lang",
            "last_artifact_snippet",
            "current_artifact_focus",
            "conversation_act",
            "conversation_subject",
            "source_policy",
        }:
            base[key] = None
    for key in ("entities", "constraints", "open_questions", "previous_decisions", "missing_evidence", "last_web_sources", "last_web_findings", "recent_tool_failures"):
        value = raw.get(key)
        if isinstance(value, list):
            base[key] = _unique_trimmed_strings(value)
    focus_budget = raw.get("focus_turn_budget")
    if isinstance(focus_budget, (int, float)):
        base["focus_turn_budget"] = max(0, int(focus_budget))
    focus_touch = raw.get("focus_last_touch_ms")
    if isinstance(focus_touch, (int, float)):
        base["focus_last_touch_ms"] = max(0, int(focus_touch))
    pending = raw.get("pending_approval")
    if isinstance(pending, dict):
        # Keep it tiny (token/tool/expiry). Avoid storing large payloads here.
        kept: Dict[str, Any] = {}
        for k in ("token", "tool", "created_ms", "expires_ms", "summary"):
            v = pending.get(k)
            if isinstance(v, str):
                kept[k] = _trim_text(v)
            elif isinstance(v, (int, float)) and k in {"created_ms", "expires_ms"}:
                kept[k] = int(v)
        base["pending_approval"] = kept
    elif pending is None:
        base["pending_approval"] = None
    style = raw.get("answer_style")
    if isinstance(style, dict):
        merged = dict(base["answer_style"])
        for key, value in style.items():
            if isinstance(value, bool):
                merged[key] = value
        base["answer_style"] = merged
    return base


def update_session_state(
    raw_state: Optional[Dict[str, Any]],
    user_message: str,
    assistant_message: str = "",
    *,
    web_query: str = "",
    sources: Optional[List[Dict[str, Any]]] = None,
    mode: str = "",
    active_project_id: Optional[str] = None,
) -> SessionState:
    """
    What it does:
    - Applies user/assistant turn signals to canonical planner session state.

    Why it exists:
    - Keep routing continuity deterministic (focus, constraints, next tool/step).

    Called from ->
    - chat and agent endpoints after each turn update

    Calls ->
    - normalization, focus-decay, intent extraction, planner derivation helpers

    Failure/guard behavior:
    - Falls back to normalized defaults when raw state is malformed/incomplete.
    """
    state = normalize_session_state(raw_state)
    user_clean = _trim_text(strip_attachment_context(user_message))
    assistant_clean = _trim_text(assistant_message)
    lower = user_clean.lower()
    project_clarification_followup = bool(active_project_id or state.get("active_project_id")) and _looks_like_project_clarification_followup(user_clean)
    followup = looks_like_followup(user_clean) or project_clarification_followup
    semantic = classify_conversational_act(user_clean, session_state=state, mode=mode)
    user_file_focus = _extract_file_focus(user_clean)
    user_symbol_focus = _extract_symbol_focus(user_clean)
    planner_next_tool = _trim_text(str(state.get("next_tool") or ""))
    referential_followup = _is_referential_followup_text(user_clean, followup=followup) or (
        project_clarification_followup
        and bool(
            planner_next_tool.startswith("project_")
            or planner_next_tool == "file_search"
            or state.get("current_task")
            or state.get("current_subtask")
            or state.get("current_topic")
            or state.get("current_artifact_focus")
            or state.get("current_file_focus")
            or state.get("current_symbol_focus")
        )
    )
    _apply_focus_decay(
        state,
        now_ms=int(time.time() * 1000),
        explicit_focus=bool(user_file_focus or user_symbol_focus),
        referential_followup=referential_followup,
    )
    if _should_clear_focus_on_topic_switch(
        state,
        user_message=user_clean,
        followup=followup,
        explicit_focus=bool(user_file_focus or user_symbol_focus),
        referential_followup=referential_followup,
    ):
        _clear_focus(state)

    if active_project_id:
        state["active_project_id"] = _trim_text(active_project_id)

    previous_topic = _trim_text(str(state.get("current_topic") or ""))
    topic_candidate = _extract_topic(user_clean)
    if semantic.get("act") in {"greeting", "help", "acknowledgement"}:
        topic_candidate = ""
    if topic_candidate and previous_topic and topic_candidate.lower() != previous_topic.lower() and not referential_followup:
        _clear_stale_web_context(state)
    if topic_candidate:
        state["current_topic"] = topic_candidate
        if not state.get("goal") or not followup:
            state["goal"] = topic_candidate
        if not followup:
            state["current_task"] = topic_candidate
        elif topic_candidate:
            state["current_subtask"] = topic_candidate

    backend = _detect_stack(lower, _BACKEND_PATTERNS)
    if backend:
        state["backend"] = backend
        _add_unique(state["previous_decisions"], f"backend={backend}")

    frontend = _detect_stack(lower, _FRONTEND_PATTERNS)
    if frontend:
        state["frontend"] = frontend
        _add_unique(state["previous_decisions"], f"frontend={frontend}")

    for entity in _extract_entities(lower):
        _add_unique(state["entities"], entity)

    for constraint in _extract_constraints(lower):
        _add_unique(state["constraints"], constraint)

    question = _extract_question_focus(user_clean)
    if question:
        _add_unique(state["open_questions"], question)
        if followup:
            state["current_subtask"] = question
        elif not state.get("current_task"):
            state["current_task"] = question
    elif followup and _looks_like_action_followup(lower):
        state["current_subtask"] = _trim_text(user_clean)

    file_focus = user_file_focus
    if file_focus:
        state["current_file_focus"] = file_focus
        state["current_artifact_focus"] = file_focus
        _touch_focus(state)

    symbol_focus = user_symbol_focus
    if symbol_focus:
        state["current_symbol_focus"] = symbol_focus
        if not file_focus:
            state["current_artifact_focus"] = symbol_focus
        _touch_focus(state)

    assistant_file_focus = _extract_file_focus(assistant_clean)
    if assistant_file_focus and not file_focus:
        state["current_file_focus"] = assistant_file_focus
        state["current_artifact_focus"] = assistant_file_focus
        _touch_focus(state)

    assistant_symbol_focus = _extract_symbol_focus(assistant_clean)
    if assistant_symbol_focus and not symbol_focus:
        state["current_symbol_focus"] = assistant_symbol_focus
        if not state.get("current_file_focus"):
            state["current_artifact_focus"] = assistant_symbol_focus
        _touch_focus(state)

    artifact_kind = detect_artifact_kind(f"{user_clean}\n{assistant_clean}")
    if assistant_clean and ("```" in assistant_clean or artifact_kind):
        state["last_artifact_kind"] = artifact_kind or "code"
        state["last_artifact"] = _trim_text(state.get("current_topic") or state.get("goal") or question or user_clean)
        lang, snippet = _extract_code_fence_snippet(assistant_message or "")
        if snippet:
            state["last_artifact_lang"] = _trim_text(lang) if lang else None
            state["last_artifact_snippet"] = _trim_snippet(snippet, max_chars=MAX_TEXT_CHARS * 6)
        state["current_artifact_focus"] = _trim_text(
            state.get("current_artifact_focus")
            or assistant_file_focus
            or assistant_symbol_focus
            or state["last_artifact"]
        )
    elif followup and state.get("current_artifact_focus"):
        state["last_artifact"] = _trim_text(
            state.get("last_artifact")
            or state.get("current_artifact_focus")
            or state.get("current_topic")
            or state.get("goal")
            or user_clean
        )
        state["last_artifact_kind"] = state.get("last_artifact_kind") or artifact_kind or detect_artifact_kind(user_clean)

    if web_query:
        state["last_web_query"] = _trim_text(web_query)
    if isinstance(sources, list):
        source_titles = []
        source_findings = []
        for item in sources[:MAX_LIST_ITEMS]:
            title = str((item or {}).get("title") or (item or {}).get("url") or "").strip()
            if title:
                source_titles.append(title)
                source_findings.append(title)
        if source_titles:
            state["last_web_sources"] = _unique_trimmed_strings(source_titles)
            state["last_web_findings"] = _unique_trimmed_strings(source_findings)

    state["conversation_act"] = _trim_text(str(semantic.get("act") or "other"))
    state["conversation_subject"] = _trim_text(str(semantic.get("subject") or ""))
    state["source_policy"] = _trim_text(str(semantic.get("source_policy") or "local"))
    state["web_required"] = bool(semantic.get("web_required"))
    state["allow_run"] = bool(semantic.get("allow_run"))
    state["override_memory"] = bool(semantic.get("override_memory"))
    state["last_user_request"] = user_clean
    state["last_mode"] = _trim_text(mode) if mode else _trim_text(str(state.get("last_mode") or ""))
    state["answer_style"] = _derive_answer_style(state, user_clean, mode=mode, followup=followup)
    plan = _derive_planner_state(state, user_clean, mode=mode)
    state["next_step"] = plan["next_step"]
    state["next_tool"] = plan["next_tool"]
    state["missing_evidence"] = plan["missing_evidence"]
    return state


def replan_session_state(
    raw_state: Optional[Dict[str, Any]],
    *,
    tool_name: str,
    success: bool,
    detail: str = "",
    mode: str = "",
    response_emitted: bool = False,
) -> SessionState:
    """
    What it does:
    - Recomputes follow-up plan hints after tool/web/LLM outcomes.

    Why it exists:
    - Convert runtime success/failure signals into deterministic next actions.

    Called from ->
    - agent orchestration after each tool execution

    Calls ->
    - planner heuristics, missing-evidence management, follow-up tool selection
    """
    state = normalize_session_state(raw_state)
    tool = _trim_text(tool_name)
    detail_clean = _trim_text(detail)

    failures = list(state.get("recent_tool_failures") or [])
    if success:
        failures = [item for item in failures if not item.startswith(f"{tool}:")]
    elif tool:
        _add_unique(failures, f"{tool}:{detail_clean or 'failed'}")
    state["recent_tool_failures"] = _unique_trimmed_strings(failures)

    missing = [str(item).strip() for item in (state.get("missing_evidence") or []) if str(item).strip()]
    next_step = _trim_text(
        state.get("current_subtask")
        or state.get("current_task")
        or state.get("goal")
        or state.get("current_topic")
        or state.get("last_user_request")
        or ""
    )
    next_tool: Optional[str] = str(state.get("next_tool") or "").strip() or None

    if tool == "web_search":
        if success:
            missing = [item for item in missing if item != "fresh_web_context"]
            if response_emitted:
                next_tool = _suggest_followup_tool(state)
                next_step = _suggest_followup_step(state, fallback=next_step)
            elif next_tool == "web_search":
                next_tool = "llm_synthesis"
        else:
            if state.get("active_project_id"):
                next_tool = "project_manifest"
                next_step = _trim_text(next_step or "use local project evidence")
            else:
                _add_unique(missing, "fresh_web_context")
                next_tool = "web_search"
                next_step = _trim_text(next_step or "retry with narrower web query")
    elif tool in {"project_manifest", "project_excerpt", "project_symbols", "file_search", "project_files"}:
        if success:
            missing = [item for item in missing if item not in {"active_project", "file_or_symbol_focus"}]
            if response_emitted:
                state["current_subtask"] = _suggest_followup_step(state, fallback=next_step)
                if not state.get("current_task") and state.get("current_artifact_focus"):
                    state["current_task"] = _trim_text(str(state.get("current_artifact_focus") or ""))
            if response_emitted:
                next_tool = _suggest_followup_tool(state)
                next_step = _suggest_followup_step(state, fallback=next_step)
            elif next_tool in {"project_manifest", "project_excerpt", "project_symbols", "file_search", "project_files"}:
                next_tool = "llm_synthesis"
        else:
            if not state.get("active_project_id"):
                _add_unique(missing, "active_project")
                next_tool = "project_manifest"
                next_step = _trim_text(next_step or "bind an active project")
            elif not (state.get("current_file_focus") or state.get("current_symbol_focus")):
                _add_unique(missing, "file_or_symbol_focus")
                next_tool = "project_excerpt"
                next_step = _trim_text(next_step or "identify the file or symbol")
    elif tool == "llm_synthesis":
        if success:
            missing = []
            if not state.get("current_subtask"):
                state["current_subtask"] = _suggest_followup_step(state, fallback=next_step)
            next_tool = _suggest_followup_tool(state)
            next_step = _suggest_followup_step(state, fallback=next_step)
        else:
            next_tool = _suggest_followup_tool(state) or next_tool
            next_step = _trim_text(next_step or "retry with narrower context")
    elif tool == "delete_project":
        if success:
            # Project is gone (or unregistered). Clear focus to prevent cross-project drift.
            state["active_project_id"] = None
            state["current_file_focus"] = None
            state["current_symbol_focus"] = None
            state["current_artifact_focus"] = None
            missing = [item for item in missing if item != "active_project"]
            _add_unique(missing, "active_project")
            next_tool = "project_manifest"
            next_step = _trim_text(next_step or "select or ingest a project")
        else:
            next_tool = "delete_project"
            next_step = _trim_text(next_step or "retry delete with approval")

    state["missing_evidence"] = _unique_trimmed_strings(missing)
    state["next_step"] = next_step
    state["next_tool"] = _trim_text(next_tool or "") or None
    state["answer_style"] = _derive_answer_style(state, state.get("last_user_request") or "", mode=mode, followup=False)
    return state


def looks_like_followup(text: str) -> bool:
    clean = _compact(text).lower()
    if not clean:
        return False
    if any(clean.startswith(prefix) for prefix in _FOLLOWUP_PREFIXES):
        return True
    if len(clean) <= 48 and re.search(r"\b(this|that|it|those|these|esto|eso|esa|ese)\b", clean):
        return True
    if len(clean) <= 64 and "?" in clean:
        return True
    return False


def _looks_like_project_clarification_followup(text: str) -> bool:
    clean = _compact(text).lower()
    if not clean or len(clean) > 140:
        return False
    return any(token in clean for token in _PROJECT_CLARIFICATION_HINTS)


def _is_referential_followup_text(text: str, *, followup: bool) -> bool:
    if not followup:
        return False
    clean = _compact(text).lower()
    if not clean or len(clean) > 120:
        return False
    if not re.search(r"\b(this|that|it|those|these|same|again|continue|next|previous|above|here|esto|eso|esta|ese|mismo|continuar)\b", clean):
        return False
    # Avoid false positives like "what time is it..." / "donde esta mexico?".
    if re.match(r"^(what|where|who|when|why|how|que|qué|donde|dónde|cuando|cuándo|como|cómo)\b", clean):
        return False
    return True


def _looks_like_project_tree_expansion_followup(text: str) -> bool:
    clean = _compact(text).lower()
    if not clean or len(clean) > 120:
        return False
    return any(
        token in clean
        for token in (
            "what else is there",
            "what else is inside",
            "what else is in there",
            "what else do we have",
            "show me the rest",
            "show the rest",
            "rest of it",
            "que mas hay",
            "qué más hay",
            "que mas tiene",
            "qué más tiene",
            "muestrame lo demas",
            "muéstrame lo demás",
            "muestra lo demas",
            "muestra lo demás",
            "lo demas",
            "lo demás",
        )
    )


def detect_artifact_kind(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for kind, hints in _ARTIFACT_TASKS.items():
        if any(hint in lowered for hint in hints):
            return kind
    return None


def _extract_code_fence_snippet(text: str) -> tuple[str, str]:
    """
    Extract the first fenced code block (```lang ... ```) as a small snippet to maintain continuity.
    Returns (lang, code). If none found, returns ("", "").
    """
    raw = text or ""
    if "```" not in raw:
        return "", ""
    # Non-greedy: first fenced block only.
    m = re.search(r"```([A-Za-z0-9_+-]*)\n(.*?)\n```", raw, flags=re.DOTALL)
    if not m:
        return "", ""
    lang = (m.group(1) or "").strip()
    code = (m.group(2) or "").strip()
    # Bound snippet size to avoid exploding prompts.
    if len(code) > (MAX_TEXT_CHARS * 8):
        code = code[: (MAX_TEXT_CHARS * 8 - 3)] + "..."
    return lang, code


def _derive_answer_style(
    state: SessionState,
    user_message: str,
    *,
    mode: str,
    followup: bool,
) -> Dict[str, bool]:
    style = dict(default_session_state()["answer_style"])
    style.update(state.get("answer_style") or {})
    lowered = (user_message or "").lower()
    is_build = any(hint in lowered for hint in ("build", "make", "create", "generar", "hazme", "implement", "login", "endpoint"))
    if is_build or "```" in lowered:
        style["code_first"] = True
    if followup:
        style["delta_only"] = True
    if any(c in state.get("constraints", []) for c in ("concise", "no_opinions")):
        style["concise"] = True
    if "step_by_step" in state.get("constraints", []):
        style["delta_only"] = False
    if mode in {"web", "crypto"}:
        style["no_unsolicited_opinions"] = True
    if mode in {"chat", "code", "project", "image", "url"}:
        style["concise"] = True
    return style


def _derive_planner_state(
    state: SessionState,
    user_message: str,
    *,
    mode: str,
) -> Dict[str, Any]:
    """
    What it does:
    - Derives `next_tool`, `next_step`, and `missing_evidence` from turn intent.

    Why it exists:
    - Maintain fail-closed, low-ambiguity planning decisions independent of LLM output.

    Called from ->
    - update_session_state

    Calls ->
    - intent/focus detectors and normalization helpers
    """
    lowered = (user_message or "").lower()
    has_active_project = bool(state.get("active_project_id"))
    current_file_focus = str(state.get("current_file_focus") or "").strip()
    current_symbol_focus = str(state.get("current_symbol_focus") or "").strip()
    current_artifact_focus = str(state.get("current_artifact_focus") or "").strip()
    current_folder_focus = current_file_focus if _looks_like_directory_focus(current_file_focus) else ""
    next_step = (
        state.get("current_subtask")
        or state.get("current_task")
        or state.get("goal")
        or state.get("current_topic")
        or ""
    )
    next_tool: Optional[str] = None
    missing_evidence: List[str] = []
    project_clarifier = has_active_project and _looks_like_project_clarification_followup(user_message) and bool(
        str(state.get("next_tool") or "").strip().startswith("project_")
        or str(state.get("next_tool") or "").strip() == "file_search"
        or current_file_focus
        or current_symbol_focus
        or current_artifact_focus
        or next_step
        or state.get("current_topic")
    )
    tree_expansion_followup = has_active_project and bool(
        current_file_focus
        and not current_folder_focus
        and _looks_like_project_tree_expansion_followup(user_message)
        and (
            str(state.get("next_tool") or "").strip().startswith("project_")
            or str(state.get("next_tool") or "").strip() == "file_search"
            or current_artifact_focus
            or next_step
            or state.get("current_topic")
        )
    )
    followup = looks_like_followup(user_message) or project_clarifier or tree_expansion_followup
    explicit_project_scope = any(term in lowered for term in _PROJECT_SCOPE_STRICT_HINTS)
    project_intent = explicit_project_scope or any(
        term in lowered
        for term in (
            "auth",
            "login",
            "backend",
            "frontend",
            "api",
            "stack",
            "arquitectura",
            "architecture",
            "entrypoint",
            "dependenc",
            "config",
            "code",
            "source",
        )
    ) or project_clarifier or tree_expansion_followup
    referential_followup = (
        bool(current_file_focus or current_symbol_focus or current_artifact_focus)
        and followup
        and (
            project_intent
            or bool(re.search(r"\b(this|that|it|those|these|same|again|continue|next|previous|above|here|esto|eso|esta|ese|mismo|continuar)\b", lowered))
        )
    ) or project_clarifier or tree_expansion_followup
    asks_tree = tree_expansion_followup or any(
        term in lowered for term in ("what files", "files inside", "inside app", "folder app", "carpeta app", "tree", "estructura", "each file")
    )
    asks_manifest = any(term in lowered for term in ("architecture", "arquitectura", "stack", "entrypoint", "dependencies", "dependencias", "configs", "config", "framework"))
    asks_excerpt = any(term in lowered for term in ("show", "read", "open", "inside", "contenido", "content", "explain", "code", "inspect", "analiza", "analyze"))
    asks_location = any(term in lowered for term in ("where", "donde", "dónde", "which file", "archivo", "path", "ruta"))
    asks_fresh = any(term in lowered for term in ("latest", "current", "docs", "documentation", "version", "package", "library"))
    imperative_project_analysis = bool(
        explicit_project_scope
        and not is_question_like(user_message)
        and (
            asks_tree
            or asks_manifest
            or asks_excerpt
            or asks_location
            or any(term in lowered for term in ("active project", "this project", "proyecto activo", "este proyecto", "repo", "repository", "codebase"))
        )
    )

    file_focus = _extract_file_focus(user_message) or (
        _parent_directory_focus(current_file_focus) if tree_expansion_followup else current_file_focus
    )
    file_focus_is_dir = _looks_like_directory_focus(file_focus)
    artifact_focus_is_dir = _looks_like_directory_focus(current_artifact_focus)
    symbol_focus = _extract_symbol_focus(user_message) or current_symbol_focus

    if has_active_project and project_intent and asks_tree:
        next_tool = "project_files"
    elif has_active_project and file_focus and file_focus_is_dir and (project_intent or referential_followup) and (asks_tree or asks_excerpt or referential_followup):
        next_tool = "project_files"
    elif has_active_project and file_focus and (project_intent or referential_followup) and (asks_excerpt or referential_followup):
        next_tool = "project_excerpt"
    elif has_active_project and symbol_focus and (project_intent or referential_followup) and (asks_location or asks_excerpt or referential_followup):
        next_tool = "project_symbols"
    elif has_active_project and asks_manifest:
        next_tool = "project_manifest"
    elif asks_fresh or mode == "web":
        next_tool = "web_search"
    elif has_active_project and (project_intent or referential_followup):
        if current_artifact_focus or current_symbol_focus:
            next_tool = "project_symbols" if (current_symbol_focus and asks_location) else "project_excerpt"
        elif project_intent:
            next_tool = "project_manifest"

    needs_project_binding = explicit_project_scope or asks_tree or asks_manifest or (asks_location and project_intent)
    if (is_question_like(user_message) or imperative_project_analysis) and not has_active_project and needs_project_binding:
        missing_evidence.append("active_project")
    if asks_fresh and not state.get("last_web_query"):
        missing_evidence.append("fresh_web_context")
    if has_active_project and asks_location and (project_intent or referential_followup) and not (file_focus or symbol_focus):
        missing_evidence.append("file_or_symbol_focus")

    semantic_act = str(state.get("conversation_act") or "other").strip()
    semantic_source_policy = str(state.get("source_policy") or "local").strip()
    semantic_web_required = bool(state.get("web_required"))
    semantic_allow_run = bool(state.get("allow_run"))

    if semantic_act in {"greeting", "help", "acknowledgement"} and (not next_step or _trim_text(next_step).lower() in {"hola", "hello", "hi", "hey", "buenas", "buenos dias", "buenos días"}):
        next_step = "answer directly and keep the conversation aligned"

    if not next_tool:
        if semantic_act in {"greeting", "help", "acknowledgement"}:
            next_tool = "llm_synthesis"
            if not next_step:
                next_step = "answer directly and keep the conversation aligned"
        elif semantic_act == "question_about_run":
            next_tool = "llm_synthesis"
            if not next_step:
                next_step = "explain whether the requested run is safe or useful"
        elif semantic_act == "classification":
            next_tool = "llm_synthesis"
            if not next_step:
                next_step = "classify the request and summarize the category"
        elif semantic_act == "definition":
            next_tool = "web_search" if semantic_source_policy in {"web", "mixed"} or semantic_web_required else "llm_synthesis"
            if not next_step:
                next_step = "define the requested concept clearly"
        elif semantic_act == "execute_analysis":
            if has_active_project and (project_intent or current_artifact_focus or current_file_focus or current_symbol_focus):
                next_tool = "project_excerpt" if (current_file_focus or current_artifact_focus) else "project_manifest"
            else:
                next_tool = "llm_synthesis"
            if not next_step:
                next_step = "perform the analysis with grounded evidence"
        elif semantic_web_required or semantic_source_policy in {"web", "mixed"}:
            next_tool = "web_search"
            if not next_step:
                next_step = "fetch supporting web evidence"

    if not next_tool and missing_evidence:
        if "active_project" in missing_evidence:
            next_tool = "project_manifest"
        elif "file_or_symbol_focus" in missing_evidence and has_active_project:
            next_tool = "file_search"
        else:
            next_tool = "web_search"
    elif not next_tool and project_clarifier and has_active_project:
        next_tool = "project_manifest"
    elif not next_tool and has_active_project and current_artifact_focus and (project_intent or referential_followup):
        next_tool = "project_files" if artifact_focus_is_dir else "project_excerpt"

    if next_tool:
        tool_step = {
            "project_manifest": "review local project architecture and key files",
            "project_files": "inspect matching project files",
            "project_symbols": "locate the relevant symbol inside the project",
            "project_excerpt": "inspect the relevant file excerpt",
            "file_search": "find the most relevant file in the project",
            "web_search": "fetch fresher external evidence",
        }.get(next_tool, "")
        if not next_step:
            next_step = tool_step
        elif tool_step and next_step == state.get("current_task"):
            next_step = _trim_text(f"{tool_step} for {next_step}")
    return {
        "next_step": _trim_text(next_step),
        "next_tool": _trim_text(next_tool or "") or None,
        "missing_evidence": _unique_trimmed_strings(missing_evidence),
    }


def is_question_like(text: str) -> bool:
    clean = _compact(text)
    lower = clean.lower()
    return bool(clean) and ("?" in clean or any(lower.startswith(prefix) for prefix in _QUESTION_PREFIXES))


def _extract_topic(text: str) -> str:
    clean = _compact(text)
    if not clean:
        return ""
    clean = re.sub(r"^(web:|url:)\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^[\[\(].*?[\]\)]\s*", "", clean)
    return _trim_text(clean)


def _extract_question_focus(text: str) -> str:
    clean = _compact(text)
    lower = clean.lower()
    if "?" in clean or any(lower.startswith(prefix) for prefix in _QUESTION_PREFIXES):
        return _trim_text(clean)
    return ""


def _extract_file_focus(text: str) -> Optional[str]:
    match = re.search(r"([A-Za-z0-9_./-]+\.(py|js|ts|tsx|jsx|json|md|yml|yaml|toml|ini|html|css|sql|txt))", text or "")
    if not match:
        return None
    return _trim_text(match.group(1))


def _looks_like_directory_focus(value: str) -> bool:
    raw = _trim_text(str(value or "")).strip().strip("/")
    if not raw:
        return False
    if raw in {".", ".."}:
        return False
    return Path(raw).suffix == ""


def _parent_directory_focus(path_value: str) -> str:
    raw = _trim_text(str(path_value or "")).strip().strip("/")
    if not raw:
        return ""
    parent = Path(raw).parent.as_posix()
    return "" if parent in {"", "."} else parent


def _extract_symbol_focus(text: str) -> Optional[str]:
    raw = text or ""
    patterns = (
        r"(?:function|class|symbol|method)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"`([A-Za-z_][A-Za-z0-9_]*)`",
        r"(?:where|donde|dónde|find|locate|search(?:\s+for)?)\s+(?:is\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+(?:defined|implemented|declared|used|handled|located)\b",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\b\s+(?:defined|implemented|declared|used|handled|located)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = _trim_text(match.group(1))
            if candidate.lower() in _SYMBOL_FOCUS_STOPWORDS:
                continue
            return candidate
    return None


def classify_conversational_act(
    text: str,
    session_state: Optional[Dict[str, Any]] = None,
    *,
    mode: str = "",
) -> Dict[str, Any]:
    """Return a compact conversational-act contract for semantic routing."""
    state = normalize_session_state(session_state)
    clean = _trim_text(strip_attachment_context(text))
    lower = clean.lower()
    current_topic = _trim_text(str(state.get("current_topic") or ""))
    followup = looks_like_followup(clean)

    def _has_any(hints: tuple[str, ...]) -> bool:
        return any(hint in lower for hint in hints)

    def _starts_any(hints: tuple[str, ...]) -> bool:
        return any(lower.startswith(hint) for hint in hints)

    normalized_turn = re.sub(r"[!?.,;:]+", " ", lower).strip()
    act = "other"
    if _starts_any(("hello", "hi", "hey", "hola", "buenas", "buenos dias", "buenos días")):
        act = "greeting"
    elif normalized_turn in {"ok", "okay", "okey", "thanks", "thank you", "ok thanks", "thanks ok", "gracias", "vale", "dale", "cool", "nice"}:
        act = "acknowledgement"
    elif _has_any(
        (
            "help",
            "ayuda",
            "how can you help",
            "what can you do",
            "what u can do",
            "who are you",
            "what are you",
            "what is your name",
            "what's your name",
            "whats your name",
            "how are you",
            "access to internet",
            "internet access",
            "browse the internet",
            "browse internet",
            "browse the web",
            "browse web",
            "can you browse",
            "can u browse",
            "do you have access",
            "u have access to internet",
            "you have access to internet",
            "que puedes hacer",
            "qué puedes hacer",
            "quien eres",
            "quién eres",
            "como estas",
            "cómo estás",
            "tienes acceso a internet",
            "tienes acceso al internet",
            "puedes navegar en internet",
            "puedes navegar por internet",
        )
    ):
        act = "help"
    elif _has_any(("classify", "classify me", "categorize", "categorise", "classification", "clasifica", "categoriza", "what category", "which category", "type of")):
        act = "classification"
    elif _has_any(("can i run", "can you run", "should i run", "how do i run", "how to run", "run this", "what happens if i run", "is it safe to run", "ejecutar", "ejecuto")):
        act = "question_about_run"
    elif _has_any(("run analysis", "execute analysis", "analyze", "analyse", "analysis", "inspect", "review", "evaluate", "deep dive", "analiza", "analizar", "inspecciona", "revisa", "evalua", "evalúa")):
        act = "execute_analysis"
    elif _has_any(("where is", "where are", "donde esta", "dónde está", "location", "geo", "capital of", "capital de")):
        act = "definition"
    elif _has_any(("what is", "what's", "whats", "define", "definition", "que es", "qué es", "what are", "que son", "qué son", "significa", "meaning of")):
        act = "definition"

    override_memory = bool(
        _has_any(("ignore previous", "start over", "new topic", "from scratch", "reset", "olvida lo anterior", "sin contexto", "new conversation"))
        or _starts_any(("new topic", "start over", "reset"))
    )

    if current_topic and followup and not override_memory:
        subject = current_topic
    else:
        subject = _extract_topic(clean)
        subject = re.sub(
            r"^(hello|hi|hey|hola|buenas|buenos dias|buenos días|help|ayuda|who are you|what are you|what is your name|what's your name|whats your name|what can you do|what u can do|how are you|who r you|do you have access|can you browse|can u browse|what is|what's|whats|define|classify|categorize|categorise|can i run|can you run|should i run|how do i run|how to run|run this|run analysis|execute analysis|analyze|analyse|analysis|inspect|review|evaluate|que es|qué es|que son|qué son|significa|quien eres|quién eres|como estas|cómo estás|tienes acceso a internet|puedes navegar en internet)\s+",
            "",
            subject,
            flags=re.IGNORECASE,
        )
        subject = _trim_text(subject)

    source_policy = "local"
    web_required = False
    if mode in {"web", "url"}:
        source_policy = "web"
        web_required = True
    elif act in {"greeting", "help", "acknowledgement"}:
        source_policy = "local"
    elif _has_any(("where is", "where are", "donde esta", "dónde está", "location", "geo", "capital of", "capital de")):
        source_policy = "web"
        web_required = True
    elif _has_any(("latest", "current", "today", "now", "news", "recent", "live", "weather", "market", "price", "precio", "precio actual", "último", "ultima", "última")):
        source_policy = "web"
        web_required = True
    elif mode == "crypto" or _has_any(("bitcoin", "btc", "crypto", "ohlcv", "prediction", "predictions", "trading", "market", "mercado", "finanzas")):
        source_policy = "mixed" if _has_any(("latest", "current", "today", "news", "market", "price")) else "local"
        web_required = source_policy == "mixed"
    elif act in {"definition", "classification"}:
        source_policy = "local"

    allow_run = act == "execute_analysis"
    if act == "question_about_run" and _has_any(("analysis", "analyze", "analyse", "inspect", "review", "evaluate")):
        allow_run = False

    return {
        "act": act,
        "subject": subject,
        "source_policy": source_policy,
        "web_required": web_required,
        "allow_run": allow_run,
        "override_memory": override_memory,
    }


def build_comp_snapshot(
    session_state: Optional[Dict[str, Any]] = None,
    *,
    plan: Optional[Dict[str, Any]] = None,
    provider: str = "",
    effective_provider: str = "",
    durable_memory_subject_count: Optional[int] = None,
    durable_memory_summary: str = "",
) -> Dict[str, Any]:
    """Return a compact orchestration snapshot for the current conversational comp."""
    state = normalize_session_state(session_state)
    semantic = classify_conversational_act("", session_state=state)
    plan_state = plan or {}
    act = str(state.get("conversation_act") or semantic.get("act") or "other").strip()
    subject = str(state.get("conversation_subject") or semantic.get("subject") or "").strip()
    source_policy = str(state.get("source_policy") or semantic.get("source_policy") or "local").strip()
    web_required = bool(state.get("web_required") or semantic.get("web_required"))
    allow_run = bool(state.get("allow_run") or semantic.get("allow_run"))
    override_memory = bool(state.get("override_memory") or semantic.get("override_memory"))
    next_tool = str(state.get("next_tool") or plan_state.get("next_tool") or "").strip()
    next_step = str(state.get("next_step") or plan_state.get("next_step") or "").strip()
    llm_required = bool(plan_state.get("llm_required", True))
    routing_confidence = float(plan_state.get("routing_confidence") or 0.0)
    ambiguous_route = bool(plan_state.get("ambiguous_route"))
    route_mode = "web" if source_policy == "web" or web_required else "mixed" if source_policy == "mixed" else "local"

    route_reason = "semantic-local"
    if act in {"greeting", "help", "acknowledgement"}:
        route_reason = "social"
    elif act == "question_about_run":
        route_reason = "run-safety"
    elif act == "execute_analysis":
        route_reason = "analysis"
    elif route_mode == "web":
        route_reason = "semantic-web"
    elif route_mode == "mixed":
        route_reason = "semantic-mixed"
    if next_tool:
        route_reason = f"planner:{next_tool}"

    if not effective_provider:
        effective_provider = provider

    memory: Dict[str, Any] = {
        "active_project_id": state.get("active_project_id") or None,
        "current_file_focus": state.get("current_file_focus") or None,
        "current_symbol_focus": state.get("current_symbol_focus") or None,
        "current_artifact_focus": state.get("current_artifact_focus") or None,
    }
    if durable_memory_subject_count is not None:
        memory["durable_subject_count"] = int(durable_memory_subject_count)
    if durable_memory_summary:
        memory["durable_summary"] = _trim_text(durable_memory_summary)

    if routing_confidence >= 0.8:
        confidence_bucket = "high"
    elif routing_confidence >= 0.55:
        confidence_bucket = "medium"
    else:
        confidence_bucket = "low"
    if routing_confidence >= 0.75:
        gate = "allow"
    elif routing_confidence >= 0.55:
        gate = "review"
    else:
        gate = "escalate"

    return {
        "controller": "comp",
        "act": act,
        "subject": subject,
        "source_policy": source_policy,
        "web_required": web_required,
        "allow_run": allow_run,
        "override_memory": override_memory,
        "route_mode": route_mode,
        "route_reason": route_reason,
        "provider": provider or None,
        "effective_provider": effective_provider or None,
        "next_tool": next_tool or None,
        "next_step": next_step or None,
        "planner": {
            "llm_required": llm_required,
            "routing_confidence": routing_confidence,
            "ambiguous_route": ambiguous_route,
        },
        "quantitative": {
            "routing_confidence": routing_confidence,
            "confidence_bucket": confidence_bucket,
            "gate": gate,
            "ambiguous_route": ambiguous_route,
        },
        "memory": memory,
    }


def infer_symbol_focus(text: str) -> Optional[str]:
    """Public wrapper so planners/routes can reuse symbol-focus extraction."""
    return _extract_symbol_focus(text)


def _extract_entities(lower: str) -> List[str]:
    found: List[str] = []
    for entity in _ENTITY_PATTERNS:
        if entity in lower:
            found.append(entity)
    acronyms = re.findall(r"\b[A-Z]{2,10}\b", lower.upper())
    for item in acronyms:
        if item.lower() not in {"i", "a"}:
            found.append(item)
    return _unique_trimmed_strings(found)


def _extract_constraints(lower: str) -> List[str]:
    found: List[str] = []
    for name, hints in _CONSTRAINT_PATTERNS.items():
        if any(hint in lower for hint in hints):
            found.append(name)
    return _unique_trimmed_strings(found)


def _detect_stack(lower: str, mapping: Dict[str, tuple[str, ...]]) -> Optional[str]:
    for key, hints in mapping.items():
        if any(hint in lower for hint in hints):
            return key
    return None


def _touch_focus(state: SessionState, *, now_ms: Optional[int] = None) -> None:
    ts = int(now_ms if now_ms is not None else (time.time() * 1000))
    state["focus_turn_budget"] = FOCUS_TURN_BUDGET
    state["focus_last_touch_ms"] = max(0, ts)


def _clear_focus(state: SessionState) -> None:
    state["current_file_focus"] = None
    state["current_symbol_focus"] = None
    state["current_artifact_focus"] = None
    state["focus_turn_budget"] = 0
    state["focus_last_touch_ms"] = 0
    if str(state.get("next_tool") or "").strip() in {"project_excerpt", "project_symbols", "file_search"}:
        state["next_tool"] = None


def _clear_stale_web_context(state: SessionState) -> None:
    state["last_web_query"] = ""
    state["last_web_sources"] = []
    state["last_web_findings"] = []
    failures = [
        str(item).strip()
        for item in (state.get("recent_tool_failures") or [])
        if str(item).strip() and not str(item).strip().startswith(("web_search:", "web_evidence_exhausted:"))
    ]
    state["recent_tool_failures"] = _unique_trimmed_strings(failures)


def _apply_focus_decay(
    state: SessionState,
    *,
    now_ms: int,
    explicit_focus: bool,
    referential_followup: bool,
) -> None:
    has_focus = bool(
        state.get("current_file_focus")
        or state.get("current_symbol_focus")
        or state.get("current_artifact_focus")
    )
    if not has_focus:
        state["focus_turn_budget"] = FOCUS_TURN_BUDGET
        state["focus_last_touch_ms"] = 0
        return

    last_touch = int(state.get("focus_last_touch_ms") or 0)
    if last_touch and (now_ms - last_touch) > FOCUS_TTL_MS:
        _clear_focus(state)
        return

    if explicit_focus or referential_followup:
        _touch_focus(state, now_ms=now_ms)
        return

    budget = int(state.get("focus_turn_budget") or FOCUS_TURN_BUDGET)
    budget -= 1
    if budget <= 0:
        _clear_focus(state)
        return
    state["focus_turn_budget"] = budget


def _has_explicit_project_scope_hint(text: str) -> bool:
    raw = str(text or "")
    lower = raw.lower()
    if any(hint in lower for hint in _PROJECT_SCOPE_STRICT_HINTS):
        return True
    if re.search(r"(\/|\\).+[A-Za-z0-9_]", raw):
        return True
    if re.search(r"\b[\w.-]+\.(py|js|ts|tsx|jsx|md|txt|json|yml|yaml|html|css|sql|ini|toml)\b", lower):
        return True
    return False


def _should_clear_focus_on_topic_switch(
    state: SessionState,
    *,
    user_message: str,
    followup: bool,
    explicit_focus: bool,
    referential_followup: bool,
) -> bool:
    if not FOCUS_CLEAR_ON_TOPIC_SWITCH:
        return False
    has_focus = bool(
        state.get("current_file_focus")
        or state.get("current_symbol_focus")
        or state.get("current_artifact_focus")
    )
    if not has_focus:
        return False
    if explicit_focus or referential_followup:
        return False
    # `looks_like_followup` is intentionally broad; do not let short world
    # questions block stale-focus cleanup unless they are clearly referential.
    if followup and _has_explicit_project_scope_hint(user_message):
        return False
    if _has_explicit_project_scope_hint(user_message):
        return False
    return is_question_like(user_message) or len(_compact(user_message)) <= 220


def _add_unique(items: List[str], value: str) -> None:
    cleaned = _trim_text(value)
    if not cleaned:
        return
    if cleaned in items:
        return
    items.append(cleaned)
    if len(items) > MAX_LIST_ITEMS:
        del items[:-MAX_LIST_ITEMS]


def _unique_trimmed_strings(values: List[Any]) -> List[str]:
    out: List[str] = []
    for value in values:
        cleaned = _trim_text(str(value))
        if cleaned and cleaned not in out:
            out.append(cleaned)
        if len(out) >= MAX_LIST_ITEMS:
            break
    return out


def _trim_text(text: str) -> str:
    compact = _compact(text)
    if len(compact) > MAX_TEXT_CHARS:
        compact = compact[: MAX_TEXT_CHARS - 3].rstrip() + "..."
    return compact


def _trim_snippet(text: str, *, max_chars: int) -> str:
    snippet = (text or "").strip()
    if max_chars <= 0:
        return ""
    if len(snippet) <= max_chars:
        return snippet
    if max_chars <= 3:
        return snippet[:max_chars]
    return snippet[: max_chars - 3].rstrip() + "..."


def _looks_like_action_followup(lower: str) -> bool:
    return any(
        token in lower
        for token in (
            "continue",
            "go ahead",
            "show",
            "read",
            "open",
            "explain",
            "inspect",
            "analyze",
            "review",
            "update",
            "fix",
            "wire",
            "connect",
            "implement",
            "search",
            "find",
            "locate",
            "sigue",
            "continua",
            "continúa",
            "muestra",
            "lee",
            "abre",
            "explica",
            "inspecciona",
            "revisa",
            "arregla",
            "busca",
            "ubica",
        )
    )


def _suggest_followup_tool(state: SessionState) -> Optional[str]:
    file_focus = _trim_text(str(state.get("current_file_focus") or ""))
    symbol_focus = _trim_text(str(state.get("current_symbol_focus") or ""))
    artifact_focus = _trim_text(str(state.get("current_artifact_focus") or ""))
    if file_focus:
        return "project_files" if _looks_like_directory_focus(file_focus) else "project_excerpt"
    if symbol_focus:
        return "project_symbols"
    if state.get("active_project_id") and artifact_focus and _looks_like_directory_focus(artifact_focus):
        return "project_files"
    if state.get("active_project_id") and (
        artifact_focus
        or _trim_text(str(state.get("current_task") or ""))
        or _trim_text(str(state.get("current_subtask") or ""))
        or _trim_text(str(state.get("current_topic") or ""))
        or _trim_text(str(state.get("goal") or ""))
    ):
        return "project_manifest"
    if state.get("last_web_query"):
        return "web_search"
    return None


def _suggest_followup_step(state: SessionState, *, fallback: str = "") -> str:
    file_focus = _trim_text(str(state.get("current_file_focus") or ""))
    symbol_focus = _trim_text(str(state.get("current_symbol_focus") or ""))
    artifact_focus = _trim_text(str(state.get("current_artifact_focus") or ""))
    current_subtask = _trim_text(str(state.get("current_subtask") or ""))
    current_task = _trim_text(str(state.get("current_task") or ""))
    if file_focus:
        if _looks_like_directory_focus(file_focus):
            return _trim_text(f"continue from folder {file_focus}")
        return _trim_text(f"continue from file {file_focus}")
    if symbol_focus:
        return _trim_text(f"continue from symbol {symbol_focus}")
    if artifact_focus:
        return _trim_text(f"continue refining {artifact_focus}")
    return _trim_text(fallback or current_subtask or current_task)


__all__ = [
    "SessionState",
    "default_session_state",
    "detect_artifact_kind",
    "classify_conversational_act",
    "is_question_like",
    "looks_like_followup",
    "normalize_session_state",
    "replan_session_state",
    "update_session_state",
    "build_comp_snapshot",
]
