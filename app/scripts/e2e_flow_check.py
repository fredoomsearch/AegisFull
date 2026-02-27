#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class Transport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: float = 30.0,
    ):
        raise NotImplementedError


class RequestsTransport(Transport):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: float = 30.0,
    ):
        return requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body if files is None else None,
            files=files,
            params=params,
            timeout=timeout,
        )


class InProcessTransport(Transport):
    def __init__(self, client) -> None:
        self._client = client

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: float = 30.0,
    ):
        # TestClient runs in-process; explicit timeout is handled by the client stack.
        return self._client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body if files is None else None,
            files=files,
            params=params,
        )


@dataclass
class ClientCtx:
    base_url: str
    timeout: float
    api_key: str
    files_api_key: str
    transport: Transport
    access_token: str = ""
    refresh_token: str = ""
    uploaded_path: str = ""

    def _headers(self, *, files_scope: bool = False, json_body: bool = True) -> Dict[str, str]:
        out: Dict[str, str] = {}
        key = self.files_api_key if files_scope else self.api_key
        if key:
            out["X-API-Key"] = key
        if self.access_token:
            out["Authorization"] = f"Bearer {self.access_token}"
        if json_body:
            out["Content-Type"] = "application/json"
        return out

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        params: Optional[dict] = None,
        files_scope: bool = False,
    ) -> requests.Response:
        url = f"{self.base_url.rstrip('/')}{path}"
        headers = self._headers(files_scope=files_scope, json_body=files is None)
        return self.transport.request(
            method=method,
            url=url,
            headers=headers,
            json_body=json_body if files is None else None,
            files=files,
            params=params,
            timeout=self.timeout,
        )


