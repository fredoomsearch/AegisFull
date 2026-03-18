#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any, Dict, List

import requests


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Soak reliability gate (traffic + threshold checks).")
    p.add_argument("--base-url", required=True)
    p.add_argument("--api-key", default=os.getenv("AEGIS_API_KEY", ""))
    p.add_argument("--duration-hours", type=float, default=72.0)
    p.add_argument("--interval-seconds", type=float, default=5.0)
    p.add_argument("--window-seconds", type=int, default=900)
    p.add_argument("--max-wrong-route-rate", type=float, default=0.005)
    p.add_argument("--max-safety-fallback-rate", type=float, default=0.03)
    p.add_argument("--max-poll-401-rate", type=float, default=0.02)
    p.add_argument(
        "--max-transport-failures",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_MAX_TRANSPORT_FAILURES", "0")),
        help="Allowed failed soak ticks after retry budget.",
    )
    p.add_argument(
        "--attempts-per-tick",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_ATTEMPTS_PER_TICK", "2")),
        help="Transport attempts per soak tick before counting a failure.",
    )
    p.add_argument(
        "--chat-timeout-seconds",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_CHAT_TIMEOUT_SECONDS", "45")),
        help="Timeout for each soak /chat request.",
    )
    p.add_argument(
        "--min-route-checked",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_MIN_ROUTE_CHECKED", "1")),
        help="Minimum successful route checks required.",
    )
    p.add_argument(
        "--startup-transport-grace",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_STARTUP_TRANSPORT_GRACE", "1")),
        help="Ignore up to N failed ticks before first successful route check.",
    )
    p.add_argument(
        "--min-route-attempt-ticks",
        type=int,
        default=int(os.getenv("AEGIS_CONTRACT_SOAK_MIN_ROUTE_ATTEMPT_TICKS", "3")),
        help="Minimum ticks to attempt while route coverage is still unmet.",
    )
    p.add_argument("--output-json", default="")
    return p.parse_args()


def _get_json(url: str, *, headers: Dict[str, str] | None = None, timeout: int = 10) -> Dict[str, Any]:
    resp = requests.get(url, headers=headers or {}, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"GET {url} status={resp.status_code} body={(resp.text or '')[:300]}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {url} returned non-object JSON")
    return payload


