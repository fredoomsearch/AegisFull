#!/usr/bin/env python3
from __future__ import annotations

"""
Startup gate orchestrator for host runtime boot.

Why this module exists:
- Run strict/standard preflight checks before uvicorn startup.
- Fail closed when security, capability, or contract gates are not satisfied.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

E2E_SCRIPT = ROOT / "app" / "scripts" / "e2e_flow_check.py"
BROWSER_SMOKE_SCRIPT = ROOT / "app" / "scripts" / "browser_smoke.py"
UI_CONTRACT_SCRIPT = ROOT / "app" / "scripts" / "ui_contract_check.py"
AGENT_EVAL_SCRIPT = ROOT / "app" / "scripts" / "agent_eval_check.py"
HARD_CONTRACT_SCRIPT = ROOT / "app" / "scripts" / "hard_contract_check.py"
NO_LOOP_STRESS_SCRIPT = ROOT / "app" / "scripts" / "no_loop_stress_check.py"
from app.services.validation_state import finish_flow, mark_step, start_flow
from app.utils.runtime_helpers import (
    env_int as _env_int,
    first_csv_token as _first_csv_token,
    product_track_default as _product_track_default,
    runtime_profile_default as _runtime_profile_default,
)
PYTEST_SMOKE_FILES = [
    "tests/test_project_services.py",
    "tests/test_retrieval_project_scope.py",
    "tests/test_ingest_repo_incremental.py",
    "tests/test_upload_inspector.py",
    "tests/test_conversation_state_db.py",
    "tests/test_files_project_surface.py",
    "tests/test_files_workspace_ingest.py",
    "tests/test_files_av_endpoints.py",
    "tests/test_ui_js_syntax.py",
    "tests/test_browser_smoke_compiles.py",
    "tests/test_chat_tool_first.py",
    "tests/test_chat_output_safety.py",
    "tests/test_agent_step.py",
    "tests/test_agent_run.py",
    "tests/test_agent_continue.py",
    "tests/test_agent_ops_tools.py",
    "tests/test_agent_approval_block.py",
    "tests/test_conversation_turns.py",
    "tests/test_execute_tool_approval.py",
    "tests/test_system_readyz_status.py",
    "tests/test_capabilities_service.py",
    "tests/test_redaction.py",
    "tests/test_image_reference_generation.py",
    "tests/test_web_search_meta.py",
    "tests/test_start_with_preflight_defaults.py",
    "tests/test_verify_full_profile.py",
    "tests/test_production_profile_check.py",
    "tests/test_validation_state.py",
    "tests/test_turn_plan_risk.py",
    "tests/test_replan_delete_project.py",
    "tests/test_tools_legacy_surface.py",
    "tests/test_tools_legacy_endpoints.py",
    "tests/test_e2e_cleanup_artifacts.py",
    "tests/test_cleanup_runtime_artifacts.py",
    "tests/test_e2e_flow_guards.py",
    "tests/test_ui_project_identity.py",
    "tests/test_ui_index_unique_ids.py",
    "tests/test_ui_output_safety.py",
    "tests/test_job_apply_helper.py",
    "tests/test_crypto_trade_safety.py",
    "tests/test_adversarial_eval_check.py",
    "tests/test_hard_contract_check.py",
    "tests/test_hard_contract_routing.py",
    "tests/test_soak_gate_compiles.py",
    "tests/test_no_loop_stress_check_compiles.py",
    "tests/test_system_metrics_runtime.py",
]

WEAK_KEYS = {"my-secret-key", "changeme", "change-me", "dev", "test", "password"}
STARTUP_GATE_STEPS = [
    "host-prereq",
    "pytest-smoke",
    "agent-evals",
    "preflight-e2e",
    "healthz",
    "host-e2e",
    "readyz",
    "ui-contract",
    "hard-contract",
    "no-loop-stress",
    "browser-smoke",
]

_CONTRACT_MODES = {"full", "strict", "none"}


def _contract_mode_default() -> str:
    raw = (os.getenv("AEGIS_START_CONTRACT_MODE", "full") or "full").strip().lower()
    return raw if raw in _CONTRACT_MODES else "full"


def _env_bool(name: str, default: bool = False) -> bool:
    # Kept local intentionally: startup gate script must stay standalone/minimal,
    # even though other modules implement similar env-bool parsing helpers.
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _print_block(title: str, lines: list[str]) -> None:
    print(f"\n[{title}]")
    for line in lines:
        print(f"- {line}")


def _run_cmd(cmd: list[str], *, env: dict[str, str], timeout: int, label: str) -> int:
    print(f"\n[run] {label}: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, env=env, check=False, timeout=timeout)
        return int(res.returncode)
    except subprocess.TimeoutExpired:
        print(f"[fail] {label}: timed out after {timeout}s")
        return 124


def _run_shell_cmd(cmd: str, *, env: dict[str, str], timeout: int, label: str) -> int:
    print(f"\n[run] {label}: {cmd}")
    try:
        res = subprocess.run(["bash", "-lc", cmd], env=env, check=False, timeout=timeout)
        return int(res.returncode)
    except subprocess.TimeoutExpired:
        print(f"[fail] {label}: timed out after {timeout}s")
        return 124


def _pytest_smoke_cmd(custom: str | None = None) -> list[str]:
    tests_raw = (custom or "").strip()
    test_files = [item.strip() for item in tests_raw.split(",") if item.strip()] if tests_raw else list(PYTEST_SMOKE_FILES)
    return [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-x",
        *test_files,
    ]


def _default_browser_smoke_cmd(base_url: str, api_key: str, files_key: str, *, strict: bool) -> str:
    if not BROWSER_SMOKE_SCRIPT.exists():
        return ""
    cmd = [
        sys.executable,
        "-m",
        "app.scripts.browser_smoke",
        "--base-url",
        base_url,
        "--api-key",
        api_key,
        "--files-api-key",
        files_key or api_key,
    ]
    if strict:
        cmd.extend([
            "--strict",
            "--crypto-proof",
            "--geo-proof",
            "--memory-speed-proof",
            "--web-proof",
        ])
    return " ".join(cmd).strip()


def _wait_health(
    base_url: str,
    timeout_s: int,
    child: subprocess.Popen,
    *,
    log_interval_s: int = 10,
) -> bool:
    wait_budget = max(5, timeout_s)
    start_ts = time.time()
    deadline = start_ts + wait_budget
    health_url = f"{base_url.rstrip('/')}/healthz"
    next_log_ts = start_ts + max(1, int(log_interval_s or 0))
    last_error = ""
    while time.time() < deadline:
        if child.poll() is not None:
            return False
        try:
            r = requests.get(health_url, timeout=3)
            if r.status_code == 200:
                return True
            last_error = f"status={r.status_code}"
        except Exception as exc:
            last_error = str(exc)
        now = time.time()
        if now >= next_log_ts:
            elapsed_s = max(0, int(now - start_ts))
            remaining_s = max(0, int(deadline - now))
            suffix = f" last_error={last_error}" if last_error else ""
            print(
                f"[wait] healthz pending: elapsed={elapsed_s}s remaining={remaining_s}s url={health_url}{suffix}"
            )
            next_log_ts = now + max(1, int(log_interval_s or 0))
        time.sleep(1)
    return False


def _check_readyz(
    base_url: str,
    api_key: str,
    *,
    strict: bool = False,
    product_track: str = "core",
) -> tuple[bool, str, dict | None]:
    # NOTE: kept local (instead of shared with verify_full.py) because startup and
    # post-start verification intentionally enforce slightly different error details.
    url = f"{base_url.rstrip('/')}/system/readyz"
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = requests.get(url, headers=headers, timeout=8)
    except Exception as exc:  # noqa: BLE001
        return False, f"readyz request failed: {exc}", None
    if r.status_code != 200:
        return False, f"readyz status={r.status_code} body={(r.text or '')[:300]}", None
    try:
        data = r.json()
    except Exception:
        return False, "readyz returned non-JSON body", None
    if not bool(data.get("ready")):
        return False, f"readyz reports not ready: {data}", data if isinstance(data, dict) else None
    if strict:
        status = str(data.get("status") or "").strip().lower()
        if product_track == "full":
            if status and status != "ready":
                return False, f"strict-readyz-requires-status-ready (status={status})", data if isinstance(data, dict) else None
        else:
            if status and status not in {"ready", "degraded", "fallback-only"}:
                return False, f"strict-core-readyz-requires-ready-or-degraded (status={status})", data if isinstance(data, dict) else None
    return True, "readyz ready=true", data if isinstance(data, dict) else None


def _readyz_debug_lines(base_url: str, readyz_data: dict | None) -> list[str]:
    lines = [f"url: {base_url}"]
    if not isinstance(readyz_data, dict):
        return lines
    process = readyz_data.get("process") if isinstance(readyz_data.get("process"), dict) else {}
    pid = process.get("pid")
    host = str(process.get("hostname") or "").strip()
    uptime = process.get("uptime_s")
    status = str(readyz_data.get("status") or "unknown").strip() or "unknown"
    if pid or host or uptime is not None:
        uptime_text = ""
        try:
            uptime_f = float(uptime)
            uptime_text = f" · up {uptime_f:.1f}s"
        except Exception:
            if uptime not in (None, ""):
                uptime_text = f" · up {uptime}"
        lines.append(f"process: pid={pid or '?'}{f' @ {host}' if host else ''}{uptime_text}")
    lines.append(f"readyz.status: {status}")
    for key in ("web_search", "image", "llm"):
        section = readyz_data.get(key)
        if isinstance(section, dict):
            level = str(section.get("status") or "").strip()
            if level:
                lines.append(f"{key}: {level}")
    degraded = readyz_data.get("degraded_reasons")
    if isinstance(degraded, list) and degraded:
        joined = ", ".join(str(x) for x in degraded[:6] if str(x).strip())
        if joined:
            lines.append(f"degraded_reasons: {joined}")
    checks = readyz_data.get("checks")
    if isinstance(checks, dict) and checks:
        summary = []
        for key in ("embeddings", "retrieval", "llm", "web_search", "image", "clamav", "project_tools"):
            value = checks.get(key)
            if value is not None:
                summary.append(f"{key}={value}")
        if summary:
            lines.append(f"checks: {'; '.join(summary)}")
    return lines


def _security_checks(api_key: str, files_key: str, strict: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []

    demo_mode = _env_bool("AEGIS_DEMO_MODE", False)
    auth_mode = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()
    cors_origins = (os.getenv("AEGIS_CORS_ORIGINS", "*") or "*").strip()
    hsts_seconds = int((os.getenv("AEGIS_HSTS_SECONDS", "0") or "0").strip() or "0")
    av_fail_open = _env_bool("FILES_AV_FAIL_OPEN", True)

    if auth_mode != "on":
        errors.append(f"AEGIS_AUTH_MODE={auth_mode} (expected 'on')")
    if not api_key:
        errors.append("AEGIS_API_KEY missing (or --api-key not provided)")
    if not files_key:
        errors.append("FILES_API_KEY missing (or --files-api-key not provided)")

    if api_key and api_key.lower() in WEAK_KEYS:
        warns.append("AEGIS_API_KEY looks weak/default")
    if files_key and files_key.lower() in WEAK_KEYS:
        warns.append("FILES_API_KEY looks weak/default")
    if not demo_mode:
        if cors_origins == "*" or "*" in [p.strip() for p in cors_origins.split(",")]:
            warns.append("AEGIS_CORS_ORIGINS includes '*'")
        if av_fail_open:
            warns.append("FILES_AV_FAIL_OPEN=1 (scanner timeout/error won't block upload)")
        if hsts_seconds <= 0:
            warns.append("AEGIS_HSTS_SECONDS=0 (HSTS disabled)")

    if strict and warns:
        errors.extend([f"[strict] {w}" for w in warns])

    return errors, warns


def _env_truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _db_required(env: dict[str, str]) -> bool:
    return not _env_truthy(env.get("AEGIS_DISABLE_DB"))


def _has_db_config(env: dict[str, str]) -> bool:
    if str(env.get("DATABASE_URL") or "").strip():
        return True
    host = str(env.get("POSTGRES_HOST") or env.get("PGHOST") or "").strip()
    db = str(env.get("POSTGRES_DB") or env.get("PGDATABASE") or "").strip()
    return bool(host and db)


def _port_bindable(host: str, port: int) -> tuple[bool, str]:
    """
    Best-effort check that the target bind address is available before uvicorn launch.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
    except Exception as exc:  # noqa: BLE001
        return False, f"could not resolve host/port ({host}:{port}): {exc}"

    last_err: Exception | None = None
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(sockaddr)
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        finally:
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                pass
    return False, f"cannot bind {host}:{port} ({last_err or 'unknown error'})"


