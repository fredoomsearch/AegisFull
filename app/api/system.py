from __future__ import annotations

"""
System runtime truth endpoints.

Why this module exists:
- Expose canonical runtime readiness (`/system/readyz`).
- Provide deep diagnostic snapshot (`/system/snapshot`).
- Surface validation/gate telemetry for startup and strict verification.
"""

import os
import socket
import time
import signal
import threading
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import require_admin_api_key, require_api_key
from app.api.router_status import snapshot_router_status
from app.services import crypto_prediction_log, crypto_trade_log, job_manager
from app.services.crypto_runtime import build_crypto_state_snapshot
from app.services.durable_memory import snapshot as durable_memory_snapshot
from app.services.session_state import build_comp_snapshot
from app.services import health_state, runtime_metrics
from app.services.capabilities_service import (
    collect_runtime_capabilities,
    summarize_runtime_capabilities,
)
from app.models.llm_utils import llm_contract_snapshot
from app.services.validation_state import snapshot as validation_runtime_snapshot
from app.utils.runtime_helpers import product_track_default as _product_track_default

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_api_key)])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = Path(os.getenv("FILES_UPLOAD_ROOT", "data/uploads")).resolve()
PROCESS_START_TS = time.time()
START_WITH_PREFLIGHT_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "start_with_preflight.py"
VERIFY_FULL_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "verify_full.py"
BROWSER_SMOKE_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "browser_smoke.py"
UI_CONTRACT_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "ui_contract_check.py"
AGENT_EVAL_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "agent_eval_check.py"
ADVERSARIAL_EVAL_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "adversarial_eval_check.py"
HARD_CONTRACT_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "hard_contract_check.py"
SOAK_GATE_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "soak_gate.py"
NO_LOOP_STRESS_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "no_loop_stress_check.py"
DEMO_CHECK_SCRIPT = PROJECT_ROOT / "app" / "scripts" / "demo_check.py"


def _runtime_profile() -> str:
    """Return normalized runtime profile (`standard` or `strict`)."""
    raw = (os.getenv("AEGIS_RUNTIME_PROFILE", "standard") or "standard").strip().lower()
    return "strict" if raw == "strict" else "standard"


def _startup_contract_mode() -> str:
    raw = (os.getenv("AEGIS_START_CONTRACT_MODE", "full") or "full").strip().lower()
    return raw if raw in {"full", "strict", "none"} else "full"


class LLMProviderUpdateRequest(BaseModel):
    provider: str


def _normalize_llm_provider(provider: str) -> str:
    value = str(provider or '').strip().lower()
    if value == 'cloud':
        return 'groq'
    if value in {'local', 'groq', 'auto'}:
        return value
    raise HTTPException(status_code=400, detail='provider must be one of: local, cloud, groq, auto')


def _llm_provider_payload(capabilities: Dict[str, Any] | None = None, *, updated: bool = False) -> Dict[str, Any]:
    caps = capabilities or collect_runtime_capabilities()
    llm_config = _resources_snapshot(caps).get('llm_config') or {}
    configured = str(llm_config.get('provider') or '')
    effective = str(llm_config.get('effective_provider') or '')
    model = str(llm_config.get('model') or '')
    remote_ready = bool(llm_config.get('remote_ready'))
    options = [
        {
            'id': 'local',
            'provider': 'local',
            'label': 'Local',
            'description': 'Local GGUF model. Best when you want offline execution and local-only fallback.',
        },
        {
            'id': 'cloud',
            'provider': 'groq',
            'label': 'Cloud',
            'description': 'Groq remote model. Best for faster general chat and stronger reasoning when configured.',
        },
    ]
    return {
        'ok': True,
        'updated': bool(updated),
        'configured_provider': configured,
        'effective_provider': effective,
        'model': model,
        'remote_ready': remote_ready,
        'options': options,
    }