def _post_json(url: str, payload: Dict[str, Any], *, headers: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"POST {url} status={resp.status_code} body={(resp.text or '')[:300]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"POST {url} returned non-object JSON")
    return data


def run_soak_gate(
    *,
    base_url: str,
    api_key: str = "",
    duration_hours: float = 72.0,
    interval_seconds: float = 5.0,
    window_seconds: int = 900,
    max_wrong_route_rate: float = 0.005,
    max_safety_fallback_rate: float = 0.03,
    max_poll_401_rate: float = 0.02,
    max_transport_failures: int = 0,
    attempts_per_tick: int = 2,
    chat_timeout_seconds: int = 45,
    min_route_checked: int = 1,
    startup_transport_grace: int = 1,
    min_route_attempt_ticks: int = 3,
) -> Dict[str, Any]:
    headers = {"X-API-Key": api_key} if api_key else {}
    base = str(base_url or "").rstrip("/")

    prompts: List[str] = [
        "web: where is russia?",
        "web: latest python 3.12 release notes",
        "web: what is the capital of japan?",
        "web: current bitcoin market summary",
    ]

    deadline = time.time() + max(0.01, float(duration_hours)) * 3600.0
    ticks = 0
    failures = 0
    wrong_route = 0
    route_checked = 0
    conv_id = str(uuid.uuid4())
    recent_errors: List[str] = []
    per_tick_attempts = max(1, int(attempts_per_tick))
    route_checked_min = max(1, int(min_route_checked))
    allowed_transport_failures = max(0, int(max_transport_failures))
    chat_timeout = max(5, int(chat_timeout_seconds))
    startup_grace_remaining = max(0, int(startup_transport_grace))
    min_attempt_ticks = max(1, int(min_route_attempt_ticks))
    startup_warnings: List[str] = []
    # Keep route coverage deterministic in short strict runs by forcing a small
    # minimum number of attempts while coverage is still missing.
    max_route_attempt_ticks = max(min_attempt_ticks, route_checked_min * 3)

    while time.time() < deadline or (route_checked < route_checked_min and ticks < max_route_attempt_ticks):
        prompt = prompts[ticks % len(prompts)]
        ticks += 1
        last_exc: Exception | None = None
        tick_ok = False
        for attempt_idx in range(per_tick_attempts):
            try:
                _get_json(f"{base}/healthz", timeout=8)
                _get_json(f"{base}/system/readyz", headers=headers, timeout=12)
                # Keep soak chat fast and deterministic; we are validating route behavior, not long synthesis.
                chat_payload = {
                    "conversation_id": conv_id,
                    "message": prompt,
                    "lang": "en",
                    "mode": "chat",
                    "use_web": True,
                    "synthesize": False,
                    "max_iterations": 1,
                    "max_total_tool_calls": 2,
                    "max_tool_retries": 1,
                    "tool_retry_backoff_ms": 25,
                }
                chat_resp = _post_json(f"{base}/chat", chat_payload, headers=headers, timeout=chat_timeout)
                ctx = dict(chat_resp.get("context") or {})
                route_checked += 1
                if str(ctx.get("source_plan") or "").strip().lower() != "web_only":
                    wrong_route += 1
                tick_ok = True
                break
            except Exception as exc:
                last_exc = exc
                if attempt_idx + 1 < per_tick_attempts:
                    time.sleep(0.15)
        if not tick_ok:
            if route_checked < route_checked_min and startup_grace_remaining > 0:
                startup_grace_remaining -= 1
                if last_exc is not None and len(startup_warnings) < 5:
                    startup_warnings.append(str(last_exc)[:280])
            else:
                failures += 1
                if last_exc is not None and len(recent_errors) < 5:
                    recent_errors.append(str(last_exc)[:280])
        time.sleep(max(0.1, float(interval_seconds)))

    metrics = _get_json(
        f"{base}/system/metrics",
        headers=headers,
        timeout=12,
    )
    rates = dict(metrics.get("rates") or {})
    wrong_route_rate = float(wrong_route) / float(max(1, route_checked))
    safety_fallback_rate = float(rates.get("safety_fallback_rate") or 0.0)
    poll_401_rate = float(rates.get("poll_401_rate") or 0.0)

    checks = {
        "wrong_route": {
            "value": wrong_route_rate,
            "max": float(max_wrong_route_rate),
            "ok": wrong_route_rate <= float(max_wrong_route_rate),
        },
        "safety_fallback": {
            "value": safety_fallback_rate,
            "max": float(max_safety_fallback_rate),
            "ok": safety_fallback_rate <= float(max_safety_fallback_rate),
        },
        "poll_401": {
            "value": poll_401_rate,
            "max": float(max_poll_401_rate),
            "ok": poll_401_rate <= float(max_poll_401_rate),
        },
        "transport_failures": {
            "value": failures,
            "max": allowed_transport_failures,
            "ok": failures <= allowed_transport_failures,
        },
        "route_coverage": {
            "value": route_checked,
            "min": route_checked_min,
            "ok": route_checked >= route_checked_min,
        },
    }
    ok = all(bool(item.get("ok")) for item in checks.values())
    payload: Dict[str, Any] = {
        "ok": ok,
        "ticks": ticks,
        "route_checked": route_checked,
        "wrong_route": wrong_route,
        "failures": failures,
        "window_seconds": int(window_seconds),
        "attempts_per_tick": per_tick_attempts,
        "recent_errors": recent_errors,
        "startup_warnings": startup_warnings,
        "startup_transport_grace_remaining": startup_grace_remaining,
        "checks": checks,
        "runtime_metrics": metrics,
    }
    return payload


def main() -> int:
    args = parse_args()
    payload = run_soak_gate(
        base_url=args.base_url,
        api_key=args.api_key,
        duration_hours=args.duration_hours,
        interval_seconds=args.interval_seconds,
        window_seconds=args.window_seconds,
        max_wrong_route_rate=args.max_wrong_route_rate,
        max_safety_fallback_rate=args.max_safety_fallback_rate,
        max_poll_401_rate=args.max_poll_401_rate,
        max_transport_failures=args.max_transport_failures,
        attempts_per_tick=args.attempts_per_tick,
        chat_timeout_seconds=args.chat_timeout_seconds,
        min_route_checked=args.min_route_checked,
        startup_transport_grace=args.startup_transport_grace,
        min_route_attempt_ticks=args.min_route_attempt_ticks,
    )
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if bool(payload.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
