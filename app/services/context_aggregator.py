from __future__ import annotations

from typing import Any, Dict, List

from app.services.project_manifest import load_project_manifest, summarize_architecture, summarize_manifest
from app.services.project_store import get_project
from app.services.session_state import build_comp_snapshot
from app.services.unified_memory import get_unified_memory_context
from app.services.phase_progress_manager import snapshot_stage_state
from app.services.progress_tracker import snapshot_progress


def _load_active_project_manifest(active_project_id: str | None) -> Dict[str, Any] | None:
    if not active_project_id:
        return None
    project = get_project(active_project_id)
    if not project:
        return None
    return load_project_manifest(project.get("manifest_path") or project.get("root_path") or "")


def _normalize_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item or "").strip()][:10]


def _retrieval_context_payload(raw_sources: List[Dict[str, Any]] | None, web_meta: Dict[str, Any] | None, lang: str) -> Dict[str, Any]:
    sources: list[str] = []
    for item in raw_sources or []:
        title = str(item.get("title") or item.get("url") or "").strip()
        if title:
            sources.append(title)
        if len(sources) >= 6:
            break
    meta = dict(web_meta or {})
    return {
        "web_status": str(meta.get("status") or "").strip() or "unknown",
        "web_source": str(meta.get("source") or "").strip() or "none",
        "web_provider": str(meta.get("provider") or "").strip() or "unknown",
        "web_results": int(meta.get("results") or len(raw_sources or [])),
        "web_attempted": bool(meta.get("attempted")) or bool(raw_sources),
        "top_findings": sources,
        "retrieval_hint": (
            "Estas fuentes llegaron de la búsqueda web y pueden ser usadas como evidencia directa."
            if lang.startswith("es")
            else "These sources came from the web search and can be used as direct evidence."
        ),
    }


def _tool_context_payload(
    plan: Dict[str, Any] | None,
    effective_tool: str,
    effective_tool_status: str,
    effective_tool_output: str,
) -> Dict[str, Any]:
    return {
        "effective_tool": effective_tool or None,
        "effective_tool_status": effective_tool_status or None,
        "effective_tool_output": (str(effective_tool_output or "")[:1000] or None),
        "tool_candidates": _normalize_list((plan or {}).get("tool_candidates") if isinstance(plan, dict) else []),
        "tool_risks": dict((plan or {}).get("tool_risks") or {}) if isinstance(plan, dict) else {},
        "approval_required": _normalize_list((plan or {}).get("approval_required") if isinstance(plan, dict) else []),
    }


def _evidence_summary(
    project_payload: Dict[str, Any],
    memory_context: Dict[str, Any],
    retrieval_context: Dict[str, Any],
    source_plan: str,
    lang: str,
) -> str:
    pieces: list[str] = []
    if project_payload.get("project_summary"):
        pieces.append("Project summary available.")
    if memory_context.get("durable_summary"):
        pieces.append("Durable memory summary available.")
    if retrieval_context.get("web_results"):
        pieces.append(f"Retrieved {retrieval_context['web_results']} web sources.")
    if source_plan == "local_only":
        pieces.append("Local-only path: using project and durable memory evidence.")
    elif source_plan == "web_only":
        pieces.append("Web-only path: using retrieved web sources as primary evidence.")
    else:
        pieces.append("Mixed evidence path: combining local and web context.")
    return " ".join(pieces)


def _response_guidance_payload(
    source_plan: str,
    web_meta: Dict[str, Any] | None,
    lang: str,
) -> Dict[str, Any]:
    web_status = str((web_meta or {}).get("status") or "").strip().lower()
    guidance = {
        "message": (
            "Usa `web:` si necesitas información en vivo; usa modo local si quieres evidencia del proyecto."
            if lang.startswith("es")
            else "Use `web:` if you need live information; use local mode for project evidence."
        ),
        "please_confirm_source": web_status in {"error", "unavailable"},
    }
    if source_plan == "web_only" and web_status in {"error", "unavailable"}:
        guidance["message"] = (
            "La web no estuvo disponible; responderé con evidencia local o te pediré una consulta más específica."
            if lang.startswith("es")
            else "Web was unavailable; I will answer with local evidence or ask for a narrower query."
        )
    return guidance


def _confidence_scores_payload(
    plan: Dict[str, Any] | None,
    retrieval_context: Dict[str, Any],
    memory_context: Dict[str, Any],
) -> Dict[str, float]:
    routing_confidence = float((plan or {}).get("routing_confidence") or 0.0)
    evidence_count = int(retrieval_context.get("web_results") or 0)
    filesystem = 0.8 if memory_context.get("durable_summary") or memory_context.get("active_project_id") else 0.3
    retrieval = min(1.0, evidence_count / 4.0)
    symbol_match = 0.8 if memory_context.get("current_symbol_focus") or memory_context.get("current_file_focus") else 0.3
    overall = min(1.0, max(0.0, routing_confidence * 0.6 + filesystem * 0.2 + retrieval * 0.1 + symbol_match * 0.1))
    return {
        "routing_confidence": round(routing_confidence, 2),
        "filesystem": round(filesystem, 2),
        "retrieval": round(retrieval, 2),
        "symbol_match": round(symbol_match, 2),
        "overall": round(overall, 2),
    }