def _json_or_text(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return (resp.text or "").strip()[:300]


def _print_ok(name: str, detail: str = "") -> None:
    suffix = f" | {detail}" if detail else ""
    print(f"[ok]   {name}{suffix}")


def _print_fail(name: str, detail: str = "") -> None:
    suffix = f" | {detail}" if detail else ""
    print(f"[fail] {name}{suffix}")


def check_health(ctx: ClientCtx) -> bool:
    r = ctx.request("GET", "/healthz", json_body=None)
    data = _json_or_text(r)
    if r.status_code == 200 and isinstance(data, dict) and data.get("status") == "ok":
        _print_ok("healthz", f"version={data.get('version')}")
        return True
    _print_fail("healthz", f"status={r.status_code} body={data}")
    return False


def check_auth_token(ctx: ClientCtx) -> bool:
    if not ctx.api_key:
        _print_ok("auth/token", "skipped (no --api-key provided)")
        return True

    body = {"scopes": ["chat", "files", "crypto", "admin"], "refresh": True}
    r = ctx.request("POST", "/auth/token", json_body=body)
    data = _json_or_text(r)
    if r.status_code == 200 and isinstance(data, dict) and data.get("access_token"):
        ctx.access_token = str(data.get("access_token") or "")
        ctx.refresh_token = str(data.get("refresh_token") or "")
        _print_ok("auth/token", "token issued")
        return True
    _print_fail("auth/token", f"status={r.status_code} body={data}")
    return False


def check_chat(ctx: ClientCtx) -> bool:
    # Use deterministic fast-path response (time helper) to avoid heavy LLM latency in smoke runs.
    body = {"message": "what time is it in new york?", "lang": "en", "mode": "chat"}
    r = ctx.request("POST", "/chat", json_body=body)
    data = _json_or_text(r)
    if r.status_code == 200 and isinstance(data, dict) and data.get("response"):
        _print_ok("chat", f"conv={str(data.get('conversation_id') or '')[:8]}")
        return True
    _print_fail("chat", f"status={r.status_code} body={data}")
    return False


def check_image(ctx: ClientCtx) -> bool:
    body = {"prompt": "health-check image", "steps": 10}
    r = ctx.request("POST", "/image/generate", json_body=body, files_scope=True)
    data = _json_or_text(r)
    if r.status_code != 200 or not isinstance(data, dict) or not data.get("image_path"):
        _print_fail("image/generate", f"status={r.status_code} body={data}")
        return False
    _print_ok("image/generate", f"path={data.get('image_path')}")

    r2 = ctx.request("GET", "/image/recent", json_body=None, files_scope=True)
    data2 = _json_or_text(r2)
    if r2.status_code == 200 and isinstance(data2, list):
        _print_ok("image/recent", f"items={len(data2)}")
        return True
    _print_fail("image/recent", f"status={r2.status_code} body={data2}")
    return False


def _build_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", "# E2E\nsample\n")
        zf.writestr("app/main.py", "print('ok')\n")
        zf.writestr("data/sample.csv", "a,b\n1,2\n")
    return buf.getvalue()


def check_upload_and_ingest(ctx: ClientCtx) -> bool:
    zip_bytes = _build_zip_bytes()
    files = {"file": ("e2e_repo.zip", zip_bytes, "application/zip")}
    r = ctx.request(
        "POST",
        "/files/upload-zip",
        files=files,
        params={"project_name": f"e2e_smoke_{int(time.time())}"},
        files_scope=True,
    )
    data = _json_or_text(r)
    if r.status_code != 200 or not isinstance(data, dict) or not data.get("path"):
        _print_fail("files/upload-zip", f"status={r.status_code} body={data}")
        return False

    ctx.uploaded_path = str(data.get("path") or "")
    _print_ok("files/upload-zip", f"path={ctx.uploaded_path}")

    r2 = ctx.request(
        "POST",
        "/files/ingest",
        json_body={"path": ctx.uploaded_path, "background": False},
        files_scope=True,
    )
    data2 = _json_or_text(r2)
    if r2.status_code == 200 and isinstance(data2, dict) and data2.get("status") == "ok":
        _print_ok("files/ingest", "ok")
        return True
    _print_fail("files/ingest", f"status={r2.status_code} body={data2}")
    return False


def check_system(ctx: ClientCtx) -> bool:
    r = ctx.request("GET", "/system/snapshot", json_body=None)
    data = _json_or_text(r)
    if r.status_code == 200 and isinstance(data, dict):
        _print_ok("system/snapshot", "ok")
    else:
        _print_fail("system/snapshot", f"status={r.status_code} body={data}")
        return False

    r2 = ctx.request("GET", "/system/readyz", json_body=None)
    data2 = _json_or_text(r2)
    if r2.status_code == 200 and isinstance(data2, dict):
        _print_ok("system/readyz", f"ready={data2.get('ready')}")
        return True
    _print_fail("system/readyz", f"status={r2.status_code} body={data2}")
    return False


def check_crypto(ctx: ClientCtx) -> bool:
    ok = True
    checks = [
        ("GET", "/crypto/models", None),
        ("GET", "/crypto/ohlcv", {"symbol": "BTCUSDT", "interval": "1m", "limit": 60}),
        ("GET", "/crypto/news", {"symbol": "BTCUSDT"}),
    ]
    for method, path, params in checks:
        r = ctx.request(method, path, json_body=None, params=params)
        data = _json_or_text(r)
        if r.status_code == 200:
            _print_ok(path, "ok")
        else:
            _print_fail(path, f"status={r.status_code} body={data}")
            ok = False
    return ok


def cleanup(ctx: ClientCtx) -> None:
    if not ctx.uploaded_path:
        return
    try:
        r = ctx.request(
            "POST",
            "/tools/delete_project",
            json_body={"path": ctx.uploaded_path},
        )
        if r.status_code == 200:
            _print_ok("cleanup", "uploaded project removed")
        else:
            _print_fail("cleanup", f"status={r.status_code} body={_json_or_text(r)}")
    except Exception as exc:  # noqa: BLE001
        _print_fail("cleanup", str(exc))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AEGIS end-to-end flow smoke check")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--api-key", default="")
    p.add_argument("--files-api-key", default="")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--skip-auth", action="store_true")
    p.add_argument("--skip-chat", action="store_true")
    p.add_argument("--skip-image", action="store_true")
    p.add_argument("--skip-ingest", action="store_true")
    p.add_argument("--skip-system", action="store_true")
    p.add_argument("--skip-crypto", action="store_true")
    p.add_argument(
        "--inprocess",
        action="store_true",
        help="Run checks against ASGI app directly (no local TCP bind).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.inprocess:
        # Keep in-process smoke deterministic and lightweight.
        os.environ["AEGIS_DISABLE_DB"] = "1"
        os.environ["AEGIS_LLM_WARMUP"] = "0"
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

        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app, raise_server_exceptions=False)
        try:
            return _run_checks(args, base_url="", transport=InProcessTransport(client))
        finally:
            client.close()

    return _run_checks(args, base_url=args.base_url, transport=RequestsTransport())


def _run_checks(args: argparse.Namespace, *, base_url: str, transport: Transport) -> int:
    ctx = ClientCtx(
        base_url=base_url,
        timeout=float(args.timeout),
        api_key=(args.api_key or "").strip(),
        files_api_key=(args.files_api_key or args.api_key or "").strip(),
        transport=transport,
    )

    checks = [check_health]
    if not args.skip_auth:
        checks.append(check_auth_token)
    if not args.skip_chat:
        checks.append(check_chat)
    if not args.skip_image:
        checks.append(check_image)
    if not args.skip_ingest:
        checks.append(check_upload_and_ingest)
    if not args.skip_system:
        checks.append(check_system)
    if not args.skip_crypto:
        checks.append(check_crypto)

    ok = True
    for fn in checks:
        try:
            ok = fn(ctx) and ok
        except Exception as exc:  # noqa: BLE001
            _print_fail(fn.__name__, str(exc))
            ok = False

    cleanup(ctx)
    print(json.dumps({"ok": ok}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
