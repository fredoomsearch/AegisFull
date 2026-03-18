#!/usr/bin/env python3
from __future__ import annotations

"""
Runtime doctor for commercial readiness (Core vs Full tracks).

What it does:
- Runs lightweight install/runtime diagnostics against local env and optional live API.
- Evaluates pass/fail differently for Core and Full product tracks.

Why it exists:
- Give operators a deterministic post-install sanity check before demos/releases.
- Separate optional-host dependency failures (image/browser) from core assistant readiness.

Called from ->
- Manual operator checks (`python -m app.scripts.doctor`)
- Post-install checklist and release runbooks

Calls ->
- Env inspection + static script presence checks
- Optional HTTP checks (`/healthz`, `/system/readyz`)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from app.utils.network_helpers import probe_tcp_url
from app.utils.runtime_helpers import product_track_default as _product_track_default

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class CheckItem:
    name: str
    ok: bool
    detail: str
    track: str


def _first_csv_token(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split(",", 1)[0].strip()


def _check_script_exists(path: str, track: str = "core") -> CheckItem:
    p = ROOT / path
    return CheckItem(
        name=f"script:{path}",
        ok=p.exists() and p.is_file(),
        detail="ok" if p.exists() else "missing",
        track=track,
    )


def _probe_tcp_endpoint(url: str, timeout: float = 2.0) -> Tuple[bool, str]:
    return probe_tcp_url(url, timeout=max(0.5, float(timeout)))


def _browser_version(binary: str, timeout: int = 3) -> Tuple[bool, str]:
    try:
        res = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout)),
        )
        output = (res.stdout or res.stderr or "").strip()
        if res.returncode == 0:
            return True, output[:180] or "ok"
        return False, f"exit={res.returncode} {output[:180]}".strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _http_json(
    base_url: str,
    path: str,
    api_key: str,
    timeout: int,
    *,
    attempts: int = 1,
    backoff_seconds: float = 0.35,
) -> Tuple[bool, str, Optional[Dict[str, Any]], int]:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"X-API-Key": api_key} if api_key else {}
    tries = max(1, int(attempts))
    last_error = ""
    for idx in range(tries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            status = int(resp.status_code)
            if status >= 400:
                return False, f"http_{status}", None, status
            payload = resp.json() if "application/json" in (resp.headers.get("content-type", "").lower()) else {}
            if not isinstance(payload, dict):
                payload = {}
            return True, "ok", payload, status
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if idx + 1 < tries:
                time.sleep(max(0.05, float(backoff_seconds)))
    return False, last_error or "request-failed", None, 0


def _env_checks(track: str) -> List[CheckItem]:
    out: List[CheckItem] = []
    auth_mode = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()
    out.append(CheckItem("env:AEGIS_AUTH_MODE", auth_mode == "on", f"value={auth_mode}", "core"))

    api_key = _first_csv_token(os.getenv("AEGIS_API_KEY"))
    files_key = _first_csv_token(os.getenv("FILES_API_KEY"))
    out.append(CheckItem("env:AEGIS_API_KEY", bool(api_key), "present" if api_key else "missing", "core"))
    out.append(CheckItem("env:FILES_API_KEY", bool(files_key), "present" if files_key else "missing", "core"))

    runtime_profile = (os.getenv("AEGIS_RUNTIME_PROFILE", "standard") or "standard").strip().lower()
    out.append(CheckItem("env:AEGIS_RUNTIME_PROFILE", runtime_profile in {"standard", "strict"}, f"value={runtime_profile}", "core"))

    if track == "full":
        img_endpoint = (os.getenv("AEGIS_IMAGE_ENDPOINT", "") or "").strip()
        out.append(CheckItem("env:AEGIS_IMAGE_ENDPOINT", bool(img_endpoint), "present" if img_endpoint else "missing", "full"))
        if img_endpoint:
            image_ok, image_detail = _probe_tcp_endpoint(img_endpoint)
            out.append(CheckItem("env:AEGIS_IMAGE_ENDPOINT:reachable", image_ok, image_detail, "full"))

        browser = (os.getenv("AEGIS_BROWSER_BINARY", "") or "").strip()
        out.append(CheckItem("env:AEGIS_BROWSER_BINARY", bool(browser), "present" if browser else "missing", "full"))
        if browser:
            browser_path = Path(browser)
            browser_exec = browser_path.exists() and browser_path.is_file() and os.access(str(browser_path), os.X_OK)
            out.append(
                CheckItem(
                    "env:AEGIS_BROWSER_BINARY:executable",
                    browser_exec,
                    f"path={browser}",
                    "full",
                )
            )
            if browser_exec:
                version_ok, version_detail = _browser_version(browser)
                out.append(CheckItem("env:AEGIS_BROWSER_BINARY:version", version_ok, version_detail, "full"))
    return out


def _readyz_checks(readyz: Dict[str, Any], track: str) -> List[CheckItem]:
    out: List[CheckItem] = []
    status = str(readyz.get("status") or "").strip().lower()
    checks = readyz.get("checks") if isinstance(readyz.get("checks"), dict) else {}
    image_info = readyz.get("image") if isinstance(readyz.get("image"), dict) else {}
    browser_info = readyz.get("browser_runtime") if isinstance(readyz.get("browser_runtime"), dict) else {}
    alerts = None
    runtime_metrics = readyz.get("runtime_metrics")
    if isinstance(runtime_metrics, dict):
        alerts = runtime_metrics.get("alerts")

    # Core: allow degraded only if optional capabilities are the reason.
    if track == "core":
        core_ok = status in {"ready", "degraded"}
        out.append(CheckItem("readyz:status", core_ok, f"value={status or 'unknown'}", "core"))
        required = (
            "embeddings",
            "retrieval",
            "llm",
            "image_storage",
            "web_search",
            "clamav",
            "project_tools",
        )
        for key in required:
            out.append(CheckItem(f"readyz:check:{key}", bool(checks.get(key)), f"value={checks.get(key)}", "core"))
    else:
        out.append(CheckItem("readyz:status", status == "ready", f"value={status or 'unknown'}", "full"))
        for key in (
            "embeddings",
            "retrieval",
            "llm",
            "image_storage",
            "image_backend",
            "web_search",
            "clamav",
            "project_tools",
            "browser_runtime",
        ):
            out.append(CheckItem(f"readyz:check:{key}", bool(checks.get(key)), f"value={checks.get(key)}", "full"))

        if not bool(checks.get("image_backend")):
            image_error = str(
                image_info.get("backend_probe_error")
                or image_info.get("last_backend_error")
                or ""
            ).strip()
            image_error_short = image_error[:180] if image_error else ""
            image_detail = f"reachable={image_info.get('backend_reachable')}"
            if image_error_short:
                image_detail += f" error={image_error_short}"
            out.append(CheckItem("readyz:image_backend_detail", False, image_detail, "full"))

        if not bool(checks.get("browser_runtime")):
            out.append(
                CheckItem(
                    "readyz:browser_runtime_detail",
                    False,
                    f"binary={browser_info.get('binary') or 'missing'}",
                    "full",
                )
            )

    if isinstance(alerts, dict):
        out.append(CheckItem("readyz:runtime_alerts", bool(alerts.get("ok", True)), f"value={alerts.get('ok')}", track))
    return out


def _script_checks(track: str) -> List[CheckItem]:
    items = [
        _check_script_exists("app/scripts/start_with_preflight.py", "core"),
        _check_script_exists("app/scripts/verify_full.py", "core"),
        _check_script_exists("app/scripts/hard_contract_check.py", "core"),
        _check_script_exists("app/scripts/no_loop_stress_check.py", "core"),
        _check_script_exists("app/scripts/adversarial_eval_check.py", "core"),
    ]
    if track == "full":
        items.append(_check_script_exists("app/scripts/browser_smoke.py", "full"))
    return items


def _evaluate(items: List[CheckItem], track: str) -> Dict[str, Any]:
    relevant = [c for c in items if c.track in {"core", track}]
    failed = [c for c in relevant if not c.ok]
    return {
        "ok": not failed,
        "track": track,
        "total": len(relevant),
        "passed": len(relevant) - len(failed),
        "failed": len(failed),
        "checks": [asdict(c) for c in relevant],
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AEGIS install/runtime doctor (Core vs Full).")
    p.add_argument(
        "--track",
        choices=["core", "full"],
        default=_product_track_default(),
        help="Product track to validate (defaults from AEGIS_PRODUCT_TRACK).",
    )
    p.add_argument("--base-url", default="", help="Optional live API base URL, e.g. http://127.0.0.1:8000")
    p.add_argument("--api-key", default=os.getenv("AEGIS_API_KEY", ""), help="API key for live checks (defaults from env).")
    p.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds for live checks.")
    p.add_argument("--attempts", type=int, default=2, help="HTTP attempts per live check.")
    p.add_argument("--json", action="store_true", help="Output JSON only.")
    return p.parse_args()


def _print_text(payload: Dict[str, Any], base_url: str) -> None:
    print(f"track={payload.get('track')} ok={payload.get('ok')}")
    print(f"checks: {payload.get('passed')}/{payload.get('total')} passed")
    if base_url:
        print(f"live_base_url={base_url}")
    print("")
    for chk in payload.get("checks", []):
        status = "ok" if chk.get("ok") else "fail"
        print(f"[{status}] {chk.get('name')} ({chk.get('track')}): {chk.get('detail')}")

    print("")
    if payload.get("ok"):
        print("[ok] doctor passed")
    else:
        print("[fail] doctor found blockers")
        print("next:")
        print("- fix failed checks")
        print("- re-run: python -m app.scripts.doctor --track core --base-url http://127.0.0.1:8000")
        print("- for full: python -m app.scripts.doctor --track full --base-url http://127.0.0.1:8000")


def main() -> int:
    args = parse_args()
    track = str(args.track or "core").strip().lower()
    base_url = str(args.base_url or "").strip()
    api_key = _first_csv_token(args.api_key) or _first_csv_token(os.getenv("AEGIS_API_KEY"))

    checks: List[CheckItem] = []
    checks.extend(_env_checks(track))
    checks.extend(_script_checks(track))

    if base_url:
        ok_healthz, detail_healthz, _healthz, _ = _http_json(
            base_url,
            "/healthz",
            api_key,
            timeout=max(2, args.timeout),
            attempts=max(1, int(args.attempts)),
        )
        checks.append(CheckItem("http:/healthz", ok_healthz, detail_healthz, "core"))
        ok_readyz, detail_readyz, readyz_payload, _ = _http_json(
            base_url,
            "/system/readyz",
            api_key,
            timeout=max(2, args.timeout),
            attempts=max(1, int(args.attempts)),
        )
        checks.append(CheckItem("http:/system/readyz", ok_readyz, detail_readyz, "core"))
        if ok_readyz and isinstance(readyz_payload, dict):
            checks.extend(_readyz_checks(readyz_payload, track))

    payload = _evaluate(checks, track)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload, base_url)
    return 0 if bool(payload.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