def _project_context_payload(active_project_id: str | None, lang: str) -> Dict[str, Any]:
    manifest = _load_active_project_manifest(active_project_id)
    if not manifest:
        return {}
    architecture = manifest.get("architecture") if isinstance(manifest.get("architecture"), dict) else {}
    return {
        "project_summary": summarize_manifest(manifest, lang=lang),
        "architecture_summary": summarize_architecture(architecture, lang=lang) if architecture else "",
        "architecture": architecture,
        "entrypoints": list((manifest.get("entrypoints") or [])[:12]),
        "dependencies": list((manifest.get("package_files") or [])[:12]),
        "configs": list((manifest.get("config_files") or [])[:12]),
    }


def _conversation_narrative_payload(
    session_state: Dict[str, Any] | None,
    turn_history: List[Dict[str, Any]] | None,
    lang: str = "es",
) -> Dict[str, Any]:
    """
    Links previous turns with current context for conversation continuity.
    Enables unified context across turns by tracking topic transitions.
    """
    state = session_state or {}
    history = turn_history or []
    
    # Extract topic flow from recent turns
    recent_topics: List[str] = []
    for turn in history[-3:]:  # Last 3 turns max
        topic = str(turn.get("topic") or turn.get("current_topic") or "").strip()
        if topic:
            recent_topics.append(topic)
    
    # Current active topic
    current_topic = str(state.get("current_topic") or "").strip()
    previous_topic = str(state.get("previous_topic") or state.get("last_topic") or "").strip()
    
    # Topic transition detection
    topic_transition = bool(current_topic and previous_topic and current_topic.lower() != previous_topic.lower())
    
    # Entity tracking from session state
    entities = list(state.get("entities", [])[:8])
    
    # Focus continuity
    current_file = str(state.get("current_file_focus") or "").strip()
    current_symbol = str(state.get("current_symbol_focus") or "").strip()
    current_artifact = str(state.get("current_artifact_focus") or "").strip()
    
    # Build narrative link
    narrative_link: List[str] = []
    if previous_topic:
        narrative_link.append(f"prev:{previous_topic}")
    if current_topic:
        narrative_link.append(f"curr:{current_topic}")
    if topic_transition:
        narrative_hint = (
            f"的主题已切换: {previous_topic} → {current_topic}"
            if lang.startswith("es")
            else f"topic switched: {previous_topic} → {current_topic}"
        )
    else:
        narrative_hint = (
            "继续当前主题" if lang.startswith("es") else "continuing current topic"
        )
    
    return {
        "narrative_link": narrative_link,
        "narrative_hint": narrative_hint,
        "recent_topics": recent_topics,
        "current_topic": current_topic or None,
        "previous_topic": previous_topic or None,
        "topic_transition": topic_transition,
        "entities": entities,
        "focus": {
            "file": current_file or None,
            "symbol": current_symbol or None,
            "artifact": current_artifact or None,
        },
    }


