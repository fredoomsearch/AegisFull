from __future__ import annotations

"""
Runtime capabilities aggregator.

Why this module exists:
- Build a single capability snapshot consumed by `/system/readyz` and `/system/snapshot`.
- Normalize optional/host-dependent services into explicit ready/degraded states.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from app.services.antivirus_service import clamav_status, latest_av_event
from app.services.project_store import list_projects
from app.services.web_search import get_web_search_status
from app.utils.runtime_helpers import product_track_default


def _embedding_status() -> Dict[str, Any]:
    """Load embedding capability state with resilient fallback payload."""
    try:
        from app.services import embedding_service
    except Exception as exc:  # noqa: BLE001
        return {"status": "disabled", "detail": str(exc)}
    try:
        return embedding_service.get_embedding_status(ensure_loaded=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _retrieval_status() -> Dict[str, Any]:
    """Load retrieval/index capability state."""
    try:
        from app.services import retrieval_service

        return retrieval_service.get_retrieval_status()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _llm_status() -> Dict[str, Any]:
    """Load local LLM backend status."""
    try:
        from app.llm_client_offload import llm_status

        return llm_status()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc), "available": False, "loaded": False}


def _image_status() -> Dict[str, Any]:
    """Load image backend/storage capability state."""
    try:
        from app.api.image import runtime_image_status

        return runtime_image_status()
    except Exception as exc:  # noqa: BLE001
        images_dir = Path("data/images").resolve()
        return {
            "status": "error",
            "detail": str(exc),
            "images_dir": str(images_dir),
            "images_dir_exists": images_dir.exists(),
        }


def _clamav_snapshot() -> Dict[str, Any]:
    status = clamav_status()
    return {
        **status,
        "latest_event": latest_av_event(),
    }


def _project_tools_status() -> Dict[str, Any]:
    """Report project tools availability from canonical project store."""
    try:
        projects = list_projects(limit=5)
        return {
            "status": "ready",
            "registered_projects": len(projects),
            "available": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "detail": str(exc),
            "registered_projects": 0,
            "available": False,
        }


def _agent_status() -> Dict[str, Any]:
    redact = (os.getenv("AEGIS_REDACT_SECRETS", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "status": "ready",
        "agent_step": True,
        "agent_run": True,
        "execute_tool": True,
        "redact_secrets": redact,
    }


def _browser_runtime_status() -> Dict[str, Any]:
    """Detect a usable browser runtime for browser-smoke/strict profile."""
    preferred = (os.getenv("AEGIS_BROWSER_BINARY") or "").strip()
    script_exists = (Path(__file__).resolve().parents[2] / "app" / "scripts" / "browser_smoke.py").exists()
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    try:
        from app.tools import find_brave_binary

        resolved = str(find_brave_binary() or "").strip()
        if resolved:
            candidates.append(resolved)
    except Exception:
        pass
    candidates.extend(["google-chrome", "chromium-browser", "chromium", "brave-browser", "brave"])

    seen: set[str] = set()
    for raw in candidates:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        path = Path(value)
        if not path.is_absolute():
            found = shutil.which(value)
            if not found:
                continue
            path = Path(found)
        try:
            if path.exists() and os.access(path, os.X_OK):
                return {
                    "status": "ready",
                    "available": True,
                    "binary": str(path),
                    "script_available": script_exists,
                }
        except Exception:
            continue

    return {
        "status": "missing",
        "available": False,
        "binary": preferred or None,
        "script_available": script_exists,
    }


def collect_runtime_capabilities(
    *,
    probe_web: bool = False,
    probe_web_query: str = "python fastapi",
    probe_web_results: int = 1,
) -> Dict[str, Any]:
    """Collect per-component capability blocks used by system endpoints."""
    return {
        "agent": _agent_status(),
        "embeddings": _embedding_status(),
        "retrieval": _retrieval_status(),
        "llm": _llm_status(),
        "web_search": get_web_search_status(
            probe=probe_web,
            probe_query=probe_web_query,
            probe_results=probe_web_results,
        ),
        "image": _image_status(),
        "clamav": _clamav_snapshot(),
        "project_tools": _project_tools_status(),
        "browser_runtime": _browser_runtime_status(),
    }


def summarize_runtime_capabilities(capabilities: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse capability blocks into canonical `ready/status/checks` summary."""
    emb = dict(capabilities.get("embeddings") or {})
    retrieval = dict(capabilities.get("retrieval") or {})
    llm = dict(capabilities.get("llm") or {})
    web = dict(capabilities.get("web_search") or {})
    image = dict(capabilities.get("image") or {})
    clamav = dict(capabilities.get("clamav") or {})
    project_tools = dict(capabilities.get("project_tools") or {})
    browser_runtime = dict(capabilities.get("browser_runtime") or {})
    strict_profile = (os.getenv("AEGIS_RUNTIME_PROFILE", "standard") or "standard").strip().lower() == "strict"
    product_track = product_track_default()
    full_track = product_track == "full"

    emb_ok = emb.get("status") != "error"
    retrieval_ok = retrieval.get("status") != "error"
    llm_ok = bool(llm.get("available")) and bool(llm.get("model_exists") or llm.get("loaded") or llm.get("remote_ready"))
    image_storage_ok = bool(image.get("images_dir_exists"))
    image_backend_ok = image.get("status") == "ready"
    web_ok = web.get("status") == "ready"
    clamav_ok = str(clamav.get("status") or "") in {"ready", "degraded", "missing"}
    project_tools_ok = bool(project_tools.get("available", True)) and project_tools.get("status") != "error"
    browser_runtime_ok = str(browser_runtime.get("status") or "") == "ready"

    core_ready = emb_ok and retrieval_ok and llm_ok and image_storage_ok and clamav_ok and project_tools_ok
    if strict_profile:
        # Product-track contract:
        # core+strict  -> image/backend and browser are non-blocking
        # full+strict  -> image/backend and browser are blocking
        core_ready = core_ready and web_ok
        if full_track:
            core_ready = core_ready and image_backend_ok and browser_runtime_ok

    degraded_reasons: List[str] = []
    if image.get("status") == "fallback-only":
        degraded_reasons.append("image:fallback-only")
    elif image.get("status") in {"degraded", "error"}:
        degraded_reasons.append(f"image:{image.get('status')}")
    include_web_degraded = bool(web.get("probe_enabled")) or (
        (os.getenv("AEGIS_READYZ_INCLUDE_WEB_DEGRADED", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    )
    if include_web_degraded and web.get("status") in {"degraded", "error", "cooldown"}:
        degraded_reasons.append(f"web:{web.get('status')}")
    if clamav.get("status") == "missing":
        degraded_reasons.append("clamav:missing")
    if strict_profile and full_track and not browser_runtime_ok:
        degraded_reasons.append(f"browser:{browser_runtime.get('status') or 'missing'}")
    if strict_profile and full_track and not image_backend_ok:
        degraded_reasons.append(f"image:{image.get('status') or 'not-ready'}")
    if strict_profile and not web_ok:
        degraded_reasons.append(f"web:{web.get('status') or 'not-ready'}")

    if degraded_reasons:
        degraded_reasons = list(dict.fromkeys(str(item) for item in degraded_reasons if str(item).strip()))

    status = "ready" if core_ready else "error"
    if core_ready and degraded_reasons:
        status = "fallback-only" if degraded_reasons == ["image:fallback-only"] else "degraded"

    levels = {
        "embeddings": str(emb.get("status") or "unknown"),
        "retrieval": str(retrieval.get("status") or "unknown"),
        "llm": "ready" if llm_ok else str(llm.get("status") or "error"),
        "web_search": str(web.get("status") or "unknown"),
        "image": str(image.get("status") or "unknown"),
        "clamav": str(clamav.get("status") or "unknown"),
        "project_tools": str(project_tools.get("status") or "unknown"),
        "browser_runtime": str(browser_runtime.get("status") or "unknown"),
    }

    return {
        "ready": core_ready,
        "status": status,
        "checks": {
            "embeddings": emb_ok,
            "retrieval": retrieval_ok,
            "llm": llm_ok,
            "image_storage": image_storage_ok,
            "image_backend": image_backend_ok,
            "web_search": web_ok,
            "clamav": clamav_ok,
            "project_tools": project_tools_ok,
            "browser_runtime": browser_runtime_ok,
        },
        "levels": levels,
        "degraded_reasons": degraded_reasons,
        "runtime_profile": "strict" if strict_profile else "standard",
        "product_track": product_track,
    }
