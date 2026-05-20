#!/usr/bin/env python3
from __future__ import annotations

"""
Mixed front/back stress runner.

Why this module exists:
- Reuse the canonical E2E/bootstrap flow to seed auth, conversation, project and crypto state.
- Exercise a broad mix of frontend/back-end surfaces in one long run.
- Make the request mix adaptable to cloud-backed chat when remote LLM is actually configured.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from app.scripts import e2e_flow_check as e2e

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class StressSpec:
    name: str
    category: str
    method: str
    path: str
    json_body: Optional[dict[str, Any]] = None
    params: Optional[dict[str, Any]] = None
    files_scope: bool = False
    validator: Optional[Callable[[Any, Any, e2e.ClientCtx], tuple[bool, str]]] = None


def _pick_free_port() -> int:
    return e2e._pick_free_port()


def _wait_ready(url: str, timeout_s: float = 20.0) -> bool:
    return e2e._wait_ready(url, timeout_s=timeout_s)


def _build_chat_payload(
    *,
    message: str,
    conversation_id: str,
    mode: str = "chat",
    synthesize: bool = False,
    use_web: bool = False,
    use_existing: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "message": message,
        "lang": "en",
        "mode": mode,
        "conversation_id": conversation_id,
        "use_existing": use_existing,
        "synthesize": synthesize,
        "use_web": use_web,
    }
    return payload


def _response_json(resp: Any) -> Any:
    return e2e._json_or_text(resp)


def _validate_dict(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict):
        return False, f"status={resp.status_code} body={data}"
    return True, "ok"


def _validate_list(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, list):
        return False, f"status={resp.status_code} body={data}"
    return True, f"items={len(data)}"


def _validate_status_ok(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict) or str(data.get("status") or "") != "ok":
        return False, f"status={resp.status_code} body={data}"
    return True, "ok"


def _validate_data_health_soft(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code == 404:
        return True, "skipped-router-disabled"
    return _validate_status_ok(resp, data, _ctx)


def _validate_chat_general(resp: Any, data: Any, ctx: e2e.ClientCtx, *, require_contains: Optional[str] = None) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict):
        return False, f"status={resp.status_code} body={data}"
    text = str(data.get("response") or "").strip()
    if not text:
        return False, "missing-response"
    if e2e._looks_like_internal_leak(text):
        return False, "internal-prompt-leak-detected"
    if require_contains and require_contains.lower() not in text.lower():
        return False, f"missing:{require_contains}"
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    if ctx.uploaded_project_id and str(context.get("active_project_id") or "") not in {"", ctx.uploaded_project_id}:
        return False, f"unexpected-active-project={context.get('active_project_id')}"
    return True, text[:120].replace("\n", " ")


def _validate_chat_project(resp: Any, data: Any, ctx: e2e.ClientCtx) -> tuple[bool, str]:
    ok, detail = _validate_chat_general(resp, data, ctx)
    if not ok:
        return ok, detail
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    if str(context.get("active_project_id") or "") != ctx.uploaded_project_id:
        return False, f"missing-project-bind={context.get('active_project_id')}"
    source_origin = context.get("source_origin") if isinstance(context.get("source_origin"), list) else []
    if "manifest" not in [str(x) for x in source_origin]:
        return False, f"missing-manifest-source={source_origin}"
    return True, "project-context-ok"


def _validate_chat_crypto(resp: Any, data: Any, ctx: e2e.ClientCtx) -> tuple[bool, str]:
    ok, detail = _validate_chat_general(resp, data, ctx)
    if not ok:
        return ok, detail
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    if str(context.get("source_plan") or "") not in {"local_only", "hybrid", "local"}:
        return False, f"unexpected-source-plan={context.get('source_plan')}"
    return True, "crypto-context-ok"


def _validate_chat_capital(resp: Any, data: Any, ctx: e2e.ClientCtx) -> tuple[bool, str]:
    ok, detail = _validate_chat_general(resp, data, ctx, require_contains="Tokyo")
    if ok:
        return ok, detail
    return _validate_chat_general(resp, data, ctx, require_contains="Tokio")


def _validate_trade_preview(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict):
        return False, f"status={resp.status_code} body={data}"
    if data.get("fill_price") is None or data.get("execution_note") is None:
        return False, f"missing-fill-or-note={data}"
    return True, str(data.get("execution_note") or "")[:120]


def _validate_trade(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict):
        return False, f"status={resp.status_code} body={data}"
    status = str(data.get("status") or "").upper()
    if status not in {"SIMULATED", "SENT_TO_EXCHANGE", "FILLED", "REJECTED"}:
        return False, f"unexpected-status={status}"
    return True, status


def _validate_websearch(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict):
        return False, f"status={resp.status_code} body={data}"
    results = data.get("results")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if not isinstance(results, list):
        return False, f"missing-results={data}"
    return True, f"results={len(results)} status={meta.get('status')}"


def _validate_fetch_url(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code == 200 and isinstance(data, dict) and isinstance(data.get("text"), str):
        return True, f"text={len(str(data.get('text') or ''))}"
    if resp.status_code in {400, 502, 503, 504}:
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("detail") or data.get("error") or "").strip()
        elif isinstance(data, str):
            detail = data[:120]
        return True, f"degraded:{resp.status_code}:{detail[:80]}"
    return False, f"status={resp.status_code} body={data}"


def _validate_ingest_status(resp: Any, data: Any, ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict):
        return False, f"status={resp.status_code} body={data}"
    job_id = str(data.get("job_id") or "").strip()
    if ctx.uploaded_ingest_job_id and job_id and job_id != ctx.uploaded_ingest_job_id:
        return False, f"unexpected-job={job_id}"
    return True, f"job={job_id[:8] if job_id else 'none'}"


def _validate_ingest_jobs(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return False, f"status={resp.status_code} body={data}"
    return True, f"items={len(data.get('items') or [])}"


def _validate_ingest_recent(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict):
        return False, f"status={resp.status_code} body={data}"
    lines = data.get("lines")
    if not isinstance(lines, list):
        return False, f"missing-lines={data}"
    return True, f"lines={len(lines)}"


def _validate_ingest_log(resp: Any, data: Any, _ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        return False, f"status={resp.status_code} body={data}"
    return True, f"lines={len(data.get('lines') or [])}"


def _validate_refresh(resp: Any, data: Any, ctx: e2e.ClientCtx) -> tuple[bool, str]:
    if resp.status_code != 200 or not isinstance(data, dict) or not data.get("cookie_auth"):
        return False, f"status={resp.status_code} body={data}"
    ctx.cookie_auth = True
    return True, "cookie-auth-refreshed"


def _build_seed_requests(ctx: e2e.ClientCtx, *, strict_capabilities: bool, include_image: bool) -> list[Callable[[], bool]]:
    checks: list[Callable[[], bool]] = [
        lambda: e2e.check_health(ctx),
        lambda: e2e.check_auth_token(ctx),
        lambda: e2e.check_chat(ctx),
        lambda: e2e.check_upload_and_ingest(ctx),
        lambda: e2e.check_project_context(ctx),
        lambda: e2e.check_memory_and_speed(ctx),
        lambda: e2e.check_turns_and_ops(ctx),
        lambda: e2e.check_system(ctx),
        lambda: _check_auxiliary_surfaces_soft(ctx),
        lambda: e2e.check_crypto(ctx),
    ]
    if include_image:
        checks.insert(7, lambda: e2e.check_image(ctx))
    if strict_capabilities:
        checks.append(lambda: _check_crypto_evaluate_once(ctx))
    return checks


def _check_auxiliary_surfaces_soft(ctx: e2e.ClientCtx) -> bool:
    ok = True
    r = ctx.request("GET", "/data/health", json_body=None)
    data = _response_json(r)
    if r.status_code == 200 and isinstance(data, dict) and str(data.get("status") or "") == "ok":
        e2e._print_ok("/data/health", f"db={data.get('db')} latency_ms={data.get('latency_ms')}")
    elif r.status_code == 404:
        e2e._print_ok("/data/health", "skipped (router disabled)")
    else:
        e2e._print_fail("/data/health", f"status={r.status_code} body={data}")
        ok = False

    r2 = ctx.request("GET", "/notifications/health", json_body=None)
    data2 = _response_json(r2)
    if r2.status_code == 200 and isinstance(data2, dict) and str(data2.get("status") or "") == "ok":
        e2e._print_ok("/notifications/health", "ok")
    else:
        e2e._print_fail("/notifications/health", f"status={r2.status_code} body={data2}")
        ok = False
    return ok


def _check_crypto_evaluate_once(ctx: e2e.ClientCtx) -> bool:
    if not ctx.uploaded_project_id:
        return True
    r = ctx.request(
        "POST",
        "/crypto/predictions/evaluate",
        json_body=None,
        params={"limit": 20},
    )
    data = _response_json(r)
    if r.status_code == 200 and isinstance(data, dict):
        return True
    e2e._print_fail("crypto/predictions/evaluate", f"status={r.status_code} body={data}")
    return False


def build_stress_plan(ctx: e2e.ClientCtx, *, cloud_ready: bool) -> list[StressSpec]:
    conversation_id = str(ctx.conversation_id or "").strip()
    project_id = str(ctx.uploaded_project_id or "").strip()
    uploaded_path = str(getattr(ctx, "uploaded_path", "") or "").strip()
    ingest_job_id = str(getattr(ctx, "uploaded_ingest_job_id", "") or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id missing")
    if not project_id:
        raise ValueError("uploaded_project_id missing")

    chat_specs: list[StressSpec]
    if cloud_ready:
        chat_specs = [
            StressSpec(
                name="chat_cloud_reasoning",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="Explain in one paragraph why a trade preview matters before sending an order.",
                    conversation_id=conversation_id,
                    mode="chat",
                    synthesize=True,
                ),
                validator=_validate_chat_general,
            ),
            StressSpec(
                name="chat_project_summary",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="what does this project contain?",
                    conversation_id=conversation_id,
                    mode="project",
                    synthesize=False,
                ),
                validator=_validate_chat_project,
            ),
            StressSpec(
                name="chat_crypto_signal",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="BTCUSDT H=2m explain the signal",
                    conversation_id=conversation_id,
                    mode="crypto",
                    synthesize=False,
                ),
                validator=_validate_chat_crypto,
            ),
            StressSpec(
                name="chat_capital",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="what is the capital of japan?",
                    conversation_id=conversation_id,
                    mode="chat",
                    synthesize=False,
                ),
                validator=_validate_chat_capital,
            ),
        ]
    else:
        chat_specs = [
            StressSpec(
                name="chat_time",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="what time is it in new york?",
                    conversation_id=conversation_id,
                    mode="chat",
                    synthesize=False,
                ),
                validator=_validate_chat_general,
            ),
            StressSpec(
                name="chat_capital",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="what is the capital of japan?",
                    conversation_id=conversation_id,
                    mode="chat",
                    synthesize=False,
                ),
                validator=_validate_chat_capital,
            ),
            StressSpec(
                name="chat_project_summary",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="what does this project contain?",
                    conversation_id=conversation_id,
                    mode="project",
                    synthesize=False,
                ),
                validator=_validate_chat_project,
            ),
            StressSpec(
                name="chat_crypto_signal",
                category="chat",
                method="POST",
                path="/chat",
                json_body=_build_chat_payload(
                    message="BTCUSDT H=2m explain the signal",
                    conversation_id=conversation_id,
                    mode="crypto",
                    synthesize=False,
                ),
                validator=_validate_chat_crypto,
            ),
        ]

    specs: list[StressSpec] = [
        StressSpec("system_snapshot", "system", "GET", "/system/snapshot", validator=_validate_dict),
        StressSpec("system_readyz", "system", "GET", "/system/readyz", validator=_validate_dict),
        StressSpec("system_metrics", "system", "GET", "/system/metrics", params={"window_seconds": 900}, validator=_validate_dict),
        StressSpec("system_capabilities", "system", "GET", "/system/capabilities", validator=_validate_dict),
        StressSpec("system_llm_provider", "system", "GET", "/system/llm/provider", validator=_validate_dict),
        StressSpec("system_demo_check", "system", "GET", "/system/demo_check", validator=_validate_dict),
        StressSpec("data_health", "aux", "GET", "/data/health", validator=_validate_data_health_soft),
        StressSpec("notifications_health", "aux", "GET", "/notifications/health", validator=_validate_status_ok),
        StressSpec("chat_list", "chat", "GET", "/chat/list", params={"limit": 40, "include_archived": 1}, validator=_validate_dict),
        StressSpec("chat_state", "chat", "GET", f"/chat/{conversation_id}/state", validator=_validate_dict),
        StressSpec("chat_events", "chat", "GET", f"/chat/{conversation_id}/events", params={"limit": 120}, validator=_validate_dict),
        StressSpec("chat_turns", "chat", "GET", f"/chat/{conversation_id}/turns", params={"limit": 20}, validator=_validate_dict),
        StressSpec("chat_bundle", "chat", "GET", f"/chat/{conversation_id}/bundle", validator=_validate_dict),
        StressSpec("websearch", "web", "GET", "/websearch", params={"q": "latest python release notes", "n": 3, "lang": "en"}, validator=_validate_websearch),
        StressSpec("fetch_url", "url", "POST", "/fetch_url", json_body={"url": "https://example.com"}, validator=_validate_fetch_url),
        *chat_specs,
        StressSpec("files_projects", "files", "GET", "/files/projects", files_scope=True, validator=_validate_dict),
        StressSpec("files_project", "files", "GET", f"/files/projects/{project_id}", params={"lang": "en"}, files_scope=True, validator=_validate_dict),
        StressSpec("files_entrypoints", "files", "GET", f"/files/projects/{project_id}/entrypoints", files_scope=True, validator=_validate_dict),
        StressSpec("files_dependencies", "files", "GET", f"/files/projects/{project_id}/dependencies", files_scope=True, validator=_validate_dict),
        StressSpec("files_configs", "files", "GET", f"/files/projects/{project_id}/configs", files_scope=True, validator=_validate_dict),
        StressSpec("files_architecture", "files", "GET", f"/files/projects/{project_id}/architecture", params={"lang": "en"}, files_scope=True, validator=_validate_dict),
        StressSpec("files_ideas", "files", "GET", f"/files/projects/{project_id}/ideas", files_scope=True, validator=_validate_dict),
        StressSpec("files_intelligence", "files", "GET", f"/files/projects/{project_id}/intelligence", files_scope=True, validator=_validate_dict),
        StressSpec("files_impact", "files", "GET", f"/files/projects/{project_id}/impact", params={"q": "auth"}, files_scope=True, validator=_validate_dict),
        StressSpec("files_symbols", "files", "GET", f"/files/projects/{project_id}/symbols", params={"q": "auth", "limit": 20}, files_scope=True, validator=_validate_dict),
        StressSpec("files_tree", "files", "GET", "/files/tree", params={"project_id": project_id, "max_depth": 3}, files_scope=True, validator=_validate_dict),
        StressSpec("files_content", "files", "GET", "/files/content", params={"project_id": project_id, "path": "app/auth.py"}, files_scope=True, validator=_validate_dict),
        StressSpec("files_av_status", "files", "GET", "/files/av/status", files_scope=True, validator=_validate_dict),
        StressSpec("files_av_recent", "files", "GET", "/files/av/recent", params={"limit": 5}, files_scope=True, validator=_validate_dict),
        StressSpec("files_describe", "files", "GET", "/files/describe", params={"path": uploaded_path, "sample_limit": 30}, files_scope=True, validator=_validate_dict),
        StressSpec("ingest_jobs", "ingest", "GET", "/files/ingest/jobs", params={"limit": 20}, files_scope=True, validator=_validate_ingest_jobs),
        StressSpec("ingest_recent", "ingest", "GET", "/files/ingest/recent", params={"tail": 20}, files_scope=True, validator=_validate_ingest_recent),
        *((
            [
                StressSpec("ingest_status", "ingest", "GET", "/files/ingest/status", params={"job_id": ingest_job_id}, files_scope=True, validator=_validate_ingest_status),
                StressSpec("ingest_log", "ingest", "GET", "/files/ingest/log", params={"job_id": ingest_job_id, "tail": 40}, files_scope=True, validator=_validate_ingest_log),
            ]
            if ingest_job_id
            else []
        )),
        StressSpec("image_generate", "image", "POST", "/image/generate", json_body={
            "prompt": "stress test abstract icon",
            "negative_prompt": "blurry",
            "width": 256,
            "height": 256,
            "steps": 3,
            "cfg": 4.0,
            "seed": 13,
        }, files_scope=True, validator=_validate_dict),
        StressSpec("image_checkpoints", "image", "GET", "/image/checkpoints", files_scope=True, validator=_validate_dict),
        StressSpec("image_recent", "image", "GET", "/image/recent", params={"limit": 5}, files_scope=True, validator=_validate_list),
        StressSpec("crypto_state", "crypto", "GET", "/crypto/state", params={"symbol": "BTCUSDT", "horizon_minutes": 2, "execution_mode": "simulated"}, validator=_validate_dict),
        StressSpec("crypto_predictions", "crypto", "GET", "/crypto/predictions", params={"limit": 10, "symbol": "BTCUSDT", "horizon_minutes": 2}, validator=_validate_list),
        StressSpec("crypto_outcomes", "crypto", "GET", "/crypto/predictions/outcomes", params={"limit": 10, "symbol": "BTCUSDT", "horizon_minutes": 2}, validator=_validate_list),
        StressSpec("crypto_stats", "crypto", "GET", "/crypto/predictions/stats", params={"limit": 20, "symbol": "BTCUSDT", "horizon_minutes": 2}, validator=_validate_dict),
        StressSpec("crypto_thresholds", "crypto", "GET", "/crypto/predictions/thresholds", params={"limit": 200, "symbol": "BTCUSDT", "horizon_minutes": 2}, validator=_validate_dict),
        StressSpec("crypto_credibility", "crypto", "GET", "/crypto/predictions/credibility", params={"symbol": "BTCUSDT", "horizon_minutes": 2}, validator=_validate_dict),
        StressSpec("crypto_policy", "crypto", "GET", "/crypto/policy", params={"symbol": "BTCUSDT", "horizon_minutes": 2}, validator=_validate_dict),
        StressSpec("crypto_leaderboard", "crypto", "GET", "/crypto/predictions/leaderboard", params={"limit": 50, "top_n": 5}, validator=_validate_list),
        StressSpec("crypto_pnl", "crypto", "GET", "/crypto/pnl", params={"limit": 20, "symbol": "BTCUSDT"}, validator=_validate_dict),
        StressSpec("crypto_models", "crypto", "GET", "/crypto/models", validator=_validate_dict),
        StressSpec("crypto_models_registry", "crypto", "GET", "/crypto/models/registry", validator=_validate_list),
        StressSpec("crypto_models_metrics", "crypto", "GET", "/crypto/models/metrics", params={"limit": 50}, validator=_validate_dict),
        StressSpec("crypto_top_coins", "crypto", "GET", "/crypto/top-coins", params={"limit": 10}, validator=_validate_list),
        StressSpec("crypto_preview", "crypto", "POST", "/crypto/trade/preview", json_body={
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.001,
            "execution_mode": "simulated",
            "stop_loss_pct": 0.01,
            "take_profit_pct": 0.02,
            "max_exposure_quote": 10000.0,
            "max_order_notional": 10000.0,
            "max_order_size_pct": 50.0,
            "max_impact_score": 100.0,
            "min_risk_reward": 0.0,
            "max_spread_bps": 1000.0,
            "max_book_consumption_pct": 100.0,
        }, params={"horizon_minutes": 2}, validator=_validate_trade_preview),
        StressSpec("crypto_trade", "crypto", "POST", "/crypto/trade", json_body={
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.001,
            "test": True,
            "execution_mode": "simulated",
            "stop_loss_pct": 0.01,
            "take_profit_pct": 0.02,
            "max_exposure_quote": 10000.0,
            "max_order_notional": 10000.0,
            "max_order_size_pct": 50.0,
            "max_impact_score": 100.0,
            "min_risk_reward": 0.0,
            "max_spread_bps": 1000.0,
            "max_book_consumption_pct": 100.0,
        }, validator=_validate_trade),
        StressSpec("crypto_trades", "crypto", "GET", "/crypto/trades", params={"limit": 20, "symbol": "BTCUSDT"}, validator=_validate_list),
        StressSpec("auth_refresh", "auth", "POST", "/auth/refresh", json_body={}, validator=_validate_refresh),
    ]
    return specs


def run_mixed_stress(ctx: e2e.ClientCtx, *, requests_total: int, cloud_ready: bool, timeout_s: float) -> Dict[str, Any]:
    specs = build_stress_plan(ctx, cloud_ready=cloud_ready)
    if not specs:
        raise RuntimeError("empty stress plan")

    totals: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    latencies: list[float] = []
    failures: list[Dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    for idx in range(max(1, int(requests_total))):
        spec = specs[idx % len(specs)]
        started = time.perf_counter()
        resp = ctx.request(
            spec.method,
            spec.path,
            json_body=spec.json_body,
            params=spec.params,
            files_scope=spec.files_scope,
        )
        elapsed = time.perf_counter() - started
        latencies.append(elapsed)
        status_counts[str(resp.status_code)] += 1

        data = _response_json(resp)
        validator = spec.validator or _validate_dict
        ok, detail = validator(resp, data, ctx)
        totals[spec.name] += 1
        categories[spec.category] += 1
        if not ok:
            failures.append(
                {
                    "i": idx + 1,
                    "name": spec.name,
                    "category": spec.category,
                    "status": resp.status_code,
                    "detail": detail,
                    "path": spec.path,
                }
            )
            if len(failures) >= 20:
                break

    summary = {
        "requests": int(requests_total),
        "executed": sum(categories.values()),
        "cloud_ready": bool(cloud_ready),
        "llm_provider": None,
        "status_counts": dict(status_counts),
        "category_counts": dict(categories),
        "spec_counts": dict(totals),
        "failures": failures,
        "avg_latency_ms": round((sum(latencies) / len(latencies)) * 1000.0, 2) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95) * 1000.0, 2) if latencies else 0.0,
        "max_latency_ms": round(max(latencies) * 1000.0, 2) if latencies else 0.0,
    }
    summary["ok"] = not failures
    if timeout_s > 0:
        summary["budget_s"] = float(timeout_s)
    return summary


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = int(round((pct / 100.0) * (len(ordered) - 1)))
    rank = max(0, min(len(ordered) - 1, rank))
    return float(ordered[rank])


def _prepare_inprocess_env(args: argparse.Namespace) -> None:
    os.environ["AEGIS_DISABLE_DB"] = "1"
    os.environ["AEGIS_LLM_WARMUP"] = "0"
    os.environ.setdefault("AEGIS_IMAGE_TIMEOUT", "3")
    os.environ.setdefault("AEGIS_FAST_MODE", "1")
    os.environ.setdefault("AEGIS_DISABLE_RETRIEVAL", "1")
    os.environ.setdefault("AEGIS_DISABLE_EMBEDDINGS", "1")
    os.environ.setdefault("AEGIS_CLAMAV_STATUS_ON_START", "0")
    os.environ.setdefault("FILES_AV_TIMEOUT", "45")
    os.environ.setdefault("FILES_AV_RETRIES", "2")
    os.environ.setdefault("AEGIS_SEARCH_WARMUP_ON_START", "0")
    os.environ.setdefault("AEGIS_ENABLE_META_API", "0")
    os.environ.setdefault("AEGIS_AUTH_MODE", "on")
    if args.skip_chat:
        os.environ["AEGIS_ENABLE_CHAT_API"] = "0"
    if args.skip_crypto:
        os.environ["AEGIS_ENABLE_CRYPTO_API"] = "0"
    if args.skip_image:
        os.environ["AEGIS_ENABLE_IMAGE_API"] = "0"
    if float(args.timeout) < 90.0:
        args.timeout = 90.0
    if args.api_key:
        os.environ.setdefault("AEGIS_API_KEY", args.api_key)
    if args.files_api_key:
        os.environ.setdefault("FILES_API_KEY", args.files_api_key)


def _run_seed_checks(ctx: e2e.ClientCtx, *, include_image: bool, strict_capabilities: bool) -> bool:
    ok = True
    for fn in _build_seed_requests(ctx, strict_capabilities=strict_capabilities, include_image=include_image):
        try:
            ok = fn() and ok
        except Exception as exc:  # noqa: BLE001
            e2e._print_fail(fn.__name__, str(exc))
            ok = False
    return ok


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mixed front/back stress check")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--api-key", default="")
    p.add_argument("--files-api-key", default="")
    p.add_argument("--timeout", type=float, default=45.0)
    p.add_argument("--requests", type=int, default=900, help="How many mixed requests to send in the stress phase.")
    p.add_argument("--skip-chat", action="store_true")
    p.add_argument("--skip-crypto", action="store_true")
    p.add_argument("--skip-image", action="store_true")
    p.add_argument("--inprocess", action="store_true", help="Run against an ephemeral local uvicorn (no TCP bind in the caller).")
    p.add_argument("--strict-capabilities", action="store_true")
    p.add_argument("--keep-artifacts", action="store_true")
    return p.parse_args()


def _run_ephemeral_inprocess(args: argparse.Namespace) -> int:
    _prepare_inprocess_env(args)
    try:
        port = _pick_free_port()
    except PermissionError:
        print(json.dumps({"ok": False, "error": "inprocess-sandbox-no-sockets"}, ensure_ascii=False))
        return 1

    base_url = f"http://127.0.0.1:{port}"
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd, env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_ready(f"{base_url}/healthz", timeout_s=min(30.0, float(args.timeout) + 5.0)):
            print(json.dumps({"ok": False, "error": "inprocess-uvicorn-not-ready"}, ensure_ascii=False))
            return 1
        return _run_checks(args, base_url=base_url)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _crypto_cleanup(ctx: e2e.ClientCtx) -> None:
    if not ctx.uploaded_project_id and not ctx.conversation_id:
        return
    try:
        r = ctx.request("DELETE", "/crypto/trades", json_body=None)
        if r.status_code == 200:
            e2e._print_ok("cleanup-crypto/trades", "ok")
        else:
            e2e._print_fail("cleanup-crypto/trades", f"status={r.status_code} body={_response_json(r)}")
    except Exception as exc:  # noqa: BLE001
        e2e._print_fail("cleanup-crypto/trades", str(exc))
    try:
        r = ctx.request("DELETE", "/crypto/predictions", json_body=None)
        if r.status_code == 200:
            e2e._print_ok("cleanup-crypto/predictions", "ok")
        else:
            e2e._print_fail("cleanup-crypto/predictions", f"status={r.status_code} body={_response_json(r)}")
    except Exception as exc:  # noqa: BLE001
        e2e._print_fail("cleanup-crypto/predictions", str(exc))


def _run_checks(args: argparse.Namespace, *, base_url: str) -> int:
    ctx = e2e.ClientCtx(
        base_url=base_url,
        timeout=float(args.timeout),
        api_key=(args.api_key or "").strip(),
        files_api_key=(args.files_api_key or args.api_key or "").strip(),
        transport=e2e.RequestsTransport(),
        strict_capabilities=bool(args.strict_capabilities),
        cleanup_artifacts=not bool(args.keep_artifacts),
    )

    ok = _run_seed_checks(ctx, include_image=not bool(args.skip_image), strict_capabilities=bool(args.strict_capabilities))
    if not ok:
        _crypto_cleanup(ctx)
        e2e.cleanup(ctx)
        print(json.dumps({"ok": False, "stage": "seed"}, ensure_ascii=False))
        return 1

    snapshot_resp = ctx.request("GET", "/system/snapshot", json_body=None)
    snapshot = _response_json(snapshot_resp)
    llm_config = {}
    if isinstance(snapshot, dict):
        resources = snapshot.get("resources") if isinstance(snapshot.get("resources"), dict) else {}
        llm_config = resources.get("llm_config") if isinstance(resources.get("llm_config"), dict) else {}
    cloud_ready = bool(llm_config.get("remote_ready")) and str(llm_config.get("effective_provider") or llm_config.get("provider") or "").strip().lower() in {"auto", "groq"}

    # Pull a turn id once so the detail endpoint is exercised too.
    try:
        turns_resp = ctx.request("GET", f"/chat/{ctx.conversation_id}/turns", json_body=None)
        turns_data = _response_json(turns_resp)
        if isinstance(turns_data, dict):
            turns = turns_data.get("items") if isinstance(turns_data.get("items"), list) else []
            if turns:
                turn_id = str((turns[-1] or {}).get("turn_id") or (turns[-1] or {}).get("id") or "").strip()
                if turn_id:
                    turn_detail_resp = ctx.request("GET", f"/chat/{ctx.conversation_id}/turns/{turn_id}", json_body=None)
                    turn_detail_data = _response_json(turn_detail_resp)
                    if turn_detail_resp.status_code == 200 and isinstance(turn_detail_data, dict):
                        e2e._print_ok("chat/turn-detail", turn_id[:8])
                    else:
                        e2e._print_fail("chat/turn-detail", f"status={turn_detail_resp.status_code} body={turn_detail_data}")
    except Exception as exc:  # noqa: BLE001
        e2e._print_fail("chat/turn-detail", str(exc))

    # Exercise crypto prediction evaluation and a single preview/predict path once before the large loop.
    try:
        predict_resp = ctx.request(
            "POST",
            "/crypto/predict",
            json_body={
                "symbol": "BTCUSDT",
                "horizon_minutes": 2,
                "model": "ensemble",
                "save": False,
                "require_trained": False,
            },
        )
        predict_data = _response_json(predict_resp)
        if predict_resp.status_code == 200 and isinstance(predict_data, dict):
            e2e._print_ok("crypto/predict", f"decision={predict_data.get('decision')}")
        else:
            e2e._print_fail("crypto/predict", f"status={predict_resp.status_code} body={predict_data}")
            ok = False
    except Exception as exc:  # noqa: BLE001
        e2e._print_fail("crypto/predict", str(exc))
        ok = False

    try:
        eval_resp = ctx.request("POST", "/crypto/predictions/evaluate", json_body=None, params={"limit": 20})
        eval_data = _response_json(eval_resp)
        if eval_resp.status_code == 200 and isinstance(eval_data, dict):
            e2e._print_ok("crypto/predictions/evaluate", str(eval_data.get("ok", True)))
        else:
            e2e._print_fail("crypto/predictions/evaluate", f"status={eval_resp.status_code} body={eval_data}")
            ok = False
    except Exception as exc:  # noqa: BLE001
        e2e._print_fail("crypto/predictions/evaluate", str(exc))
        ok = False

    stress = run_mixed_stress(
        ctx,
        requests_total=max(1, int(args.requests)),
        cloud_ready=cloud_ready,
        timeout_s=float(args.timeout),
    )
    e2e._print_ok(
        "stress",
        f"requests={stress.get('executed')} cloud={int(bool(cloud_ready))} p95_ms={stress.get('p95_latency_ms')}",
    )
    if stress.get("failures"):
        ok = False
        for item in stress["failures"][:10]:
            e2e._print_fail(
                "stress-item",
                f"{item.get('i')} {item.get('category')} {item.get('name')} status={item.get('status')} {item.get('detail')}",
            )

    _crypto_cleanup(ctx)
    e2e.cleanup(ctx)

    payload = {
        "ok": bool(ok and stress.get("ok")),
        "stress": stress,
        "cloud_ready": cloud_ready,
        "base_url": base_url,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def main() -> int:
    args = parse_args()
    if args.inprocess:
        return _run_ephemeral_inprocess(args)
    return _run_checks(args, base_url=args.base_url)


if __name__ == "__main__":
    sys.exit(main())