def _merge_unified_memory_context(
    project_context: Dict[str, Any],
    memory_context: Dict[str, Any],
    retrieval_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Consolidates short-term + working + semantic + project + tool memory.
    Provides unified memory view for all reasoning paths.
    """
    return {
        "short_term": {
            "current_topic": memory_context.get("current_topic"),
            "recent_topics": memory_context.get("recent_topics", [])[:3],
        },
        "working": {
            "current_file_focus": memory_context.get("current_file_focus"),
            "current_symbol_focus": memory_context.get("current_symbol_focus"),
            "current_artifact_focus": memory_context.get("current_artifact_focus"),
        },
        "semantic": {
            "entities": memory_context.get("entities", [])[:10],
            "constraints": memory_context.get("constraints", [])[:5],
        },
        "project": {
            "active_project_id": project_context.get("project_id"),
            "summary": project_context.get("project_summary"),
        },
        "tool": {
            "missing_evidence": memory_context.get("missing_evidence", [])[:5],
            "recent_tool_failures": memory_context.get("recent_tool_failures", [])[:3],
        },
    }


def build_unified_context(
    source_plan: str,
    active_project_id: str | None,
    raw_sources: List[Dict[str, Any]] | None,
    web_meta: Dict[str, Any] | None,
    session_state: Dict[str, Any] | None,
    web_query: str,
    used_manifest: bool = False,
    used_local: bool = False,
    effective_tool: str = "",
    effective_tool_status: str = "",
    effective_tool_output: str = "",
    crypto_prediction_ref: Dict[str, Any] | None = None,
    plan: Dict[str, Any] | None = None,
    lang: str = "es",
) -> Dict[str, Any]:
    state = session_state or {}
    project_payload = _project_context_payload(active_project_id, lang) if active_project_id else {}
    memory_context = get_unified_memory_context(
        memory_subject=active_project_id,
        session_state=session_state,
    )
    retrieval_context = _retrieval_context_payload(raw_sources, web_meta, lang)
    tool_context = _tool_context_payload(plan, effective_tool, effective_tool_status, effective_tool_output)

    evidence_summary = _evidence_summary(project_payload, memory_context, retrieval_context, source_plan, lang)
    response_guidance = _response_guidance_payload(source_plan, web_meta, lang)
    confidence_scores = _confidence_scores_payload(plan, retrieval_context, memory_context)

    meta = dict(web_meta or {})
    web_status = str(meta.get("status") or ("not-used" if source_plan == "local_only" else "unavailable")).strip()
    web_source = str(meta.get("source") or ("none" if source_plan == "local_only" else "none")).strip()
    web_provider = str(meta.get("provider") or "").strip()
    web_results = int(meta.get("results") or len(raw_sources or []))
    web_attempted = bool(meta.get("attempted")) or source_plan in {"web_only", "local+web"}
    using_live_web = web_source == "live"
    using_cached_web = web_source == "cache"
    using_stale_cache = web_source == "stale-cache"

    source_origin: List[str] = []
    if used_manifest:
        source_origin.append("manifest")
    if used_local:
        source_origin.append("local")
    if raw_sources:
        source_origin.append("web")
    if not source_origin:
        source_origin.append("model")
    if using_stale_cache and "web" not in source_origin:
        source_origin.append("web")

    if using_live_web:
        data_notice = "Usando fuentes web en vivo." if lang.startswith("es") else "Using live web sources."
    elif using_cached_web:
        data_notice = "Usando fuentes web en caché." if lang.startswith("es") else "Using cached web sources."
    elif using_stale_cache:
        data_notice = (
            "La web en vivo no estuvo disponible; usando caché web almacenada."
            if lang.startswith("es")
            else "Live web was unavailable; using stored web cache."
        )
    elif web_attempted and source_plan in {"web_only", "local+web"}:
        if used_local or active_project_id:
            data_notice = (
                "La web no estuvo disponible; respondiendo con datos locales del proyecto."
                if lang.startswith("es")
                else "Web was unavailable; answering with local project data."
            )
        else:
            data_notice = (
                "La web no estuvo disponible; respondiendo con datos locales almacenados."
                if lang.startswith("es")
                else "Web was unavailable; answering with local stored data."
            )
    elif used_local or active_project_id or used_manifest:
        data_notice = (
            "Respondiendo con datos locales del proyecto."
            if lang.startswith("es")
            else "Answering with local project data."
        )
    else:
        data_notice = (
            "Respondiendo con contexto local del modelo."
            if lang.startswith("es")
            else "Answering with local model context."
        )

    payload: Dict[str, Any] = {
        "source_plan": source_plan,
        "source_origin": source_origin,
        "active_project_id": active_project_id,
        "web_query": web_query,
        "web_status": web_status,
        "web_source": web_source,
        "web_provider": web_provider,
        "web_results": web_results,
        "web_attempted": web_attempted,
        "using_live_web": using_live_web,
        "using_cached_web": using_cached_web,
        "using_stale_cache": using_stale_cache,
        "data_notice": data_notice,
        "effective_tool": effective_tool or None,
        "effective_tool_status": effective_tool_status or None,
        "effective_tool_output": (str(effective_tool_output or "")[:1000] or None),
        "source_context": {
            "project": project_payload,
            "memory": memory_context,
            "retrieval": retrieval_context,
            "tool": tool_context,
        },
        "evidence_summary": evidence_summary,
        "response_guidance": response_guidance,
        "confidence_scores": confidence_scores,
        "output_ready": bool(project_payload or memory_context or retrieval_context),
        "tool_approved": plan.get("tool_approved") if isinstance(plan, dict) else False,
        "pending_approval": {
            "tool": str(state.get("pending_approval", {}).get("tool") or "").strip() or None,
            "expires_ms": state.get("pending_approval", {}).get("expires_ms"),
        }
        if isinstance(state.get("pending_approval"), dict)
        else None,
        "comp": build_comp_snapshot(session_state, plan=plan),
        "source_hint": (
            "Usa la memoria unificada y las fuentes locales primero; la web solo si está disponible."
            if lang.startswith("es")
            else "Use unified memory and local sources first; use web only if available."
        ),
        "crypto_prediction_ref": (
            {
                "log_id": str((crypto_prediction_ref or {}).get("log_id") or "").strip() or None,
                "symbol": str((crypto_prediction_ref or {}).get("symbol") or "").strip().upper() or None,
                "horizon_minutes": int((crypto_prediction_ref or {}).get("horizon_minutes") or 0) or None,
                "ts": int((crypto_prediction_ref or {}).get("ts") or 0) or None,
                "source": str((crypto_prediction_ref or {}).get("source") or "").strip() or None,
                "decision": str((crypto_prediction_ref or {}).get("decision") or "").strip().upper() or None,
            }
            if isinstance(crypto_prediction_ref, dict)
            else None
        ),
    }
    payload.update(tool_context)
    payload.update(memory_context)
    try:
        payload["phase_progress"] = snapshot_progress()
    except Exception:
        payload["phase_progress"] = {}
    try:
        payload["stage_state"] = snapshot_stage_state()
    except Exception:
        payload["stage_state"] = {}
    payload.update(project_payload)
    return payload