def _resources_snapshot(capabilities: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Collect runtime resource telemetry used by system endpoints/UI."""
    caps = capabilities or {}
    llm = dict(caps.get("llm") or {})

    cpu_count = os.cpu_count() or 0
    try:
        load1, load5, load15 = os.getloadavg()
        load = {"1m": load1, "5m": load5, "15m": load15}
    except Exception:
        load = {}

    mem = {"rss_mb": None, "vms_mb": None, "available_mb": None, "total_mb": None}
    try:
        import psutil  # type: ignore

        p = psutil.Process()
        mi = p.memory_info()
        mem["rss_mb"] = int(mi.rss / (1024 * 1024))
        mem["vms_mb"] = int(mi.vms / (1024 * 1024))
        vm = psutil.virtual_memory()
        mem["available_mb"] = int(vm.available / (1024 * 1024))
        mem["total_mb"] = int(vm.total / (1024 * 1024))
    except Exception:
        pass

    gpu: Dict[str, Any] = {"available": False, "probed": False}
    probe_gpu = (os.getenv("AEGIS_RESOURCES_PROBE_GPU", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    if probe_gpu:
        gpu["probed"] = True
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                idx = int(torch.cuda.current_device())
                props = torch.cuda.get_device_properties(idx)
                gpu = {
                    "available": True,
                    "probed": True,
                    "device": props.name,
                    "total_vram_mb": int(props.total_memory / (1024 * 1024)),
                    "allocated_mb": int(torch.cuda.memory_allocated(idx) / (1024 * 1024)),
                    "reserved_mb": int(torch.cuda.memory_reserved(idx) / (1024 * 1024)),
                }
        except Exception:
            pass

    return {
        "ts_ms": int(time.time() * 1000),
        "cpu": {"count": cpu_count, "load": load},
        "mem": mem,
        "gpu": gpu,
        "llm_config": {
            "ctx": llm.get("ctx"),
            "threads": llm.get("threads"),
            "gpu_layers": llm.get("gpu_layers"),
            "batch": llm.get("batch"),
            "max_new_tokens": llm.get("max_new_tokens"),
            "model_path": llm.get("model_path"),
            "model": llm.get("model"),
            "provider": llm.get("provider"),
            "effective_provider": llm.get("effective_provider"),
            "remote_ready": llm.get("remote_ready"),
            "contract": llm_contract_snapshot(),
        },
    }


def _agent_profile_snapshot() -> Dict[str, Any]:
    """Expose current planner/tool policy and budgets from runtime config."""
    tool_order = ["local_tools", "project_context", "web_retrieval", "llm_reasoning"]
    offline_mode = (os.getenv("AEGIS_OFFLINE_MODE", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}

    def _int_env(name: str, default: int) -> int:
        raw = (os.getenv(name) or "").strip()
        try:
            return int(raw) if raw else default
        except Exception:
            return default

    return {
        "offline_mode": offline_mode,
        "tool_routing_order": tool_order,
        "prompt_budget": {
            "max_prompt_chars": _int_env("AEGIS_MAX_PROMPT_CHARS", 5000),
            "max_response_chars": _int_env("AEGIS_MAX_RESPONSE_CHARS", 8000),
            "history_fetch_limit": _int_env("AEGIS_HISTORY_FETCH_LIMIT", 24),
        },
        "session_state_limits": {
            "max_items": _int_env("AEGIS_SESSION_MAX_ITEMS", 8),
            "max_text_chars": _int_env("AEGIS_SESSION_MAX_TEXT_CHARS", 180),
        },
        "web_policy": {
            "providers": (os.getenv("AEGIS_SEARCH_PROVIDERS") or "").strip(),
            "timeout_s": (os.getenv("AEGIS_SEARCH_TIMEOUT") or "").strip(),
            "cache_ttl_s": (os.getenv("AEGIS_SEARCH_CACHE_TTL") or "").strip(),
            "disk_cache_ttl_s": (os.getenv("AEGIS_SEARCH_CACHE_DISK_TTL") or "").strip(),
        },
    }


def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _runtime_metrics_alerts(metrics: Dict[str, Any]) -> Dict[str, Any]:
    rates = dict(metrics.get("rates") or {})
    safety_rate = float(rates.get("safety_fallback_rate") or 0.0)
    poll_401_rate = float(rates.get("poll_401_rate") or 0.0)
    ambiguous_route_rate = float(rates.get("ambiguous_route_rate") or 0.0)
    low_confidence_route_rate = float(rates.get("low_confidence_route_rate") or 0.0)

    thresholds = {
        "safety_fallback_rate_max": _float_env("AEGIS_CONTRACT_MAX_SAFETY_FALLBACK_RATE", 0.03),
        "poll_401_rate_max": _float_env("AEGIS_CONTRACT_MAX_POLL_401_RATE", 0.02),
        "ambiguous_route_rate_max": _float_env("AEGIS_CONTRACT_MAX_AMBIGUOUS_ROUTE_RATE", 0.5),
        "low_confidence_route_rate_max": _float_env("AEGIS_CONTRACT_MAX_LOW_CONFIDENCE_ROUTE_RATE", 0.75),
    }

    breaches: List[str] = []
    if safety_rate > thresholds["safety_fallback_rate_max"]:
        breaches.append("safety_fallback_rate")
    if poll_401_rate > thresholds["poll_401_rate_max"]:
        breaches.append("poll_401_rate")
    if ambiguous_route_rate > thresholds["ambiguous_route_rate_max"]:
        breaches.append("ambiguous_route_rate")
    if low_confidence_route_rate > thresholds["low_confidence_route_rate_max"]:
        breaches.append("low_confidence_route_rate")

    return {
        "ok": len(breaches) == 0,
        "breaches": breaches,
        "thresholds": thresholds,
        "rates": {
            "safety_fallback_rate": safety_rate,
            "poll_401_rate": poll_401_rate,
            "ambiguous_route_rate": ambiguous_route_rate,
            "low_confidence_route_rate": low_confidence_route_rate,
        },
    }


def _is_under_uploads(path: Path) -> bool:
    try:
        return UPLOADS_DIR in path.resolve().parents or path.resolve() == UPLOADS_DIR
    except Exception:
        return False


def _serialize_root(entry: Path) -> Dict[str, Any]:
    stat = entry.stat()
    rel = entry.relative_to(PROJECT_ROOT)
    info: Dict[str, Any] = {
        "name": entry.name,
        "path": str(rel),
        "type": "dir" if entry.is_dir() else "file",
        "is_dir": entry.is_dir(),
        "size": stat.st_size,
        "modified": int(stat.st_mtime * 1000),
    }
    if entry.is_dir():
        try:
            children = list(entry.iterdir())
            info["items"] = len(children)
        except Exception:
            info["items"] = None
    return info


def _list_ingest_roots(limit: int = 25) -> List[Dict[str, Any]]:
    if not UPLOADS_DIR.exists():
        return []
    roots: List[Dict[str, Any]] = []
    try:
        entries = sorted(
            [p for p in UPLOADS_DIR.iterdir() if _is_under_uploads(p)],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        entries = []

    for entry in entries[:limit]:
        try:
            roots.append(_serialize_root(entry))
        except Exception:
            continue
    return roots

def _pnl_snapshot() -> Dict[str, Any]:
    try:
        trades = crypto_trade_log.list_trades(limit=200)
        pnl = crypto_trade_log.compute_pnl(trades, price_lookup=lambda _sym: None)
        return pnl
    except Exception:
        return {}


def _env_snapshot() -> Dict[str, Any]:
    """Expose a few non-sensitive env toggles to help the assistant describe its state."""
    keys = [
        "BINANCE_LIVE",
        "BINANCE_LIVE_TRADING",
        "AEGIS_SEARCH_PROVIDERS",
        "AEGIS_WEB_SNIPPETS_MAX_PAGES",
        "AEGIS_SEARCH_CACHE_TTL",
        "AEGIS_SEARCH_CACHE_DISK_TTL",
        "AEGIS_READYZ_PROBE_WEB",
        "AEGIS_READYZ_INCLUDE_WEB_DEGRADED",
        "AEGIS_DISABLE_EMBEDDINGS",
        "AEGIS_DISABLE_DB",
        "AEGIS_DEMO_MODE",
        "AEGIS_FAST_MODE",
        "AEGIS_START_CONTRACT_MODE",
        "AEGIS_MODEL_PATH",
        "AEGIS_LLM_PROVIDER",
        "AEGIS_GROQ_MODEL",
        "AEGIS_GROQ_BASE_URL",
        "AEGIS_GROQ_TIMEOUT_SECONDS",
    ]
    out: Dict[str, Any] = {}
    for k in keys:
        v = os.getenv(k)
        if v is not None:
            out[k] = v
    return out


def _process_snapshot() -> Dict[str, Any]:
    """Summarize the current backend process identity for UI/status surfaces."""
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "hostname": socket.gethostname(),
        "uptime_s": round(max(0.0, time.time() - PROCESS_START_TS), 1),
    }


def _security_snapshot() -> Dict[str, Any]:
    """Summarize effective security posture and derived risk flags."""
    auth_mode = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()
    cors_raw = (os.getenv("AEGIS_CORS_ORIGINS", "*") or "*").strip()
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()] or ["*"]
    cors_wildcard = "*" in cors_origins
    cors_creds_raw = (os.getenv("AEGIS_CORS_ALLOW_CREDENTIALS", "auto") or "auto").strip().lower()
    secure_headers = (os.getenv("AEGIS_SECURE_HEADERS", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
    hsts_seconds_raw = (os.getenv("AEGIS_HSTS_SECONDS", "0") or "0").strip()
    try:
        hsts_seconds = int(hsts_seconds_raw)
    except Exception:
        hsts_seconds = 0

    weak_tokens = {"my-secret-key", "changeme", "change-me", "dev", "test", "password"}
    weak_keys: List[str] = []
    for env_name in ("AEGIS_API_KEY", "FILES_API_KEY", "ADMIN_API_KEY"):
        raw = (os.getenv(env_name) or "").strip()
        if not raw:
            continue
        if any(k.strip().lower() in weak_tokens for k in raw.split(",") if k.strip()):
            weak_keys.append(env_name)

    risks: List[str] = []
    if auth_mode != "on":
        risks.append(f"auth_mode={auth_mode}")
    if cors_wildcard:
        risks.append("cors_wildcard")
    if not secure_headers:
        risks.append("secure_headers_disabled")
    if hsts_seconds <= 0:
        risks.append("hsts_disabled")
    risks.extend([f"weak_key:{k}" for k in weak_keys])

    return {
        "auth_mode": auth_mode,
        "cors_origins": cors_origins,
        "cors_allow_credentials": cors_creds_raw,
        "cors_wildcard": cors_wildcard,
        "secure_headers_enabled": secure_headers,
        "hsts_seconds": hsts_seconds,
        "weak_keys": weak_keys,
        "risks": risks,
    }


def _validation_snapshot() -> Dict[str, Any]:
    """Expose validation pipeline shape and latest recorded run statuses."""
    runtime_validation = validation_runtime_snapshot() or {}
    browser_smoke_default = BROWSER_SMOKE_SCRIPT.exists()
    strict_default = _runtime_profile() == "strict"
    product_track = _product_track_default()
    strict_browser_default = strict_default and product_track == "full"
    startup_gate = [
        "host-prereq",
        "pytest-smoke",
        "agent-evals",
        "preflight-e2e",
        "host-e2e",
        "readyz",
    ]
    if UI_CONTRACT_SCRIPT.exists():
        startup_gate.append("ui-contract")
    if HARD_CONTRACT_SCRIPT.exists():
        startup_gate.append("hard-contract")
    if NO_LOOP_STRESS_SCRIPT.exists():
        startup_gate.append("no-loop-stress")
    if browser_smoke_default:
        startup_gate.append("browser-smoke")

    verify_full = [
        "host-prereq",
        "pytest-full",
        "e2e-strict",
    ]
    if AGENT_EVAL_SCRIPT.exists():
        verify_full.append("agent-evals")
    if UI_CONTRACT_SCRIPT.exists():
        verify_full.append("ui-contract")
    if HARD_CONTRACT_SCRIPT.exists():
        verify_full.append("hard-contract")
    if NO_LOOP_STRESS_SCRIPT.exists():
        verify_full.append("no-loop-stress")
    if browser_smoke_default:
        verify_full.append("browser-smoke")

    return {
        "startup_gate": startup_gate,
        "verify_full": verify_full,
        "browser_smoke_default": browser_smoke_default,
        "browser_smoke_strict_default": strict_browser_default,
        "runtime_profile_default": _runtime_profile(),
        "product_track_default": product_track,
        "contract_mode_default": _startup_contract_mode(),
        "last_runs": runtime_validation.get("flows", {}),
        "last_updated_ms": runtime_validation.get("last_updated_ms"),
        "scripts": {
            "start_with_preflight": START_WITH_PREFLIGHT_SCRIPT.exists(),
            "verify_full": VERIFY_FULL_SCRIPT.exists(),
            "agent_eval_check": AGENT_EVAL_SCRIPT.exists(),
            "adversarial_eval_check": ADVERSARIAL_EVAL_SCRIPT.exists(),
            "hard_contract_check": HARD_CONTRACT_SCRIPT.exists(),
            "soak_gate": SOAK_GATE_SCRIPT.exists(),
            "no_loop_stress_check": NO_LOOP_STRESS_SCRIPT.exists(),
            "browser_smoke": browser_smoke_default,
            "demo_check": DEMO_CHECK_SCRIPT.exists(),
        },
    }

def _api_surfaces_snapshot() -> Dict[str, Any]:
    """
    Report which routers/surfaces are active or intentionally legacy.
    """
    router_status = snapshot_router_status()

    def _mounted(label: str) -> bool:
        return bool((router_status.get(label) or {}).get("mounted"))

    def _flag(name: str, default: str) -> bool:
        return (os.getenv(name, default) or default).strip().lower() in {"1", "true", "yes", "on"}

    return {
        "chat_api": _mounted("chat"),
        "crypto_api": _mounted("crypto"),
        "data_api": _mounted("data"),
        "notifications_api": _mounted("notifications"),
        "tools_api_legacy": True,
        "tools_api_legacy_mode": "410-gone",
        "system_api": _mounted("system"),
        "admin_api": _mounted("admin"),
        "auth_api": _mounted("auth"),
        "image_api": _mounted("image"),
        "meta_api": _mounted("meta"),
        # runtime-only, but users ask about it often
        "shutdown_endpoint": _flag("AEGIS_ENABLE_SHUTDOWN_ENDPOINT", "0"),
        "inprocess_e2e_gate": _flag("AEGIS_ENABLE_INPROCESS_E2E", "0"),
        "router_status": router_status,
    }


@router.get("/snapshot")
async def system_snapshot() -> Dict[str, Any]:
    """
    What it does:
    - Returns the canonical diagnostic snapshot consumed by operators and UI.

    Why it exists:
    - Centralize runtime truth in one endpoint instead of scattered checks.

    Called from ->
    - Status/session panel in UI
    - Operational and debugging checks

    Calls ->
    - capabilities_service (runtime probes)
    - runtime_metrics + validation_state
    - crypto snapshot helpers (predictions/PnL)
    """
    probe = (os.getenv("AEGIS_READYZ_PROBE_WEB", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    probe_query = (os.getenv("AEGIS_READYZ_WEB_QUERY") or "python fastapi").strip() or "python fastapi"
    capabilities = collect_runtime_capabilities(
        probe_web=probe,
        probe_web_query=probe_query,
        probe_web_results=1,
    )
    summary = summarize_runtime_capabilities(capabilities)
    jobs = [job_manager.serialize_job(j) for j in job_manager.list_jobs(limit=5)]
    preds = crypto_prediction_log.pair_predictions_with_outcomes(limit=10)
    stats = crypto_prediction_log.recent_stats(limit=200)
    pnl = _pnl_snapshot()
    crypto_state = build_crypto_state_snapshot(limit=10, trade_limit=50, leaderboard_limit=6)
    health = health_state.snapshot()
    metrics = runtime_metrics.snapshot()
    metrics_alerts = _runtime_metrics_alerts(metrics)
    durable = durable_memory_snapshot()
    llm_config = _resources_snapshot(capabilities)["llm_config"]
    comp = build_comp_snapshot(
        None,
        provider=str(llm_config.get("provider") or ""),
        effective_provider=str(llm_config.get("effective_provider") or ""),
        durable_memory_subject_count=int(durable.get("subject_count") or 0),
        durable_memory_summary=str(durable.get("summary") or ""),
    )

    return {
        "ingest_roots": _list_ingest_roots(),
        "jobs": jobs,
        "process": _process_snapshot(),
        "resources": {**_resources_snapshot(capabilities), "comp": comp},
        "agent_profile": _agent_profile_snapshot(),
        "durable_memory": durable,
        "api_surfaces": _api_surfaces_snapshot(),
        **capabilities,
        "runtime_profile": str(summary.get("runtime_profile") or _runtime_profile()),
        "product_track": str(summary.get("product_track") or _product_track_default()),
        "status": summary["status"],
        "checks": summary["checks"],
        "degraded_reasons": summary["degraded_reasons"],
        "security": _security_snapshot(),
        "validation": _validation_snapshot(),
        "predictions": preds,
        "stats": stats,
        "pnl": pnl,
        "crypto_state": crypto_state,
        "env": _env_snapshot(),
        "health": health,
        "runtime_metrics": metrics,
        "runtime_metrics_alerts": metrics_alerts,
    }


@router.get("/llm/provider")
async def llm_provider_state() -> Dict[str, Any]:
    capabilities = collect_runtime_capabilities()
    return _llm_provider_payload(capabilities)


@router.post("/llm/provider")
async def set_llm_provider(payload: LLMProviderUpdateRequest) -> Dict[str, Any]:
    normalized = _normalize_llm_provider(payload.provider)
    os.environ['AEGIS_LLM_PROVIDER'] = normalized
    capabilities = collect_runtime_capabilities()
    return _llm_provider_payload(capabilities, updated=True)


@router.get("/readyz")
async def readyz() -> Dict[str, Any]:
    """
    What it does:
    - Reports machine-readable readiness and degraded reasons.

    Why it exists:
    - Gate startup/strict flows with one deterministic health contract.

    Called from ->
    - start_with_preflight / verify_full
    - deploy/runtime monitors

    Calls ->
    - capabilities_service summary
    - runtime_metrics snapshot + alert thresholds

    Failure/guard behavior:
    - Returns `ready=False` with detailed checks instead of throwing, so callers
      can inspect precise degraded subsystems.
    """
    probe = (os.getenv("AEGIS_READYZ_PROBE_WEB", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    probe_query = (os.getenv("AEGIS_READYZ_WEB_QUERY") or "python fastapi").strip() or "python fastapi"
    capabilities = collect_runtime_capabilities(
        probe_web=probe,
        probe_web_query=probe_query,
        probe_web_results=1,
    )
    summary = summarize_runtime_capabilities(capabilities)
    jobs = [job_manager.serialize_job(j) for j in job_manager.list_jobs(limit=3)]
    metrics = runtime_metrics.snapshot(window_seconds=300)
    metrics_alerts = _runtime_metrics_alerts(metrics)

    durable = durable_memory_snapshot()
    llm_config = _resources_snapshot(capabilities)["llm_config"]
    crypto_state = build_crypto_state_snapshot(limit=10, trade_limit=50, leaderboard_limit=6)
    comp = build_comp_snapshot(
        None,
        provider=str(llm_config.get("provider") or ""),
        effective_provider=str(llm_config.get("effective_provider") or ""),
        durable_memory_subject_count=int(durable.get("subject_count") or 0),
        durable_memory_summary=str(durable.get("summary") or ""),
    )

    return {
        "ready": summary["ready"],
        "status": summary["status"],
        "checks": summary["checks"],
        "degraded_reasons": summary["degraded_reasons"],
        "process": _process_snapshot(),
        "runtime_profile": str(summary.get("runtime_profile") or _runtime_profile()),
        "product_track": str(summary.get("product_track") or _product_track_default()),
        "resources": {**_resources_snapshot(capabilities), "comp": comp},
        "agent_profile": _agent_profile_snapshot(),
        "durable_memory": durable,
        "api_surfaces": _api_surfaces_snapshot(),
        "security": _security_snapshot(),
        "validation": _validation_snapshot(),
        "crypto_state": crypto_state,
        **capabilities,
        "jobs": jobs,
        "runtime_metrics": {
            "window_seconds": metrics.get("window_seconds"),
            "rates": metrics.get("rates"),
            "window": {
                "poll_401": int((metrics.get("window") or {}).get("poll_401") or 0),
                "poll_request": int((metrics.get("window") or {}).get("poll_request") or 0),
                "safety_fallback": int((metrics.get("window") or {}).get("safety_fallback") or 0),
                "chat_response": int((metrics.get("window") or {}).get("chat_response") or 0),
            },
            "alerts": metrics_alerts,
        },
    }


@router.get("/metrics")
async def runtime_metrics_snapshot(
    window_seconds: int = Query(900, ge=60, le=86400),
) -> Dict[str, Any]:
    """
    What it does:
    - Returns reliability counters/rates for the requested time window.

    Why it exists:
    - Decouple gate/alert logic from internal service state.

    Called from ->
    - hard_contract_check
    - dashboards and ops tooling

    Calls ->
    - runtime_metrics.snapshot
    """
    return runtime_metrics.snapshot(window_seconds=window_seconds)


@router.get("/demo_check")
async def demo_check() -> Dict[str, Any]:
    """
    Small, deterministic self-check endpoint for interview demos.

    This intentionally mirrors the "what matters" summary:
    - core readiness + degraded reasons
    - where to open the UI
    - how to stop cleanly
    """
    probe = (os.getenv("AEGIS_READYZ_PROBE_WEB", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    probe_query = (os.getenv("AEGIS_READYZ_WEB_QUERY") or "python fastapi").strip() or "python fastapi"
    capabilities = collect_runtime_capabilities(
        probe_web=probe,
        probe_web_query=probe_query,
        probe_web_results=1,
    )
    summary = summarize_runtime_capabilities(capabilities)
    return {
        "ok": bool(summary["ready"]),
        "ready": summary["ready"],
        "status": summary["status"],
        "checks": summary["checks"],
        "degraded_reasons": summary["degraded_reasons"],
        "ui": {"path": "/", "hint": "open in a browser"},
        "stop_hint": "./stop_aegis.sh",
    }


@router.get("/capabilities")
async def capabilities() -> Dict[str, Any]:
    """
    Canonical capabilities registry endpoint (machine-readable).
    Prefer this over scraping snapshot when you only need runtime status.
    """
    probe = (os.getenv("AEGIS_READYZ_PROBE_WEB", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    probe_query = (os.getenv("AEGIS_READYZ_WEB_QUERY") or "python fastapi").strip() or "python fastapi"
    caps = collect_runtime_capabilities(
        probe_web=probe,
        probe_web_query=probe_query,
        probe_web_results=1,
    )
    summary = summarize_runtime_capabilities(caps)
    return {"summary": summary, "capabilities": caps}


@router.get("/agent_evals")
async def agent_evals() -> Dict[str, Any]:
    """
    Deterministic internal agent evals (routing/heuristics).
    Useful for demos and quick sanity checks without running full E2E.
    """
    try:
        from app.scripts.agent_eval_check import run_agent_eval_cases

        return run_agent_eval_cases()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"agent_evals failed: {exc}") from exc


@router.post("/shutdown", dependencies=[Depends(require_admin_api_key)])
async def shutdown() -> Dict[str, Any]:
    """
    Best-effort graceful shutdown endpoint for local dev/demo.

    Disabled by default. To enable:
      export AEGIS_ENABLE_SHUTDOWN_ENDPOINT=1

    Requires ADMIN_API_KEY (or admin-scoped JWT).
    """
    enabled = (os.getenv("AEGIS_ENABLE_SHUTDOWN_ENDPOINT", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        raise HTTPException(status_code=403, detail="Shutdown endpoint disabled")

    def _delayed_term() -> None:
        time.sleep(0.5)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(0)  # noqa: S606

    threading.Thread(target=_delayed_term, daemon=True).start()
    return {"ok": True, "message": "shutting down"}
