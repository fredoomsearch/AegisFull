from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services import durable_memory
from app.services.session_state import normalize_session_state


def get_memory_summary(subject: Optional[str], *, max_chars: int = 800) -> str:
    return durable_memory.get_durable_memory_summary(subject, max_chars=max_chars)


def _get_short_term_memory(
    session_state: Dict[str, Any] | None,
    turn_history: List[Dict[str, Any]] | None,
) -> Dict[str, Any]:
    """
    Short-term memory: current turn context and recent conversation flow.
    """
    state = session_state or {}
    history = turn_history or []
    
    # Extract recent topics from turn history
    recent_topics: List[str] = []
    for turn in history[-3:]:  # Last 3 turns max
        topic = str(turn.get("topic") or turn.get("current_topic") or "").strip()
        if topic:
            recent_topics.append(topic)
    
    return {
        "current_topic": state.get("current_topic"),
        "previous_topic": state.get("previous_topic") or state.get("last_topic"),
        "recent_topics": recent_topics[:3],
    }


def _get_working_memory(session_state: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Working memory: file/symbol focus persistence for session continuity.
    """
    state = session_state or {}
    return {
        "current_file_focus": state.get("current_file_focus") or None,
        "current_symbol_focus": state.get("current_symbol_focus") or None,
        "current_artifact_focus": state.get("current_artifact_focus") or None,
    }


def _get_semantic_memory(session_state: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Semantic memory: entities, constraints, and learned patterns from session.
    """
    state = session_state or {}
    return {
        "entities": (state.get("entities") or [])[:10],
        "constraints": (state.get("constraints") or [])[:5],
    }


def _merge_unified_memory_layers(
    durable_summary: str,
    short_term: Dict[str, Any],
    working: Dict[str, Any],
    semantic: Dict[str, Any],
    project_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Consolidate all memory layers into unified memory view.
    """
    return {
        "durable": {
            "summary": durable_summary,
        },
        "short_term": short_term,
        "working": working,
        "semantic": semantic,
        "project": {
            "active_project_id": project_context.get("active_project_id"),
            "summary": project_context.get("durable_summary"),
        },
    }


def get_unified_memory_context(
    *,
    memory_subject: Optional[str],
    session_state: Optional[Dict[str, Any]] = None,
    max_chars: int = 800,
    turn_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    True unified memory context combining:
    - Durable memory (persistent across sessions)
    - Short-term memory (current turn context)
    - Working memory (file/symbol focus persistence)
    - Semantic memory (entities, constraints)
    """
    state = normalize_session_state(session_state)
    durable_summary = get_memory_summary(memory_subject, max_chars=max_chars)
    
    # Get all memory layers
    short_term = _get_short_term_memory(state, turn_history)
    working = _get_working_memory(state)
    semantic = _get_semantic_memory(state)
    
    # Merge into unified context
    unified = _merge_unified_memory_layers(
        durable_summary=durable_summary,
        short_term=short_term,
        working=working,
        semantic=semantic,
        project_context={
            "active_project_id": state.get("active_project_id"),
            "durable_summary": None,
        },
    )
    
    # Flat structure for backward compatibility with existing call sites
    memory_context: Dict[str, Any] = {
        "memory_subject": memory_subject or None,
        "durable_summary": durable_summary or None,
        "current_file_focus": working.get("current_file_focus") or None,
        "current_symbol_focus": working.get("current_symbol_focus") or None,
        "current_artifact_focus": working.get("current_artifact_focus") or None,
        "active_project_id": state.get("active_project_id") or None,
        "recent_tool_failures": (state.get("recent_tool_failures") or [])[:8],
        "missing_evidence": (state.get("missing_evidence") or [])[:8],
        # Enhanced unified memory layers
        "short_term": short_term,
        "working": working,
        "semantic": semantic,
        "_unified": unified,
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
