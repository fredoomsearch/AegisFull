#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import urlparse

from app.tools import find_brave_binary
from app.utils.network_helpers import probe_tcp_host_port
from app.utils.runtime_helpers import first_csv_token as _first_csv_token

_WEAK_KEYS = {"my-secret-key", "changeme", "change-me", "dev", "test", "password", "123456"}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str

    def as_dict(self) -> Dict[str, str | bool]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def _is_strong_key(value: str, *, min_len: int = 24) -> Tuple[bool, str]:
    key = str(value or "").strip()
    if not key:
        return False, "missing"
    if len(key) < min_len:
        return False, f"too_short:{len(key)}<{min_len}"
    if key.lower() in _WEAK_KEYS:
        return False, "weak-default"
    return True, "ok"


def _check_tcp_reachable(host: str, port: int, timeout: float = 2.5) -> Tuple[bool, str]:
    return probe_tcp_host_port(host, int(port), timeout=timeout)


def run_checks(*, require_browser: bool, require_image_endpoint: bool) -> Dict[str, object]:
    results: List[CheckResult] = []

    runtime_profile = (os.getenv("AEGIS_RUNTIME_PROFILE", "standard") or "standard").strip().lower()
    results.append(
        CheckResult(
            name="runtime_profile",
            ok=(runtime_profile == "strict"),
            detail=f"value={runtime_profile}",
        )
    )

    product_track = (os.getenv("AEGIS_PRODUCT_TRACK", "core") or "core").strip().lower()
    results.append(
        CheckResult(
            name="product_track",
            ok=(product_track == "full"),
            detail=f"value={product_track}",
        )
    )

    start_contract_mode = (os.getenv("AEGIS_START_CONTRACT_MODE", "full") or "full").strip().lower()
    results.append(
        CheckResult(
            name="start_contract_mode",
            ok=(start_contract_mode == "full"),
            detail=f"value={start_contract_mode}",
        )
    )

    auth_mode = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()
    results.append(CheckResult(name="auth_mode", ok=(auth_mode == "on"), detail=f"value={auth_mode}"))

    api_key = _first_csv_token(os.getenv("AEGIS_API_KEY"))
    files_key = _first_csv_token(os.getenv("FILES_API_KEY")) or api_key
    admin_key = _first_csv_token(os.getenv("ADMIN_API_KEY"))

    for name, value in (("AEGIS_API_KEY", api_key), ("FILES_API_KEY", files_key), ("ADMIN_API_KEY", admin_key)):
        ok, detail = _is_strong_key(value)
        results.append(CheckResult(name=name, ok=ok, detail=detail))

    cors = (os.getenv("AEGIS_CORS_ORIGINS", "*") or "*").strip()
    cors_has_wildcard = cors == "*" or "*" in [p.strip() for p in cors.split(",")]
    results.append(CheckResult(name="cors_origins", ok=not cors_has_wildcard, detail=f"value={cors}"))

    hsts_raw = (os.getenv("AEGIS_HSTS_SECONDS", "0") or "0").strip()
    try:
        hsts = int(hsts_raw or "0")
    except Exception:
        hsts = 0
    results.append(CheckResult(name="hsts_seconds", ok=hsts > 0, detail=f"value={hsts}"))

    av_fail_open = (os.getenv("FILES_AV_FAIL_OPEN", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
    results.append(CheckResult(name="av_fail_open", ok=not av_fail_open, detail=f"value={int(av_fail_open)}"))

    if require_browser:
        browser = find_brave_binary()
        results.append(CheckResult(name="browser_binary", ok=bool(browser), detail=(browser or "not-found")))
    else:
        results.append(CheckResult(name="browser_binary", ok=True, detail="not-required"))

    image_endpoint = (os.getenv("AEGIS_IMAGE_ENDPOINT", "") or "").strip()
    if require_image_endpoint:
        if not image_endpoint:
            results.append(CheckResult(name="image_endpoint", ok=False, detail="missing"))
        else:
            parsed = urlparse(image_endpoint)
            host = str(parsed.hostname or "").strip()
            port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
            if not host:
                results.append(CheckResult(name="image_endpoint", ok=False, detail=f"invalid:{image_endpoint}"))
            else:
                ok, detail = _check_tcp_reachable(host, port)
                results.append(CheckResult(name="image_endpoint", ok=ok, detail=(detail if ok else f"unreachable:{detail}")))
    else:
        results.append(CheckResult(name="image_endpoint", ok=True, detail="not-required"))

    failed = [r.as_dict() for r in results if not r.ok]
    payload = {
        "ok": not failed,
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "checks": [r.as_dict() for r in results],
    }
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check production/strict runtime profile prerequisites.")
    p.add_argument("--require-browser", action="store_true", help="Require a Chromium-compatible browser binary.")
    p.add_argument("--require-image-endpoint", action="store_true", help="Require reachable AEGIS_IMAGE_ENDPOINT host:port.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = run_checks(
        require_browser=bool(args.require_browser),
        require_image_endpoint=bool(args.require_image_endpoint),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if bool(payload.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