def _host_prereq_checks(*, host: str, port: int, env: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []

    if _db_required(env) and not _has_db_config(env):
        errors.append("DB required but DATABASE_URL/POSTGRES_* is not configured")

    bind_ok, bind_detail = _port_bindable(host, port)
    if not bind_ok:
        errors.append(bind_detail)

    return errors, warns


def _forward_signal(proc: subprocess.Popen, sig: int) -> None:
    if proc.poll() is None:
        try:
            proc.send_signal(sig)
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Start uvicorn only after automated preflight/E2E gates pass."
    )
    p.add_argument(
        "--runtime-profile",
        choices=["standard", "strict"],
        default=_runtime_profile_default(),
        help="Validation profile. strict => security/capabilities/browser gates are strict by default.",
    )
    p.add_argument(
        "--product-track",
        choices=["core", "full"],
        default=_product_track_default(),
        help="Product track contract. core keeps optional host deps non-blocking; full enforces all in strict.",
    )
    p.add_argument(
        "--contract-mode",
        choices=["full", "strict", "none"],
        default=_contract_mode_default(),
        help="Startup contract gate depth. full=runs full preflight chain, strict=light local gates only, none=boot with minimal checks.",
    )
    p.add_argument("--app", default="main:app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.add_argument("--log-level", default="info")

    p.add_argument("--api-key", default="")
    p.add_argument("--files-api-key", default="")
    p.add_argument("--admin-api-key", default="")
    p.add_argument("--check-base-url", default="")

    p.add_argument("--health-timeout", type=int, default=120)
    p.add_argument("--e2e-timeout", type=int, default=90)
    p.add_argument("--preflight-timeout", type=int, default=120)
    p.add_argument("--pytest-timeout", type=int, default=90)
    p.add_argument(
        "--pytest-smoke-tests",
        default="",
        help="Comma-separated pytest files for startup smoke gate. Defaults to a curated short subset.",
    )

    p.add_argument("--skip-pytest-smoke", action="store_true")
    p.add_argument("--skip-preflight", action="store_true")
    p.add_argument("--skip-post-e2e", action="store_true")
    p.add_argument("--skip-ui-contract", action="store_true")
    p.add_argument("--skip-hard-contract", action="store_true")
    p.add_argument("--skip-no-loop-stress", action="store_true")
    p.add_argument("--skip-browser-smoke", action="store_true")
    p.add_argument(
        "--strict-browser-smoke",
        action="store_true",
        help="Fail instead of skipping when the browser runtime is unavailable.",
    )
    p.add_argument(
        "--browser-smoke-cmd",
        default=os.getenv("AEGIS_BROWSER_SMOKE_CMD", ""),
        help="Browser smoke command to run after host E2E/readyz. Defaults to the repo browser smoke script when available.",
    )
    p.add_argument("--browser-smoke-timeout", type=int, default=300)
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
    p.add_argument("--strict-security", action="store_true")
    p.add_argument(
        "--strict-capabilities",
        action="store_true",
        help="Fail startup if host E2E detects degraded/fallback-only runtime capabilities.",
    )
    p.add_argument("--disable-db", action="store_true")
    return p.parse_args()


def main() -> int:
    """
    What it does:
    - Executes startup gate sequence before launching uvicorn.

    Why it exists:
    - Prevents booting a runtime that fails smoke/security/contract checks.

    Called from ->
    - `start_aegis.sh` and strict startup wrappers

    Calls ->
    - host prereq checks, pytest smoke, agent evals, E2E checks,
      readyz/ui/hard-contract/no-loop/browser-smoke gates

    Failure/guard behavior:
    - Fails closed in strict profile when required gates are skipped or fail.
    """
    args = parse_args()
    env = os.environ.copy()
    start_flow("startup_gate", STARTUP_GATE_STEPS)
    runtime_profile = "strict" if str(args.runtime_profile).strip().lower() == "strict" else "standard"
    product_track = "full" if str(getattr(args, "product_track", _product_track_default())).strip().lower() == "full" else "core"
    contract_mode = str(getattr(args, "contract_mode", _contract_mode_default()) or "full").strip().lower()
    if contract_mode not in _CONTRACT_MODES:
        contract_mode = "full"
    full_contract = contract_mode == "full"
    no_contract = contract_mode == "none"
    strict_from_profile = runtime_profile == "strict"
    strict_browser_smoke = bool(args.strict_browser_smoke or (strict_from_profile and product_track == "full" and full_contract))
    strict_security = bool(args.strict_security or strict_from_profile)
    strict_capabilities = bool(args.strict_capabilities or (strict_from_profile and product_track == "full" and full_contract))
    no_loop_runs = max(4, int(getattr(args, "no_loop_runs", 8) or 8))
    no_loop_request_timeout = max(5, int(getattr(args, "no_loop_request_timeout", 45) or 45))
    no_loop_max_seconds_per_run = max(1.0, float(getattr(args, "no_loop_max_seconds_per_run", 35.0) or 35.0))
    max_no_loop_failures = max(0, int(getattr(args, "max_no_loop_failures", 0) or 0))
    no_loop_auth_edge_every = max(0, int(getattr(args, "no_loop_auth_edge_every", 0) or 0))
    no_loop_auth_edge_invalid_key = str(
        getattr(args, "no_loop_auth_edge_invalid_key", "invalid-no-loop-key") or ""
    ).strip()
    max_no_loop_auth_edge_unexpected_failures = max(
        0, int(getattr(args, "max_no_loop_auth_edge_unexpected_failures", 0) or 0)
    )
    soak_startup_transport_grace = max(
        0, int(os.getenv("AEGIS_CONTRACT_SOAK_STARTUP_TRANSPORT_GRACE", "2") or 2)
    )
    soak_min_route_attempt_ticks = max(
        1, int(os.getenv("AEGIS_CONTRACT_SOAK_MIN_ROUTE_ATTEMPT_TICKS", "5") or 5)
    )
    soak_chat_timeout_seconds = max(
        8, int(os.getenv("AEGIS_CONTRACT_SOAK_CHAT_TIMEOUT_SECONDS", "20") or 20)
    )

    if args.disable_db:
        env["AEGIS_DISABLE_DB"] = "1"
    env["AEGIS_RUNTIME_PROFILE"] = runtime_profile
    env["AEGIS_PRODUCT_TRACK"] = product_track
    env["AEGIS_START_CONTRACT_MODE"] = contract_mode

    if full_contract and strict_browser_smoke and args.skip_browser_smoke:
        finish_flow("startup_gate", "failed", "browser-smoke-disabled-in-strict")
        print("[fail] Strict profile requires browser smoke. Remove --skip-browser-smoke.")
        return 2
    if full_contract and strict_from_profile and args.skip_hard_contract:
        finish_flow("startup_gate", "failed", "hard-contract-disabled-in-strict")
        print("[fail] Strict profile requires hard-contract gate. Remove --skip-hard-contract.")
        return 2
    if full_contract and strict_from_profile and args.skip_no_loop_stress:
        finish_flow("startup_gate", "failed", "no-loop-stress-disabled-in-strict")
        print("[fail] Strict profile requires no-loop stress gate. Remove --skip-no-loop-stress.")
        return 2

    api_key = _first_csv_token(args.api_key) or _first_csv_token(env.get("AEGIS_API_KEY"))
    files_key = _first_csv_token(args.files_api_key) or _first_csv_token(env.get("FILES_API_KEY")) or api_key
    admin_key = _first_csv_token(args.admin_api_key) or _first_csv_token(env.get("ADMIN_API_KEY"))

    if api_key:
        env["AEGIS_API_KEY"] = api_key
    if files_key:
        env["FILES_API_KEY"] = files_key
    if admin_key:
        env["ADMIN_API_KEY"] = admin_key

    errs, warns = _security_checks(api_key, files_key, strict_security)
    if warns:
        _print_block("security-warnings", warns)
    if errs:
        finish_flow("startup_gate", "failed", "security-errors")
        _print_block("security-errors", errs)
        return 2
    print(
        f"[profile] runtime={runtime_profile} track={product_track} contract={contract_mode} "
        f"strict_security={int(strict_security)} strict_capabilities={int(strict_capabilities)} "
        f"strict_browser_smoke={int(strict_browser_smoke)}"
    )

    host_errors, host_warns = _host_prereq_checks(host=args.host, port=args.port, env=env)
    if host_warns:
        _print_block("host-prereq-warnings", host_warns)
    if host_errors:
        mark_step("startup_gate", "host-prereq", "failed", "; ".join(host_errors[:2]))
        finish_flow("startup_gate", "failed", "host-prereq")
        _print_block("host-prereq-errors", host_errors)
        print("[fail] Host prerequisites failed. Server will not start.")
        return 2
    mark_step("startup_gate", "host-prereq", "passed", "ok")

    if not E2E_SCRIPT.exists():
        finish_flow("startup_gate", "failed", "missing-e2e-script")
        print(f"[fail] Missing E2E script at {E2E_SCRIPT}")
        return 2

    if full_contract and not args.skip_pytest_smoke:
        pytest_cmd = _pytest_smoke_cmd(args.pytest_smoke_tests)
        rc = _run_cmd(
            pytest_cmd,
            env=env,
            timeout=max(30, args.pytest_timeout),
            label="pytest-smoke",
        )
        if rc != 0:
            mark_step("startup_gate", "pytest-smoke", "failed", f"exit={rc}")
            finish_flow("startup_gate", "failed", "pytest-smoke")
            print("[fail] Pytest smoke checks failed. Server will not start.")
            return rc
        mark_step("startup_gate", "pytest-smoke", "passed", "ok")
    else:
        skip_reason = "skip-pytest-smoke" if args.skip_pytest_smoke else f"contract-mode={contract_mode}"
        mark_step("startup_gate", "pytest-smoke", "skipped", skip_reason)

    # Agent evals: deterministic internal heuristics/routing checks (fast).
    if not no_contract and AGENT_EVAL_SCRIPT.exists():
        rc = _run_cmd(
            [sys.executable, "-m", "app.scripts.agent_eval_check"],
            env=env,
            timeout=30,
            label="agent-evals",
        )
        if rc != 0:
            mark_step("startup_gate", "agent-evals", "failed", f"exit={rc}")
            finish_flow("startup_gate", "failed", "agent-evals")
            print("[fail] Agent eval checks failed. Server will not start.")
            return rc
        mark_step("startup_gate", "agent-evals", "passed", "ok")
    else:
        reason = "contract-mode=none" if no_contract else "missing-agent-eval-script"
        mark_step("startup_gate", "agent-evals", "skipped", reason)

    preflight_enabled = full_contract and not args.skip_preflight
    # In-process ASGI TestClient smoke can be flaky on some environments; keep it opt-in.
    if (os.getenv("AEGIS_ENABLE_INPROCESS_E2E", "0") or "0").strip().lower() not in {"1", "true", "yes", "on"}:
        preflight_enabled = False

    if preflight_enabled:
        pre_cmd = [
            sys.executable,
            str(E2E_SCRIPT),
            "--inprocess",
            "--api-key",
            api_key,
            "--files-api-key",
            files_key,
            "--timeout",
            str(max(30, args.e2e_timeout)),
            "--skip-ingest",
            "--skip-system",
            "--skip-crypto",
        ]
        rc = _run_cmd(pre_cmd, env=env, timeout=max(30, args.preflight_timeout), label="preflight-e2e(inprocess)")
        if rc != 0:
            mark_step("startup_gate", "preflight-e2e", "failed", f"exit={rc}")
            finish_flow("startup_gate", "failed", "preflight-e2e")
            print("[fail] Preflight checks failed. Server will not start.")
            return rc
        mark_step("startup_gate", "preflight-e2e", "passed", "ok")
    else:
        if not full_contract:
            reason = f"contract-mode={contract_mode}"
        else:
            reason = "skip-preflight" if args.skip_preflight else "AEGIS_ENABLE_INPROCESS_E2E=0"
        mark_step("startup_gate", "preflight-e2e", "skipped", reason)

    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        args.app,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--log-level",
        args.log_level,
    ]
    if args.reload:
        uvicorn_cmd.append("--reload")

    print(f"\n[start] {' '.join(uvicorn_cmd)}")
    proc = subprocess.Popen(uvicorn_cmd, env=env)

    base_url = args.check_base_url.strip()
    if not base_url:
        if args.host in {"0.0.0.0", "::"}:
            base_url = f"http://127.0.0.1:{args.port}"
        else:
            base_url = f"http://{args.host}:{args.port}"

    if not _wait_health(base_url, args.health_timeout, proc):
        mark_step("startup_gate", "healthz", "failed", "health-timeout")
        finish_flow("startup_gate", "failed", "healthz")
        print("[fail] Server did not become healthy in time.")
        _forward_signal(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except Exception:
            _forward_signal(proc, signal.SIGKILL)
        return 1
    mark_step("startup_gate", "healthz", "passed", "ok")

    # Guard against false-positive health checks when another process
    # is already bound to the same host/port.
    exit_code = proc.poll()
    if exit_code is not None:
        finish_flow("startup_gate", "failed", f"uvicorn-exited:{exit_code}")
        print(
            f"[fail] Managed uvicorn process exited early (code={exit_code}). "
            "Likely address already in use or startup crash."
        )
        return 1

    if full_contract and not args.skip_post_e2e:
        e2e_cmd = [
            sys.executable,
            str(E2E_SCRIPT),
            "--base-url",
            base_url,
            "--api-key",
            api_key,
            "--files-api-key",
            files_key,
            "--timeout",
            str(max(30, args.e2e_timeout)),
        ]
        if strict_capabilities:
            e2e_cmd.append("--strict-capabilities")
        rc = _run_cmd(e2e_cmd, env=env, timeout=max(60, args.e2e_timeout * 3), label="post-start-e2e(host)")
        if rc != 0:
            mark_step("startup_gate", "host-e2e", "failed", f"exit={rc}")
            finish_flow("startup_gate", "failed", "host-e2e")
            print("[fail] Post-start E2E failed. Stopping server.")
            _forward_signal(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except Exception:
                _forward_signal(proc, signal.SIGKILL)
            return rc
        mark_step("startup_gate", "host-e2e", "passed", "ok")

        ok, detail, readyz_data = _check_readyz(
            base_url,
            api_key,
            strict=strict_capabilities,
            product_track=product_track,
        )
        if not ok:
            mark_step("startup_gate", "readyz", "failed", detail)
            finish_flow("startup_gate", "failed", "readyz")
            print(f"[fail] {detail}")
            _print_block("readyz-failure", _readyz_debug_lines(base_url, readyz_data))
            _forward_signal(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except Exception:
                _forward_signal(proc, signal.SIGKILL)
            return 1
        mark_step("startup_gate", "readyz", "passed", detail)
        print(f"[ok] {detail}")
        try:
            if isinstance(readyz_data, dict):
                status = str(readyz_data.get("status") or "unknown")
                reasons = readyz_data.get("degraded_reasons") or []
                web_level = str(((readyz_data.get("web_search") or {}) if isinstance(readyz_data.get("web_search"), dict) else {}).get("status") or "")
                img_level = str(((readyz_data.get("image") or {}) if isinstance(readyz_data.get("image"), dict) else {}).get("status") or "")
                print("\n[demo-status]")
                print(f"- url: {base_url}")
                print(f"- readyz.status: {status}")
                if web_level:
                    print(f"- web_search: {web_level}")
                if img_level:
                    print(f"- image: {img_level}")
                if isinstance(reasons, list) and reasons:
                    joined = ", ".join(str(x) for x in reasons[:6] if str(x).strip())
                    if joined:
                        print(f"- degraded_reasons: {joined}")
        except Exception:
            pass

        if not args.skip_ui_contract and UI_CONTRACT_SCRIPT.exists():
            rc = _run_cmd(
                [sys.executable, "-m", "app.scripts.ui_contract_check", "--base-url", base_url],
                env=env,
                timeout=30,
                label="ui-contract",
            )
            if rc != 0:
                mark_step("startup_gate", "ui-contract", "failed", f"exit={rc}")
                finish_flow("startup_gate", "failed", "ui-contract")
                print("[fail] UI contract check failed. Stopping server.")
                _forward_signal(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except Exception:
                    _forward_signal(proc, signal.SIGKILL)
                return rc
            mark_step("startup_gate", "ui-contract", "passed", "ok")
        else:
            mark_step(
                "startup_gate",
                "ui-contract",
                "skipped",
                "skip-ui-contract" if args.skip_ui_contract else "missing-ui-contract-script",
            )

        if not args.skip_hard_contract and HARD_CONTRACT_SCRIPT.exists():
            hard_contract_cmd = [
                sys.executable,
                "-m",
                "app.scripts.hard_contract_check",
                "--base-url",
                base_url,
                "--api-key",
                api_key,
                "--strict",
                "--run-no-loop",
                "--no-loop-runs",
                str(no_loop_runs),
                "--no-loop-request-timeout",
                str(no_loop_request_timeout),
                "--no-loop-max-seconds-per-run",
                str(no_loop_max_seconds_per_run),
                "--max-no-loop-failures",
                str(max_no_loop_failures),
                "--no-loop-auth-edge-every",
                str(no_loop_auth_edge_every),
                "--max-no-loop-auth-edge-unexpected-failures",
                str(max_no_loop_auth_edge_unexpected_failures),
                "--soak-startup-transport-grace",
                str(soak_startup_transport_grace),
                "--soak-min-route-attempt-ticks",
                str(soak_min_route_attempt_ticks),
                "--soak-chat-timeout-seconds",
                str(soak_chat_timeout_seconds),
            ]
            if no_loop_auth_edge_invalid_key:
                hard_contract_cmd.extend(["--no-loop-auth-edge-invalid-key", no_loop_auth_edge_invalid_key])
            rc = _run_cmd(
                hard_contract_cmd,
                env=env,
                timeout=max(30, args.hard_contract_timeout),
                label="hard-contract",
            )
            if rc != 0:
                mark_step("startup_gate", "hard-contract", "failed", f"exit={rc}")
                finish_flow("startup_gate", "failed", "hard-contract")
                print("[fail] Hard contract gate failed. Stopping server.")
                _forward_signal(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except Exception:
                    _forward_signal(proc, signal.SIGKILL)
                return rc
            mark_step("startup_gate", "hard-contract", "passed", "ok")
        else:
            mark_step(
                "startup_gate",
                "hard-contract",
                "skipped",
                "skip-hard-contract" if args.skip_hard_contract else "missing-hard-contract-script",
            )

        if not args.skip_no_loop_stress and NO_LOOP_STRESS_SCRIPT.exists():
            no_loop_cmd = [
                sys.executable,
                "-m",
                "app.scripts.no_loop_stress_check",
                "--base-url",
                base_url,
                "--api-key",
                api_key,
                "--runs",
                str(no_loop_runs),
                "--request-timeout",
                str(no_loop_request_timeout),
                "--max-seconds-per-run",
                str(no_loop_max_seconds_per_run),
                "--max-failures",
                str(max_no_loop_failures),
                "--auth-edge-every",
                str(no_loop_auth_edge_every),
                "--max-auth-edge-unexpected-failures",
                str(max_no_loop_auth_edge_unexpected_failures),
            ]
            if no_loop_auth_edge_invalid_key:
                no_loop_cmd.extend(["--auth-edge-invalid-key", no_loop_auth_edge_invalid_key])
            rc = _run_cmd(
                no_loop_cmd,
                env=env,
                timeout=max(30, int(args.no_loop_timeout)),
                label="no-loop-stress",
            )
            if rc != 0:
                mark_step("startup_gate", "no-loop-stress", "failed", f"exit={rc}")
                finish_flow("startup_gate", "failed", "no-loop-stress")
                print("[fail] No-loop stress gate failed. Stopping server.")
                _forward_signal(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except Exception:
                    _forward_signal(proc, signal.SIGKILL)
                return rc
            mark_step("startup_gate", "no-loop-stress", "passed", "ok")
        else:
            if strict_from_profile and not args.skip_no_loop_stress:
                mark_step("startup_gate", "no-loop-stress", "failed", "missing-no-loop-stress-script")
                finish_flow("startup_gate", "failed", "no-loop-stress")
                print("[fail] Strict profile requires no-loop stress script, but it is missing.")
                _forward_signal(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except Exception:
                    _forward_signal(proc, signal.SIGKILL)
                return 2
            mark_step(
                "startup_gate",
                "no-loop-stress",
                "skipped",
                "skip-no-loop-stress" if args.skip_no_loop_stress else "missing-no-loop-stress-script",
            )

        browser_smoke_cmd = ""
        if not args.skip_browser_smoke:
            browser_smoke_cmd = str(args.browser_smoke_cmd or "").strip() or _default_browser_smoke_cmd(
                base_url,
                api_key,
                files_key,
                strict=strict_browser_smoke,
            )
        if browser_smoke_cmd:
            rc = _run_shell_cmd(
                browser_smoke_cmd,
                env=env,
                timeout=max(30, args.browser_smoke_timeout),
                label="browser-smoke",
            )
            if rc != 0:
                if strict_browser_smoke:
                    mark_step("startup_gate", "browser-smoke", "failed", f"exit={rc}")
                    finish_flow("startup_gate", "failed", "browser-smoke")
                    print("[fail] Browser smoke failed. Stopping server.")
                    _forward_signal(proc, signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except Exception:
                        _forward_signal(proc, signal.SIGKILL)
                    return rc
                mark_step("startup_gate", "browser-smoke", "skipped", f"non-strict-exit={rc}")
                print("[warn] Browser smoke failed (non-strict). Keeping server running.")
            else:
                mark_step("startup_gate", "browser-smoke", "passed", "ok")
        else:
            if strict_browser_smoke:
                mark_step("startup_gate", "browser-smoke", "failed", "missing-browser-smoke-cmd")
                finish_flow("startup_gate", "failed", "browser-smoke")
                print("[fail] Strict browser smoke requested but no command is configured.")
                _forward_signal(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except Exception:
                    _forward_signal(proc, signal.SIGKILL)
                return 2
            mark_step("startup_gate", "browser-smoke", "skipped", "no-browser-smoke-cmd")
    else:
        post_skip_reason = "skip-post-e2e" if args.skip_post_e2e else f"contract-mode={contract_mode}"
        mark_step("startup_gate", "host-e2e", "skipped", post_skip_reason)

        if not no_contract:
            ok, detail, readyz_data = _check_readyz(
                base_url,
                api_key,
                strict=strict_capabilities,
                product_track=product_track,
            )
            if not ok:
                mark_step("startup_gate", "readyz", "failed", detail)
                finish_flow("startup_gate", "failed", "readyz")
                print(f"[fail] {detail}")
                _print_block("readyz-failure", _readyz_debug_lines(base_url, readyz_data))
                _forward_signal(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except Exception:
                    _forward_signal(proc, signal.SIGKILL)
                return 1
            mark_step("startup_gate", "readyz", "passed", detail)
            print(f"[ok] {detail}")

            if not args.skip_ui_contract and UI_CONTRACT_SCRIPT.exists():
                rc = _run_cmd(
                    [sys.executable, "-m", "app.scripts.ui_contract_check", "--base-url", base_url],
                    env=env,
                    timeout=30,
                    label="ui-contract",
                )
                if rc != 0:
                    mark_step("startup_gate", "ui-contract", "failed", f"exit={rc}")
                    finish_flow("startup_gate", "failed", "ui-contract")
                    print("[fail] UI contract check failed. Stopping server.")
                    _forward_signal(proc, signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except Exception:
                        _forward_signal(proc, signal.SIGKILL)
                    return rc
                mark_step("startup_gate", "ui-contract", "passed", "ok")
            else:
                mark_step(
                    "startup_gate",
                    "ui-contract",
                    "skipped",
                    "skip-ui-contract" if args.skip_ui_contract else "missing-ui-contract-script",
                )
        else:
            mark_step("startup_gate", "readyz", "skipped", f"contract-mode={contract_mode}")
            mark_step("startup_gate", "ui-contract", "skipped", f"contract-mode={contract_mode}")

        mark_step("startup_gate", "hard-contract", "skipped", f"contract-mode={contract_mode}")
        mark_step("startup_gate", "no-loop-stress", "skipped", f"contract-mode={contract_mode}")
        mark_step("startup_gate", "browser-smoke", "skipped", f"contract-mode={contract_mode}")

    finish_flow("startup_gate", "passed", "startup-gates-passed")
    print("[ok] Startup gates passed. Server is running.")
    try:
        print(f"[hint] Full verification (100% signal): python app/scripts/verify_full.py --base-url {base_url} --api-key <key> --files-api-key <key>")
        if contract_mode != "full":
            print(f"[hint] Current startup skipped full contract gates (contract={contract_mode}). Use --contract-mode full for release-grade startup checks.")
    except Exception:
        pass

    def _on_signal(sig: int, _frame) -> None:  # noqa: ANN001
        _forward_signal(proc, sig)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    return int(proc.wait())


if __name__ == "__main__":
    raise SystemExit(main())
