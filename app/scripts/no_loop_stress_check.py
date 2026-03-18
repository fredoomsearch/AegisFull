#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from collections import Counter
from typing import Any, Dict, List

import requests

_ALLOWED_STOP_REASONS = {
    "plan_satisfied",
    "no_tool_candidates",
    "budget_exhausted",
    "no_new_evidence_after_web",
    "max_iterations_reached",
    "error",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="No-loop stress gate for agent runtime.")
    p.add_argument("--base-url", required=True)
    p.add_argument("--api-key", default=os.getenv("AEGIS_API_KEY", ""))
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--request-timeout", type=int, default=45)
    p.add_argument("--max-seconds-per-run", type=float, default=35.0)
    p.add_argument("--max-iterations", type=int, default=3)
    p.add_argument("--max-total-tool-calls", type=int, default=8)
    p.add_argument("--max-failures", type=int, default=0)
    p.add_argument(
        "--auth-edge-every",
        type=int,
        default=0,
        help="Inject an invalid API key every N runs (0 disables this edge-path check).",
    )
    p.add_argument(
        "--auth-edge-invalid-key",
        default="invalid-no-loop-key",
        help="Invalid key used for auth edge injections.",
    )
    p.add_argument(
        "--max-auth-edge-unexpected-failures",
        type=int,
        default=0,
        help="Allowed non-401/403 failures during auth-edge injected runs.",
    )
    p.add_argument("--output-json", default="")
    return p.parse_args()


def _post_json(
    url: str,
    payload: Dict[str, Any],
    *,
    headers: Dict[str, str],
    timeout: int,
) -> Dict[str, Any]:
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"POST {url} status={resp.status_code} body={(resp.text or '')[:300]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"POST {url} returned non-object JSON")
    return data


