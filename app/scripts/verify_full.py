#!/usr/bin/env python3
from __future__ import annotations

"""
Post-start strict verification orchestrator.

Why this module exists:
- Execute full runtime validation (pytest + E2E + contracts) against a live host.
- Provide deterministic pass/fail output for release and operator checks.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scripts.start_with_preflight import _default_browser_smoke_cmd
from app.services.validation_state import finish_flow, mark_step, start_flow
from app.utils.runtime_helpers import (
    env_int as _env_int,
    product_track_default as _product_track_default,
    runtime_profile_default as _runtime_profile_default,
)


E2E_SCRIPT = ROOT / "app" / "scripts" / "e2e_flow_check.py"
AGENT_EVAL_SCRIPT = ROOT / "app" / "scripts" / "agent_eval_check.py"
HARD_CONTRACT_SCRIPT = ROOT / "app" / "scripts" / "hard_contract_check.py"
NO_LOOP_STRESS_SCRIPT = ROOT / "app" / "scripts" / "no_loop_stress_check.py"
VERIFY_FULL_STEPS = [
    "host-prereq",
    "pytest-full",
    "e2e-strict",
    "readyz",
    "agent-evals",
    "ui-contract",
    "hard-contract",
    "no-loop-stress",
    "browser-smoke",
]


def _run(cmd: list[str], *, env: dict[str, str], label: str, timeout: int) -> int:
    # Kept local intentionally: verify_full has a compact CLI contract and
    # should not depend on orchestration helpers from other scripts.
    print(f"\n[run] {label}: {' '.join(cmd)}")
    try:
        return subprocess.run(cmd, env=env, check=False, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"[fail] {label}: timed out after {timeout}s")
        return 124


def _host_prereq(base_url: str, timeout: int) -> tuple[bool, str]:
    target = str(base_url or "").strip()
    if not target:
        return False, "missing-base-url"
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"}:
        return False, f"invalid-base-url-scheme:{parsed.scheme or 'none'}"
    if not parsed.netloc:
        return False, "invalid-base-url-host"

    healthz = f"{target.rstrip('/')}/healthz"
    try:
        r = requests.get(healthz, timeout=max(3, timeout))
    except Exception as exc:  # noqa: BLE001
        return False, f"healthz-request-failed:{exc}"
    if r.status_code != 200:
        return False, f"healthz-status:{r.status_code}"
    return True, "ok"


def _check_readyz(
    base_url: str,
    api_key: str,
    timeout: int,
    *,
    strict: bool = False,
    product_track: str = "core",
) -> tuple[bool, str]:
    # NOTE: kept local (instead of shared with start_with_preflight.py) because
    # verify-full returns compact CLI-oriented status tokens.
    target = str(base_url or "").strip()
    if not target:
        return False, "missing-base-url"
    url = f"{target.rstrip('/')}/system/readyz"
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = requests.get(url, headers=headers, timeout=max(3, timeout))
    except Exception as exc:  # noqa: BLE001
        return False, f"readyz-request-failed:{exc}"
    if r.status_code != 200:
        return False, f"readyz-status:{r.status_code}"
    try:
        data = r.json()
    except Exception:
        return False, "readyz-non-json"
    if not bool(data.get("ready")):
        return False, f"readyz-not-ready:{data}"
    if strict:
        status = str(data.get("status") or "").strip().lower()
        if product_track == "full":
            if status and status != "ready":
                return False, f"strict-readyz-requires-status-ready:{status}"
        else:
            if status and status not in {"ready", "degraded", "fallback-only"}:
                return False, f"strict-core-readyz-requires-ready-or-degraded:{status}"
    return True, "ok"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extended verification: full pytest + strict E2E + optional browser smoke.")
    p.add_argument(
        "--runtime-profile",
        choices=["standard", "strict"],
        default=_runtime_profile_default(),
        help="Validation profile. strict => strict browser smoke is required by default.",
    )
    p.add_argument(
        "--product-track",
        choices=["core", "full"],
        default=_product_track_default(),
        help="Product track contract. core keeps optional host deps non-blocking; full enforces all in strict.",
    )
    p.add_argument("--base-url", default="")
    p.add_argument("--api-key", default=os.getenv("AEGIS_API_KEY", ""))
    p.add_argument("--files-api-key", default=os.getenv("FILES_API_KEY", ""))
    p.add_argument("--health-timeout", type=int, default=12)
    p.add_argument("--pytest-timeout", type=int, default=600)
    p.add_argument("--e2e-timeout", type=int, default=180)
    p.add_argument("--browser-smoke-cmd", default="", help="Optional shell command for browser smoke.")
    p.add_argument("--strict-browser-smoke", action="store_true", help="Fail instead of skipping when browser runtime is unavailable.")
    p.add_argument("--skip-ui-contract", action="store_true", help="Skip UI contract check (HTML + static assets).")
    p.add_argument("--skip-hard-contract", action="store_true", help="Skip hard contract gate.")
    p.add_argument("--skip-no-loop-stress", action="store_true", help="Skip no-loop stress gate.")
    p.add_argument("--hard-contract-timeout", type=int, default=180)
    p.add_argument("--no-loop-timeout", type=int, default=120)
    p.add_argument("--no-loop-runs", type=int, default=8)
    p.add_argument(
        "--no-loop-request-timeout",
        type=int,
        default=_env_int("AEGIS_CONTRACT_NO_LOOP_REQUEST_TIMEOUT", 45),
    )
    p.add_argument(
        "--no-loop-max-seconds-per-run",
        type=float,
        default=float(os.getenv("AEGIS_CONTRACT_NO_LOOP_MAX_SECONDS", "35")),
    )
    p.add_argument(
        "--max-no-loop-failures",
        type=int,
        default=_env_int("AEGIS_CONTRACT_MAX_NO_LOOP_FAILURES", 0),
    )
    p.add_argument(
        "--no-loop-auth-edge-every",
        type=int,
        default=_env_int("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_EVERY", 0),
    )
    p.add_argument(
        "--no-loop-auth-edge-invalid-key",
        default=os.getenv("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_INVALID_KEY", "invalid-no-loop-key"),
    )
    p.add_argument(
        "--max-no-loop-auth-edge-unexpected-failures",
        type=int,
        default=_env_int("AEGIS_CONTRACT_MAX_NO_LOOP_AUTH_EDGE_UNEXPECTED", 0),
    )
    p.add_argument("--skip-pytest", action="store_true")
    p.add_argument("--skip-e2e", action="store_true")
    return p.parse_args()


def main() -> int:
    """
    What it does:
    - Runs post-start strict verification pipeline for full runtime confidence.

    Why it exists:
    - Provide deterministic go/no-go validation after environment boot.

    Called from ->
    - `verify_full.sh`, `go_strict.sh`, CI/manual strict checks

    Calls ->
    - full pytest, strict E2E, readyz, agent evals, UI contract,
      hard-contract and no-loop stress gates, browser smoke

    Failure/guard behavior:
    - Enforces strict profile requirements (no skip flags for required gates).
    """
    args = parse_args()
    env = os.environ.copy()
    runtime_profile = "strict" if str(args.runtime_profile).strip().lower() == "strict" else "standard"
    product_track = "full" if str(getattr(args, "product_track", _product_track_default())).strip().lower() == "full" else "core"
    strict_from_profile = runtime_profile == "strict"
    strict_browser_smoke = bool(args.strict_browser_smoke or (strict_from_profile and product_track == "full"))
    skip_no_loop_stress = bool(getattr(args, "skip_no_loop_stress", False))
    no_loop_timeout = int(getattr(args, "no_loop_timeout", 120) or 120)
    no_loop_runs = int(getattr(args, "no_loop_runs", 8) or 8)
    no_loop_request_timeout = int(getattr(args, "no_loop_request_timeout", 45) or 45)
    no_loop_max_seconds_per_run = float(getattr(args, "no_loop_max_seconds_per_run", 35.0) or 35.0)
    max_no_loop_failures = int(getattr(args, "max_no_loop_failures", 0) or 0)
    no_loop_auth_edge_every = int(getattr(args, "no_loop_auth_edge_every", 0) or 0)
    no_loop_auth_edge_invalid_key = str(getattr(args, "no_loop_auth_edge_invalid_key", "invalid-no-loop-key") or "").strip()
    max_no_loop_auth_edge_unexpected_failures = int(
        getattr(args, "max_no_loop_auth_edge_unexpected_failures", 0) or 0
    )
    env["AEGIS_RUNTIME_PROFILE"] = runtime_profile
    env["AEGIS_PRODUCT_TRACK"] = product_track
    start_flow("verify_full", VERIFY_FULL_STEPS)
    print(f"[profile] runtime={runtime_profile} track={product_track} strict_browser_smoke={int(strict_browser_smoke)}")

    if strict_from_profile:
        if not str(args.base_url or "").strip():
            mark_step("verify_full", "host-prereq", "failed", "missing-base-url-strict")
            finish_flow("verify_full", "failed", "host-prereq")
            print("[fail] Strict verify_full requires --base-url.")
            return 2
        if bool(args.skip_pytest):
            mark_step("verify_full", "pytest-full", "failed", "skip-pytest-in-strict")
            finish_flow("verify_full", "failed", "pytest-full")
            print("[fail] Strict verify_full does not allow --skip-pytest.")
            return 2
        if bool(args.skip_e2e):
            mark_step("verify_full", "e2e-strict", "failed", "skip-e2e-in-strict")
            finish_flow("verify_full", "failed", "e2e-strict")
            print("[fail] Strict verify_full does not allow --skip-e2e.")
            return 2
        if bool(args.skip_ui_contract):
            mark_step("verify_full", "ui-contract", "failed", "skip-ui-contract-in-strict")
            finish_flow("verify_full", "failed", "ui-contract")
            print("[fail] Strict verify_full does not allow --skip-ui-contract.")
            return 2
        if bool(args.skip_hard_contract):
            mark_step("verify_full", "hard-contract", "failed", "skip-hard-contract-in-strict")
            finish_flow("verify_full", "failed", "hard-contract")
            print("[fail] Strict verify_full does not allow --skip-hard-contract.")
            return 2
        if skip_no_loop_stress:
            mark_step("verify_full", "no-loop-stress", "failed", "skip-no-loop-stress-in-strict")
            finish_flow("verify_full", "failed", "no-loop-stress")
            print("[fail] Strict verify_full does not allow --skip-no-loop-stress.")
            return 2

    if args.base_url:
        ok, detail = _host_prereq(args.base_url, args.health_timeout)
        if not ok:
            mark_step("verify_full", "host-prereq", "failed", detail)
            finish_flow("verify_full", "failed", "host-prereq")
            print(f"[fail] host-prereq failed: {detail}")
            return 2
        mark_step("verify_full", "host-prereq", "passed", "ok")
    else:
        mark_step("verify_full", "host-prereq", "skipped", "missing-base-url")

    if not args.skip_pytest:
        rc = _run([sys.executable, "-m", "pytest", "-q"], env=env, label="pytest-full", timeout=max(60, args.pytest_timeout))
        if rc != 0:
            mark_step("verify_full", "pytest-full", "failed", f"exit={rc}")
            finish_flow("verify_full", "failed", "pytest-full")
            print("[fail] Full pytest verification failed.")
            return rc
        mark_step("verify_full", "pytest-full", "passed", "ok")
    else:
        mark_step("verify_full", "pytest-full", "skipped", "skip-pytest")

    if not args.skip_e2e and args.base_url:
        if strict_from_profile and product_track == "full":
            # Full track keeps optional host deps (image/backend) as strict blockers.
            e2e_cmd = [
                sys.executable,
                str(E2E_SCRIPT),
                "--base-url",
                args.base_url,
                "--api-key",
                args.api_key,
                "--files-api-key",
                args.files_api_key or args.api_key,
                "--timeout",
                str(max(60, args.e2e_timeout)),
                "--strict-capabilities",
            ]
            rc = _run(
                e2e_cmd,
                env=env,
                label="e2e-strict",
                timeout=max(120, args.e2e_timeout * 3),
            )
        else:
            e2e_cmd = [
                sys.executable,
                str(E2E_SCRIPT),
                "--base-url",
                args.base_url,
                "--api-key",
                args.api_key,
                "--files-api-key",
                args.files_api_key or args.api_key,
                "--timeout",
                str(max(60, args.e2e_timeout)),
            ]
            rc = _run(
                e2e_cmd,
                env=env,
                label="e2e-strict",
                timeout=max(120, args.e2e_timeout * 3),
            )
        if rc != 0:
            mark_step("verify_full", "e2e-strict", "failed", f"exit={rc}")
            finish_flow("verify_full", "failed", "e2e-strict")
            print("[fail] Strict E2E verification failed.")
            return rc
        mark_step("verify_full", "e2e-strict", "passed", "ok")
    else:
        mark_step("verify_full", "e2e-strict", "skipped", "skip-e2e-or-missing-base-url")

    if args.base_url:
        ok, detail = _check_readyz(
            args.base_url,
            args.api_key,
            args.health_timeout,
            strict=strict_from_profile,
            product_track=product_track,
        )
        if not ok:
            mark_step("verify_full", "readyz", "failed", detail)
            finish_flow("verify_full", "failed", "readyz")
            print(f"[fail] readyz verification failed: {detail}")
            return 2
        mark_step("verify_full", "readyz", "passed", "ok")
    else:
        mark_step("verify_full", "readyz", "skipped", "missing-base-url")

    if AGENT_EVAL_SCRIPT.exists():
        rc = _run(
            [sys.executable, "-m", "app.scripts.agent_eval_check"],
            env=env,
            label="agent-evals",
            timeout=60,
        )
        if rc != 0:
            mark_step("verify_full", "agent-evals", "failed", f"exit={rc}")
            finish_flow("verify_full", "failed", "agent-evals")
            print("[fail] Agent eval verification failed.")
            return rc
        mark_step("verify_full", "agent-evals", "passed", "ok")
    else:
        mark_step("verify_full", "agent-evals", "skipped", "missing-agent-eval-script")

    if not args.skip_ui_contract and args.base_url:
        rc = _run(
            [sys.executable, "-m", "app.scripts.ui_contract_check", "--base-url", args.base_url],
            env=env,
            label="ui-contract",
            timeout=30,
        )
        if rc != 0:
            mark_step("verify_full", "ui-contract", "failed", f"exit={rc}")
            finish_flow("verify_full", "failed", "ui-contract")
            print("[fail] UI contract verification failed.")
            return rc
        mark_step("verify_full", "ui-contract", "passed", "ok")
    else:
        mark_step("verify_full", "ui-contract", "skipped", "skip-ui-contract-or-missing-base-url")

    if not args.skip_hard_contract and args.base_url and HARD_CONTRACT_SCRIPT.exists():
        hard_contract_cmd = [
            sys.executable,
            "-m",
            "app.scripts.hard_contract_check",
            "--base-url",
            args.base_url,
            "--api-key",
            args.api_key,
            "--strict",
            "--run-no-loop",
            "--no-loop-runs",
            str(max(1, no_loop_runs)),
            "--no-loop-request-timeout",
            str(max(5, no_loop_request_timeout)),
            "--no-loop-max-seconds-per-run",
            str(max(1.0, no_loop_max_seconds_per_run)),
            "--max-no-loop-failures",
            str(max(0, max_no_loop_failures)),
            "--no-loop-auth-edge-every",
            str(max(0, no_loop_auth_edge_every)),
            "--max-no-loop-auth-edge-unexpected-failures",
            str(max(0, max_no_loop_auth_edge_unexpected_failures)),
        ]
        if no_loop_auth_edge_invalid_key:
            hard_contract_cmd.extend(["--no-loop-auth-edge-invalid-key", no_loop_auth_edge_invalid_key])
        rc = _run(
            hard_contract_cmd,
            env=env,
            label="hard-contract",
            timeout=max(30, args.hard_contract_timeout),
        )
        if rc != 0:
            mark_step("verify_full", "hard-contract", "failed", f"exit={rc}")
            finish_flow("verify_full", "failed", "hard-contract")
            print("[fail] Hard contract verification failed.")
            return rc
        mark_step("verify_full", "hard-contract", "passed", "ok")
    else:
        mark_step("verify_full", "hard-contract", "skipped", "skip-hard-contract-or-missing-base-url")

    if not skip_no_loop_stress and args.base_url and NO_LOOP_STRESS_SCRIPT.exists():
        no_loop_cmd = [
            sys.executable,
            "-m",
            "app.scripts.no_loop_stress_check",
            "--base-url",
            args.base_url,
            "--api-key",
            args.api_key,
            "--runs",
            str(max(4, no_loop_runs)),
            "--request-timeout",
            str(max(5, no_loop_request_timeout)),
            "--max-seconds-per-run",
            str(max(1.0, no_loop_max_seconds_per_run)),
            "--max-failures",
            str(max(0, max_no_loop_failures)),
            "--auth-edge-every",
            str(max(0, no_loop_auth_edge_every)),
            "--max-auth-edge-unexpected-failures",
            str(max(0, max_no_loop_auth_edge_unexpected_failures)),
        ]
        if no_loop_auth_edge_invalid_key:
            no_loop_cmd.extend(["--auth-edge-invalid-key", no_loop_auth_edge_invalid_key])
        rc = _run(
            no_loop_cmd,
            env=env,
            label="no-loop-stress",
            timeout=max(30, no_loop_timeout),
        )
        if rc != 0:
            mark_step("verify_full", "no-loop-stress", "failed", f"exit={rc}")
            finish_flow("verify_full", "failed", "no-loop-stress")
            print("[fail] No-loop stress verification failed.")
            return rc
        mark_step("verify_full", "no-loop-stress", "passed", "ok")
    else:
        if strict_from_profile and not skip_no_loop_stress:
            mark_step("verify_full", "no-loop-stress", "failed", "missing-no-loop-stress-script")
            finish_flow("verify_full", "failed", "no-loop-stress")
            print("[fail] Strict verify_full requires no-loop stress script.")
            return 2
        mark_step("verify_full", "no-loop-stress", "skipped", "skip-no-loop-stress-or-missing-base-url")

    browser_smoke_cmd = args.browser_smoke_cmd.strip()
    if not browser_smoke_cmd and args.base_url:
        browser_smoke_cmd = _default_browser_smoke_cmd(
            args.base_url,
            args.api_key,
            args.files_api_key or args.api_key,
            strict=strict_browser_smoke,
        )
    if browser_smoke_cmd:
        rc = _run(
            ["bash", "-lc", browser_smoke_cmd],
            env=env,
            label="browser-smoke",
            timeout=300,
        )
        if rc != 0:
            mark_step("verify_full", "browser-smoke", "failed", f"exit={rc}")
            finish_flow("verify_full", "failed", "browser-smoke")
            print("[fail] Browser smoke verification failed.")
            return rc
        mark_step("verify_full", "browser-smoke", "passed", "ok")
    else:
        if strict_browser_smoke:
            mark_step("verify_full", "browser-smoke", "failed", "missing-browser-smoke-cmd")
            finish_flow("verify_full", "failed", "browser-smoke")
            print("[fail] Strict browser smoke requested but no command is configured.")
            return 2
        mark_step("verify_full", "browser-smoke", "skipped", "no-browser-smoke-cmd")

    finish_flow("verify_full", "passed", "verify-full-passed")
    print("[ok] verify-full checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
