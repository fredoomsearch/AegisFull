#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parents[2]
E2E_SCRIPT = ROOT / "app" / "scripts" / "e2e_flow_check.py"

WEAK_KEYS = {"my-secret-key", "changeme", "change-me", "dev", "test", "password"}


def _first_csv_token(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    return value.split(",", 1)[0].strip().strip("\"'")


def _env_bool(name: str, default: bool = False) -> bool:
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


def _wait_health(base_url: str, timeout_s: int, child: subprocess.Popen) -> bool:
    deadline = time.time() + max(5, timeout_s)
    health_url = f"{base_url.rstrip('/')}/healthz"
    while time.time() < deadline:
        if child.poll() is not None:
            return False
        try:
            r = requests.get(health_url, timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _check_readyz(base_url: str, api_key: str) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/system/readyz"
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = requests.get(url, headers=headers, timeout=8)
    except Exception as exc:  # noqa: BLE001
        return False, f"readyz request failed: {exc}"
    if r.status_code != 200:
        return False, f"readyz status={r.status_code} body={(r.text or '')[:300]}"
    try:
        data = r.json()
    except Exception:
        return False, "readyz returned non-JSON body"
    if not bool(data.get("ready")):
        return False, f"readyz reports not ready: {data}"
    return True, "readyz ready=true"


def _security_checks(api_key: str, files_key: str, strict: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []

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
    if cors_origins == "*" or "*" in [p.strip() for p in cors_origins.split(",")]:
        warns.append("AEGIS_CORS_ORIGINS includes '*'")
    if av_fail_open:
        warns.append("FILES_AV_FAIL_OPEN=1 (scanner timeout/error won't block upload)")
    if hsts_seconds <= 0:
        warns.append("AEGIS_HSTS_SECONDS=0 (HSTS disabled)")

    if strict and warns:
        errors.extend([f"[strict] {w}" for w in warns])

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

    p.add_argument("--skip-preflight", action="store_true")
    p.add_argument("--skip-post-e2e", action="store_true")
    p.add_argument("--strict-security", action="store_true")
    p.add_argument("--disable-db", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    env = os.environ.copy()

    if args.disable_db:
        env["AEGIS_DISABLE_DB"] = "1"

    api_key = _first_csv_token(args.api_key) or _first_csv_token(env.get("AEGIS_API_KEY"))
    files_key = _first_csv_token(args.files_api_key) or _first_csv_token(env.get("FILES_API_KEY")) or api_key
    admin_key = _first_csv_token(args.admin_api_key) or _first_csv_token(env.get("ADMIN_API_KEY"))

    if api_key:
        env["AEGIS_API_KEY"] = api_key
    if files_key:
        env["FILES_API_KEY"] = files_key
    if admin_key:
        env["ADMIN_API_KEY"] = admin_key

    errs, warns = _security_checks(api_key, files_key, args.strict_security)
    if warns:
        _print_block("security-warnings", warns)
    if errs:
        _print_block("security-errors", errs)
        return 2

    if not E2E_SCRIPT.exists():
        print(f"[fail] Missing E2E script at {E2E_SCRIPT}")
        return 2

    if not args.skip_preflight:
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
            "--skip-crypto",
        ]
        rc = _run_cmd(pre_cmd, env=env, timeout=max(30, args.preflight_timeout), label="preflight-e2e(inprocess)")
        if rc != 0:
            print("[fail] Preflight checks failed. Server will not start.")
            return rc

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
        print("[fail] Server did not become healthy in time.")
        _forward_signal(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except Exception:
            _forward_signal(proc, signal.SIGKILL)
        return 1

    # Guard against false-positive health checks when another process
    # is already bound to the same host/port.
    exit_code = proc.poll()
    if exit_code is not None:
        print(
            f"[fail] Managed uvicorn process exited early (code={exit_code}). "
            "Likely address already in use or startup crash."
        )
        return 1

    if not args.skip_post_e2e:
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
        rc = _run_cmd(e2e_cmd, env=env, timeout=max(60, args.e2e_timeout * 3), label="post-start-e2e(host)")
        if rc != 0:
            print("[fail] Post-start E2E failed. Stopping server.")
            _forward_signal(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except Exception:
                _forward_signal(proc, signal.SIGKILL)
            return rc

        ok, detail = _check_readyz(base_url, api_key)
        if not ok:
            print(f"[fail] {detail}")
            _forward_signal(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except Exception:
                _forward_signal(proc, signal.SIGKILL)
            return 1
        print(f"[ok] {detail}")

    print("[ok] Startup gates passed. Server is running.")

    def _on_signal(sig: int, _frame) -> None:  # noqa: ANN001
        _forward_signal(proc, sig)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    return int(proc.wait())


if __name__ == "__main__":
    raise SystemExit(main())
