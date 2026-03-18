#!/usr/bin/env python3
from __future__ import annotations

"""
Hard-contract release gate evaluator.

Why this module exists:
- Aggregate adversarial, runtime-metrics, soak, and no-loop checks into one gate.
- Emit machine-readable go/no-go payload for strict startup and release pipelines.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict

import requests

from app.scripts.adversarial_eval_check import run_adversarial_eval_cases
from app.scripts.no_loop_stress_check import run_no_loop_stress
from app.scripts.soak_gate import run_soak_gate


def _run_adversarial(min_cases: int) -> Dict[str, Any]:
    result = run_adversarial_eval_cases(min_cases=min_cases)
    wrong_route_rate = 1.0
    total = int(result.get("total") or 0)
    passed = int(result.get("passed") or 0)
    if total > 0:
        wrong_route_rate = float(total - passed) / float(total)
    return {
        "ok": bool(result.get("ok")),
        "result": result,
        "wrong_route_rate": wrong_route_rate,
    }


def _fetch_runtime_metrics(base_url: str, api_key: str, window_seconds: int) -> Dict[str, Any]:
    headers = {"X-API-Key": api_key} if api_key else {}
    url = f"{base_url.rstrip('/')}/system/metrics"
    resp = requests.get(url, headers=headers, params={"window_seconds": window_seconds}, timeout=12)
    if resp.status_code != 200:
        raise RuntimeError(f"/system/metrics status={resp.status_code} body={(resp.text or '')[:300]}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("/system/metrics returned non-object JSON")
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hard contract release gate.")
    p.add_argument("--base-url", default="")
    p.add_argument("--api-key", default=os.getenv("AEGIS_API_KEY", ""))
    p.add_argument("--min-cases", type=int, default=500)
    p.add_argument("--window-seconds", type=int, default=900)
    p.add_argument(
        "--max-wrong-route-rate",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_MAX_WRONG_ROUTE_RATE", "0.005")),
    )
    p.add_argument(
        "--max-safety-fallback-rate",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_MAX_SAFETY_FALLBACK_RATE", "0.03")),
    )
    p.add_argument(
        "--max-poll-401-rate",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_MAX_POLL_401_RATE", "0.02")),
    )
    p.add_argument(
        "--max-ambiguous-route-rate",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_MAX_AMBIGUOUS_ROUTE_RATE", "0.5")),
    )
    p.add_argument(
        "--max-low-confidence-route-rate",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_MAX_LOW_CONFIDENCE_ROUTE_RATE", "0.75")),
    )
    p.add_argument(
        "--run-soak",
        action="store_true",
        help="Run the soak gate as part of this hard contract check.",
    )
    p.add_argument(
        "--soak-duration-hours",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_SOAK_HOURS", "0.001")),
        help="Soak run duration in hours (strict defaults to a short mandatory run).",
    )
    p.add_argument(
        "--soak-interval-seconds",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_SOAK_INTERVAL_SECONDS", "1.5")),
        help="Delay between soak ticks.",
    )
    p.add_argument(
        "--soak-window-seconds",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_WINDOW_SECONDS", "900")),
        help="Metrics window for soak checks.",
    )
    p.add_argument(
        "--max-transport-failures",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_MAX_TRANSPORT_FAILURES", "0")),
        help="Allowed failed soak ticks after retry budget.",
    )
    p.add_argument(
        "--soak-attempts-per-tick",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_ATTEMPTS_PER_TICK", "2")),
        help="Transport attempts per soak tick before counting a failure.",
    )
    p.add_argument(
        "--soak-chat-timeout-seconds",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_CHAT_TIMEOUT_SECONDS", "20")),
        help="Timeout for each soak /chat call.",
    )
    p.add_argument(
        "--soak-min-route-checked",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_MIN_ROUTE_CHECKED", "1")),
        help="Minimum successful route checks required for soak coverage.",
    )
    p.add_argument(
        "--soak-startup-transport-grace",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_STARTUP_TRANSPORT_GRACE", "2")),
        help="Ignore up to N failed soak ticks before first successful route check.",
    )
    p.add_argument(
        "--soak-min-route-attempt-ticks",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_MIN_ROUTE_ATTEMPT_TICKS", "5")),
        help="Minimum soak ticks to attempt while route coverage is still unmet.",
    )
    p.add_argument(
        "--run-no-loop",
        action="store_true",
        help="Run no-loop stress gate as part of this hard contract check.",
    )
    p.add_argument(
        "--no-loop-runs",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_NO_LOOP_RUNS", "8")),
        help="How many agent_run calls to execute in no-loop stress.",
    )
    p.add_argument(
        "--no-loop-request-timeout",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_NO_LOOP_REQUEST_TIMEOUT", "45")),
        help="HTTP timeout for each no-loop stress run.",
    )
    p.add_argument(
        "--no-loop-max-seconds-per-run",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_NO_LOOP_MAX_SECONDS", "35")),
        help="Upper bound latency per agent run.",
    )
    p.add_argument(
        "--max-no-loop-failures",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_MAX_NO_LOOP_FAILURES", "0")),
        help="Allowed failing runs in no-loop stress (strict should stay 0).",
    )
    p.add_argument(
        "--no-loop-auth-edge-every",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_EVERY", "0")),
        help="Inject invalid API key every N no-loop runs (0 disables auth-edge scenario).",
    )
    p.add_argument(
        "--no-loop-auth-edge-invalid-key",
        default=os.getenv("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_INVALID_KEY", "invalid-no-loop-key"),
        help="Invalid API key value used by auth-edge injections.",
    )
    p.add_argument(
        "--max-no-loop-auth-edge-unexpected-failures",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_MAX_NO_LOOP_AUTH_EDGE_UNEXPECTED", "0")),
        help="Allowed unexpected non-401/403 failures in no-loop auth-edge runs.",
    )
    p.add_argument("--strict", action="store_true")
    return p.parse_args()


def main() -> int:
    """
    What it does:
    - Evaluates release hard-contract checks and returns pass/fail status.

    Why it exists:
    - Enforce measurable reliability gates before promotion.

    Called from ->
    - startup/verify scripts and strict gate automation

    Calls ->
    - adversarial evals, runtime metrics fetch, optional soak gate,
      optional no-loop stress checks

    Failure/guard behavior:
    - Emits full structured result payload and exits non-zero on any failed gate.
    """
    args = parse_args()
    checks: Dict[str, Any] = {}
    strict_mode = bool(args.strict)
    run_soak = bool(args.run_soak or strict_mode)
    run_no_loop = bool(args.run_no_loop or strict_mode)

    adversarial = _run_adversarial(min_cases=max(1, int(args.min_cases)))
    checks["adversarial"] = adversarial
    checks["wrong_route_threshold"] = {
        "value": adversarial["wrong_route_rate"],
        "max": float(args.max_wrong_route_rate),
        "ok": bool(adversarial["wrong_route_rate"] <= float(args.max_wrong_route_rate)),
    }

    metrics_payload: Dict[str, Any] = {}
    if str(args.base_url or "").strip():
        try:
            metrics_payload = _fetch_runtime_metrics(
                base_url=args.base_url,
                api_key=args.api_key,
                window_seconds=max(60, int(args.window_seconds)),
            )
            rates = dict(metrics_payload.get("rates") or {})
            safety_rate = float(rates.get("safety_fallback_rate") or 0.0)
            poll_401_rate = float(rates.get("poll_401_rate") or 0.0)
            ambiguous_route_rate = float(rates.get("ambiguous_route_rate") or 0.0)
            low_confidence_route_rate = float(rates.get("low_confidence_route_rate") or 0.0)
            checks["runtime_metrics"] = {
                "ok": True,
                "rates": rates,
                "window_seconds": metrics_payload.get("window_seconds"),
            }
            checks["safety_fallback_threshold"] = {
                "value": safety_rate,
                "max": float(args.max_safety_fallback_rate),
                "ok": bool(safety_rate <= float(args.max_safety_fallback_rate)),
            }
            checks["poll_401_threshold"] = {
                "value": poll_401_rate,
                "max": float(args.max_poll_401_rate),
                "ok": bool(poll_401_rate <= float(args.max_poll_401_rate)),
            }
            checks["ambiguous_route_threshold"] = {
                "value": ambiguous_route_rate,
                "max": float(args.max_ambiguous_route_rate),
                "ok": bool(ambiguous_route_rate <= float(args.max_ambiguous_route_rate)),
            }
            checks["low_confidence_route_threshold"] = {
                "value": low_confidence_route_rate,
                "max": float(args.max_low_confidence_route_rate),
                "ok": bool(low_confidence_route_rate <= float(args.max_low_confidence_route_rate)),
            }
        except Exception as exc:  # noqa: BLE001
            checks["runtime_metrics"] = {"ok": False, "error": str(exc)}
            checks["safety_fallback_threshold"] = {
                "value": None,
                "max": float(args.max_safety_fallback_rate),
                "ok": not strict_mode,
            }
            checks["poll_401_threshold"] = {
                "value": None,
                "max": float(args.max_poll_401_rate),
                "ok": not strict_mode,
            }
            checks["ambiguous_route_threshold"] = {
                "value": None,
                "max": float(args.max_ambiguous_route_rate),
                "ok": not strict_mode,
            }
            checks["low_confidence_route_threshold"] = {
                "value": None,
                "max": float(args.max_low_confidence_route_rate),
                "ok": not strict_mode,
            }
    else:
        missing_base_url = {
            "ok": not strict_mode,
            "skipped": "missing-base-url",
        }
        if strict_mode:
            missing_base_url["error"] = "strict mode requires --base-url to validate runtime metrics"
        checks["runtime_metrics"] = missing_base_url
        checks["safety_fallback_threshold"] = {
            "value": None,
            "max": float(args.max_safety_fallback_rate),
            "ok": not strict_mode,
        }
        checks["poll_401_threshold"] = {
            "value": None,
            "max": float(args.max_poll_401_rate),
            "ok": not strict_mode,
        }
        checks["ambiguous_route_threshold"] = {
            "value": None,
            "max": float(args.max_ambiguous_route_rate),
            "ok": not strict_mode,
        }
        checks["low_confidence_route_threshold"] = {
            "value": None,
            "max": float(args.max_low_confidence_route_rate),
            "ok": not strict_mode,
        }

    if run_soak:
        if str(args.base_url or "").strip():
            try:
                soak_payload = run_soak_gate(
                    base_url=args.base_url,
                    api_key=args.api_key,
                    duration_hours=max(0.001, float(args.soak_duration_hours)),
                    interval_seconds=max(0.1, float(args.soak_interval_seconds)),
                    window_seconds=max(60, int(args.soak_window_seconds)),
                    max_wrong_route_rate=float(args.max_wrong_route_rate),
                    max_safety_fallback_rate=float(args.max_safety_fallback_rate),
                    max_poll_401_rate=float(args.max_poll_401_rate),
                    max_transport_failures=max(0, int(args.max_transport_failures)),
                    attempts_per_tick=max(1, int(args.soak_attempts_per_tick)),
                    chat_timeout_seconds=max(5, int(args.soak_chat_timeout_seconds)),
                    min_route_checked=max(1, int(args.soak_min_route_checked)),
                    startup_transport_grace=max(0, int(args.soak_startup_transport_grace)),
                    min_route_attempt_ticks=max(1, int(args.soak_min_route_attempt_ticks)),
                )
                checks["soak_gate"] = {
                    "ok": bool(soak_payload.get("ok")),
                    "ticks": soak_payload.get("ticks"),
                    "route_checked": soak_payload.get("route_checked"),
                    "failures": soak_payload.get("failures"),
                    "checks": soak_payload.get("checks"),
                }
            except Exception as exc:  # noqa: BLE001
                checks["soak_gate"] = {
                    "ok": False if strict_mode else True,
                    "error": str(exc),
                }
        else:
            missing_soak = {
                "ok": not strict_mode,
                "skipped": "missing-base-url",
            }
            if strict_mode:
                missing_soak["error"] = "strict mode requires --base-url to run soak gate"
            checks["soak_gate"] = missing_soak
    else:
        checks["soak_gate"] = {"ok": True, "skipped": "disabled"}

    if run_no_loop:
        if str(args.base_url or "").strip():
            try:
                no_loop_payload = run_no_loop_stress(
                    base_url=args.base_url,
                    api_key=args.api_key,
                    runs=max(1, int(args.no_loop_runs)),
                    request_timeout=max(5, int(args.no_loop_request_timeout)),
                    max_seconds_per_run=max(1.0, float(args.no_loop_max_seconds_per_run)),
                    max_iterations=3,
                    max_total_tool_calls=8,
                    max_failures=max(0, int(args.max_no_loop_failures)),
                    auth_edge_every=max(0, int(args.no_loop_auth_edge_every)),
                    auth_edge_invalid_key=str(args.no_loop_auth_edge_invalid_key or "").strip(),
                    max_auth_edge_unexpected_failures=max(0, int(args.max_no_loop_auth_edge_unexpected_failures)),
                )
                checks["no_loop_stress"] = {
                    "ok": bool(no_loop_payload.get("ok")),
                    "runs": no_loop_payload.get("runs"),
                    "failed_runs": no_loop_payload.get("failed_runs"),
                    "max_failures": no_loop_payload.get("max_failures"),
                    "summary": no_loop_payload.get("summary"),
                    "auth_edge": no_loop_payload.get("auth_edge"),
                }
            except Exception as exc:  # noqa: BLE001
                checks["no_loop_stress"] = {
                    "ok": False if strict_mode else True,
                    "error": str(exc),
                }
        else:
            missing_no_loop = {
                "ok": not strict_mode,
                "skipped": "missing-base-url",
            }
            if strict_mode:
                missing_no_loop["error"] = "strict mode requires --base-url to run no-loop stress gate"
            checks["no_loop_stress"] = missing_no_loop
    else:
        checks["no_loop_stress"] = {"ok": True, "skipped": "disabled"}

    all_ok = all(bool(v.get("ok")) for v in checks.values() if isinstance(v, dict) and "ok" in v)
    payload = {"ok": all_ok, "checks": checks}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