def run_no_loop_stress(
    *,
    base_url: str,
    api_key: str = "",
    runs: int = 10,
    request_timeout: int = 45,
    max_seconds_per_run: float = 35.0,
    max_iterations: int = 3,
    max_total_tool_calls: int = 8,
    max_failures: int = 0,
    auth_edge_every: int = 0,
    auth_edge_invalid_key: str = "invalid-no-loop-key",
    max_auth_edge_unexpected_failures: int = 0,
) -> Dict[str, Any]:
    headers = {"X-API-Key": api_key} if api_key else {}
    base = str(base_url or "").rstrip("/")
    total_runs = max(1, int(runs))
    max_it = max(1, int(max_iterations))
    max_calls = max(1, int(max_total_tool_calls))
    auth_edge_interval = max(0, int(auth_edge_every))

    prompts: List[Dict[str, Any]] = [
        {"message": "hello", "use_web": False},
        {"message": "show clamav status and show last ingest log", "use_web": False},
        {"message": "latest angular login docs", "use_web": True},
        {"message": "where is russia?", "use_web": True},
        {"message": "what files are in this project?", "use_web": False},
    ]

    failures: List[Dict[str, Any]] = []
    elapsed_values: List[float] = []
    stop_reasons: Counter[str] = Counter()
    auth_edge_runs = 0
    auth_edge_unauthorized = 0
    auth_edge_unexpected_failures = 0

    for idx in range(total_runs):
        item = prompts[idx % len(prompts)]
        conv_id = str(uuid.uuid4())
        run_index = idx + 1
        use_auth_edge = bool(auth_edge_interval and (run_index % auth_edge_interval == 0))
        call_headers = dict(headers)
        if use_auth_edge:
            auth_edge_runs += 1
            if str(auth_edge_invalid_key or "").strip():
                call_headers["X-API-Key"] = str(auth_edge_invalid_key).strip()
            elif "X-API-Key" in call_headers:
                del call_headers["X-API-Key"]
        payload = {
            "message": str(item["message"]),
            "use_web": bool(item["use_web"]),
            "max_iterations": max_it,
            "max_total_tool_calls": max_calls,
            "max_tool_retries": 2,
            "tool_retry_backoff_ms": 50,
            "synthesize": False,
            "lang": "en",
        }
        started = time.perf_counter()
        fail_detail: Dict[str, Any] | None = None
        try:
            data = _post_json(
                f"{base}/chat/{conv_id}/agent_run",
                payload,
                headers=call_headers,
                timeout=max(10, int(request_timeout)),
            )
            if use_auth_edge:
                fail_detail = {
                    "kind": "auth_edge_unexpected_success",
                    "status": "expected_401_or_403",
                }
                data = {}
            elapsed_s = time.perf_counter() - started
            elapsed_values.append(elapsed_s)

            if use_auth_edge:
                pass
            elif elapsed_s > float(max_seconds_per_run):
                fail_detail = {
                    "kind": "slow_run",
                    "elapsed_s": elapsed_s,
                    "max_seconds_per_run": float(max_seconds_per_run),
                }
            else:
                iterations = data.get("iterations")
                if not isinstance(iterations, list):
                    fail_detail = {"kind": "missing_iterations", "payload_keys": sorted(list(data.keys()))[:20]}
                else:
                    iterations_completed = int(data.get("iterations_completed") or len(iterations))
                    total_tool_calls = int(data.get("total_tool_calls") or 0)
                    stop_reason = str(data.get("stop_reason") or "").strip().lower()
                    stop_reasons[stop_reason or "missing"] += 1
                    if not bool(data.get("ok")):
                        fail_detail = {"kind": "run_not_ok", "stop_reason": stop_reason}
                    elif iterations_completed > max_it:
                        fail_detail = {
                            "kind": "iterations_budget_exceeded",
                            "iterations_completed": iterations_completed,
                            "max_iterations": max_it,
                        }
                    elif len(iterations) > max_it:
                        fail_detail = {
                            "kind": "iterations_list_exceeded",
                            "iterations_len": len(iterations),
                            "max_iterations": max_it,
                        }
                    elif total_tool_calls > max_calls:
                        fail_detail = {
                            "kind": "tool_budget_exceeded",
                            "total_tool_calls": total_tool_calls,
                            "max_total_tool_calls": max_calls,
                        }
                    elif not stop_reason:
                        fail_detail = {"kind": "missing_stop_reason"}
                    elif stop_reason not in _ALLOWED_STOP_REASONS:
                        fail_detail = {"kind": "unexpected_stop_reason", "stop_reason": stop_reason}
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            if use_auth_edge and ("status=401" in err or "status=403" in err):
                auth_edge_unauthorized += 1
                fail_detail = None
            else:
                if use_auth_edge:
                    auth_edge_unexpected_failures += 1
                    fail_detail = {"kind": "auth_edge_exception", "error": err}
                else:
                    fail_detail = {"kind": "exception", "error": err}

        if fail_detail:
            failures.append(
                {
                    "run": run_index,
                    "prompt": str(item["message"]),
                    "detail": fail_detail,
                }
            )
            if len(failures) > max(0, int(max_failures)):
                # Keep running to collect enough signal, but we already know gate will fail.
                pass

    max_elapsed = max(elapsed_values) if elapsed_values else 0.0
    avg_elapsed = (sum(elapsed_values) / float(len(elapsed_values))) if elapsed_values else 0.0
    ok = (
        len(failures) <= max(0, int(max_failures))
        and auth_edge_unexpected_failures <= max(0, int(max_auth_edge_unexpected_failures))
    )

    return {
        "ok": ok,
        "runs": total_runs,
        "max_failures": int(max_failures),
        "failed_runs": len(failures),
        "failures": failures[:30],
        "auth_edge": {
            "enabled": bool(auth_edge_interval),
            "every": auth_edge_interval,
            "runs": auth_edge_runs,
            "unauthorized": auth_edge_unauthorized,
            "unexpected_failures": auth_edge_unexpected_failures,
            "max_unexpected_failures": int(max_auth_edge_unexpected_failures),
        },
        "summary": {
            "stop_reason_counts": dict(stop_reasons),
            "max_elapsed_s": max_elapsed,
            "avg_elapsed_s": avg_elapsed,
            "max_iterations": max_it,
            "max_total_tool_calls": max_calls,
        },
    }


def main() -> int:
    args = parse_args()
    payload = run_no_loop_stress(
        base_url=args.base_url,
        api_key=args.api_key,
        runs=args.runs,
        request_timeout=args.request_timeout,
        max_seconds_per_run=args.max_seconds_per_run,
        max_iterations=args.max_iterations,
        max_total_tool_calls=args.max_total_tool_calls,
        max_failures=args.max_failures,
        auth_edge_every=args.auth_edge_every,
        auth_edge_invalid_key=args.auth_edge_invalid_key,
        max_auth_edge_unexpected_failures=args.max_auth_edge_unexpected_failures,
    )
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if bool(payload.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
