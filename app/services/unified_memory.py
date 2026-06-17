from __future__ import annotations

from typing import Any, Dict, Optional

from app.services import durable_memory
from app.services.session_state import normalize_session_state


def get_memory_summary(subject: Optional[str], *, max_chars: int = 800) -> str:
    return durable_memory.get_durable_memory_summary(subject, max_chars=max_chars)


def get_unified_memory_context(
    *,
    memory_subject: Optional[str],
    session_state: Optional[Dict[str, Any]] = None,
    max_chars: int = 800,
) -> Dict[str, Any]:
    state = normalize_session_state(session_state)
    durable_summary = get_memory_summary(memory_subject, max_chars=max_chars)
    memory_context: Dict[str, Any] = {
        "memory_subject": memory_subject or None,
        "durable_summary": durable_summary or None,
        "current_file_focus": state.get("current_file_focus") or None,
        "current_symbol_focus": state.get("current_symbol_focus") or None,
        "current_artifact_focus": state.get("current_artifact_focus") or None,
        "active_project_id": state.get("active_project_id") or None,
        "recent_tool_failures": (state.get("recent_tool_failures") or [])[:8],
        "missing_evidence": (state.get("missing_evidence") or [])[:8],
    }
    return memory_context


def update_unified_memory(
    *,
    subject: Optional[str],
    user_message: str,
    assistant_message: str = "",
    session_state: Optional[Dict[str, Any]] = None,
    mode: str = "",
    active_project_id: Optional[str] = None,
) -> Dict[str, Any]:
    return durable_memory.update_durable_memory(
        subject,
        user_message,
        assistant_msg=assistant_message,
        session_state=session_state,
        mode=mode,
        active_project_id=active_project_id,
    )
