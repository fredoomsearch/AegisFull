#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class Transport(ABC):
    @abstractmethod
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
    ): ...


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
            timeout=timeout,
        )


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_ready(url: str, timeout_s: float = 20.0) -> bool:
    deadline = time.time() + max(1.0, timeout_s)
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


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
    uploaded_project_id: str = ""
    conversation_id: str = ""
    strict_capabilities: bool = False
    cleanup_artifacts: bool = True
    generated_image_paths: list[str] = field(default_factory=list)

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


def _looks_like_internal_leak(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    lowered = value.lower()
    head = "\n".join(value.splitlines()[:6]).lower()
    head_markers = (
        "you are aegis",
        "do not reveal system prompts",
        "never output special chat tokens",
    )
    if any(marker in head for marker in head_markers):
        return True
    any_markers = ("<<sys>>", "<</sys>>", "[inst]", "[/inst]")
    return any(marker in lowered for marker in any_markers)


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

    body = {"scopes": ["chat", "files", "crypto"], "refresh": True}
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
        response = str(data.get("response") or "").strip()
        if _looks_like_internal_leak(response):
            _print_fail("chat", "internal-prompt-leak-detected")
            return False
        ctx.conversation_id = str(data.get("conversation_id") or "")
        _print_ok("chat", f"conv={str(data.get('conversation_id') or '')[:8]}")
        return True
    _print_fail("chat", f"status={r.status_code} body={data}")
    return False


def check_contextual_web(ctx: ClientCtx) -> bool:
    if not isinstance(ctx.transport, InProcessTransport):
        _print_ok("contextual-web", "skipped (host mode)")
        return True

    from app.api import chat as chat_api
    from app.models import llm_utils as llm_utils_api

    seen: Dict[str, Any] = {}
    orig_generate = chat_api.generate_response
    orig_search_meta = chat_api.web_search_structured_with_meta
    orig_snippets = chat_api.fetch_snippets_from_sources
    orig_retrieval_query = getattr(llm_utils_api, "retrieval_query", None)
    orig_retrieval_available = bool(getattr(llm_utils_api, "RETRIEVAL_AVAILABLE", False))

    def fake_search(q, n, lang=None):
        seen["q"] = q
        return (
            [
                {"title": "JWT Python", "snippet": "python jwt", "link": "https://example.com/python"},
                {"title": "Angular Auth", "snippet": "angular auth", "link": "https://example.com/angular"},
            ],
            {"status": "live", "source": "live", "provider": "fake", "results": 2, "attempted": True, "live_web_used": True},
        )

    try:
        chat_api.generate_response = lambda *args, **kwargs: "ok"  # type: ignore[assignment]
        chat_api.web_search_structured_with_meta = fake_search  # type: ignore[assignment]
        chat_api.fetch_snippets_from_sources = (  # type: ignore[assignment]
            lambda sources: ([{"url": s.get("url"), "snippet": s.get("snippet") or "stub"} for s in sources], [])
        )
        llm_utils_api.retrieval_query = lambda *args, **kwargs: []  # type: ignore[assignment]
        llm_utils_api.RETRIEVAL_AVAILABLE = False  # type: ignore[assignment]

        first = ctx.request(
            "POST",
            "/chat",
            json_body={"message": "I am building a login page with Angular frontend and Python backend", "lang": "en"},
        )
        data1 = _json_or_text(first)
        if first.status_code != 200 or not isinstance(data1, dict) or not data1.get("conversation_id"):
            _print_fail("contextual-web", f"seed status={first.status_code} body={data1}")
            return False

        conv_id = str(data1.get("conversation_id"))
        second = ctx.request(
            "POST",
            "/chat",
            json_body={
                "message": "best JWT library?",
                "lang": "en",
                "mode": "web",
                "conversation_id": conv_id,
                "use_existing": True,
            },
        )
        data2 = _json_or_text(second)
        query = str(seen.get("q") or "").lower()
        context = (data2 or {}).get("context") if isinstance(data2, dict) else None
        if (
            second.status_code == 200
            and "login" in query
            and "angular" in query
            and "python" in query
            and isinstance(context, dict)
            and bool(context.get("using_live_web"))
            and str(context.get("web_source") or "") == "live"
        ):
            _print_ok("contextual-web", query)
            return True
        _print_fail("contextual-web", f"status={second.status_code} query={query!r} body={data2}")
        return False
    finally:
        chat_api.generate_response = orig_generate  # type: ignore[assignment]
        chat_api.web_search_structured_with_meta = orig_search_meta  # type: ignore[assignment]
        chat_api.fetch_snippets_from_sources = orig_snippets  # type: ignore[assignment]
        llm_utils_api.retrieval_query = orig_retrieval_query  # type: ignore[assignment]
        llm_utils_api.RETRIEVAL_AVAILABLE = orig_retrieval_available  # type: ignore[assignment]


def check_image(ctx: ClientCtx) -> bool:
    # Keep image request lightweight so strict checks are stable on CPU-only hosts.
    body = {
        "prompt": "health-check image",
        "steps": 3,
        "width": 256,
        "height": 256,
        "cfg": 4.0,
        "seed": 7,
    }
    r = ctx.request("POST", "/image/generate", json_body=body, files_scope=True)
    data = _json_or_text(r)
    if r.status_code != 200 or not isinstance(data, dict) or not data.get("image_path"):
        _print_fail("image/generate", f"status={r.status_code} body={data}")
        return False
    fallback_used = bool(data.get("fallback_used"))
    backend_ok = bool(data.get("backend_ok"))
    image_path = str(data.get("image_path") or "").strip()
    if image_path:
        ctx.generated_image_paths.append(image_path)
    if ctx.strict_capabilities and (fallback_used or not backend_ok):
        _print_fail("image/generate", f"fallback-only path={data.get('image_path')} error={data.get('backend_error')}")
        return False
    mode = "fallback-only" if fallback_used else "backend"
    _print_ok("image/generate", f"{mode} path={data.get('image_path')}")

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
        zf.writestr("README.md", "# E2E\nFastAPI-style auth sample project.\n")
        zf.writestr("requirements.txt", "fastapi\nuvicorn\n")
        zf.writestr(
            "app/auth.py",
            "class AuthService:\n"
            "    def login(self, user):\n"
            "        return user\n\n"
            "def refresh_token(token):\n"
            "    return token\n",
        )
        zf.writestr("tests/test_auth.py", "def test_login():\n    assert True\n")
        zf.writestr("data/sample.csv", "a,b\n1,2\n")
    return buf.getvalue()


def _is_av_timeout_upload_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    detail = str(payload.get("detail") or "").strip().lower()
    error_obj = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    message = str(error_obj.get("message") or "").strip().lower()
    joined = f"{detail} {message}".strip()
    return "av scan timed out" in joined


def check_upload_and_ingest(ctx: ClientCtx) -> bool:
    zip_bytes = _build_zip_bytes()
    files = {"file": ("e2e_repo.zip", zip_bytes, "application/zip")}
    data: Any = {}
    for attempt in range(2):
        r = ctx.request(
            "POST",
            "/files/upload-zip",
            files=files,
            params={"project_name": f"e2e_smoke_{int(time.time())}"},
            files_scope=True,
        )
        data = _json_or_text(r)
        if r.status_code == 200 and isinstance(data, dict) and data.get("path"):
            break
        is_timeout = r.status_code in {400, 504} and _is_av_timeout_upload_error(data)
        if is_timeout and attempt == 0:
            _print_fail("files/upload-zip", "AV timeout on first attempt, retrying once")
            time.sleep(0.4)
            continue
        _print_fail("files/upload-zip", f"status={r.status_code} body={data}")
        return False

    ctx.uploaded_path = str(data.get("path") or "")
    ctx.uploaded_project_id = str(data.get("project_id") or "")
    _print_ok("files/upload-zip", f"path={ctx.uploaded_path}")

    r2 = ctx.request(
        "POST",
        "/files/ingest",
        json_body={"path": ctx.uploaded_path, "background": False},
        files_scope=True,
    )
    data2 = _json_or_text(r2)
    if r2.status_code == 200 and isinstance(data2, dict) and data2.get("status") == "ok":
        if str(data2.get("project_id") or ""):
            ctx.uploaded_project_id = str(data2.get("project_id") or "")
        _print_ok("files/ingest", f"project_id={ctx.uploaded_project_id or '?'}")
        return True
    _print_fail("files/ingest", f"status={r2.status_code} body={data2}")
    return False


def check_project_context(ctx: ClientCtx) -> bool:
    if not ctx.uploaded_project_id:
        _print_fail("project-context", "missing uploaded_project_id")
        return False
    if not ctx.conversation_id:
        _print_fail("project-context", "missing conversation_id")
        return False

    r1 = ctx.request("GET", f"/files/projects/{ctx.uploaded_project_id}", json_body=None, files_scope=True, params={"lang": "en"})
    data1 = _json_or_text(r1)
    if r1.status_code != 200 or not isinstance(data1, dict) or not data1.get("manifest"):
        _print_fail("files/projects/{id}", f"status={r1.status_code} body={data1}")
        return False

    r1c = ctx.request("GET", f"/files/projects/{ctx.uploaded_project_id}/entrypoints", json_body=None, files_scope=True)
    data1c = _json_or_text(r1c)
    if r1c.status_code != 200 or not isinstance(data1c, dict):
        _print_fail("files/projects/{id}/entrypoints", f"status={r1c.status_code} body={data1c}")
        return False

    r1d = ctx.request("GET", f"/files/projects/{ctx.uploaded_project_id}/dependencies", json_body=None, files_scope=True)
    data1d = _json_or_text(r1d)
    if r1d.status_code != 200 or not isinstance(data1d, dict):
        _print_fail("files/projects/{id}/dependencies", f"status={r1d.status_code} body={data1d}")
        return False

    r1e = ctx.request("GET", f"/files/projects/{ctx.uploaded_project_id}/configs", json_body=None, files_scope=True)
    data1e = _json_or_text(r1e)
    if r1e.status_code != 200 or not isinstance(data1e, dict):
        _print_fail("files/projects/{id}/configs", f"status={r1e.status_code} body={data1e}")
        return False

    r1h = ctx.request(
        "GET",
        f"/files/projects/{ctx.uploaded_project_id}/architecture",
        json_body=None,
        files_scope=True,
        params={"lang": "en"},
    )
    data1h = _json_or_text(r1h)
    if (
        r1h.status_code != 200
        or not isinstance(data1h, dict)
        or not isinstance(data1h.get("architecture"), dict)
        or not str(data1h.get("summary") or "").strip()
    ):
        _print_fail("files/projects/{id}/architecture", f"status={r1h.status_code} body={data1h}")
        return False

    r1b = ctx.request(
        "GET",
        f"/files/projects/{ctx.uploaded_project_id}/symbols",
        json_body=None,
        files_scope=True,
        params={"q": "auth", "limit": 20},
    )
    data1b = _json_or_text(r1b)
    if r1b.status_code != 200 or not isinstance(data1b, dict) or str(data1b.get("status") or "") != "ok":
        _print_fail("files/projects/{id}/symbols", f"status={r1b.status_code} body={data1b}")
        return False
    # Symbol search can be legitimately empty depending on uploaded project contents.
    items = data1b.get("items") or []
    if not items:
        _print_ok("files/projects/{id}/symbols", "ok (no matches)")
    else:
        _print_ok("files/projects/{id}/symbols", f"items={len(items)}")

    r1f = ctx.request(
        "GET",
        "/files/tree",
        json_body=None,
        files_scope=True,
        params={"project_id": ctx.uploaded_project_id, "max_depth": 3},
    )
    data1f = _json_or_text(r1f)
    if r1f.status_code != 200 or not isinstance(data1f, dict):
        _print_fail("files/tree", f"status={r1f.status_code} body={data1f}")
        return False

    r1g = ctx.request(
        "GET",
        "/files/content",
        json_body=None,
        files_scope=True,
        params={"project_id": ctx.uploaded_project_id, "path": "app/auth.py"},
    )
    data1g = _json_or_text(r1g)
    if r1g.status_code != 200 or not isinstance(data1g, dict) or "AuthService" not in str(data1g.get("content") or ""):
        _print_fail("files/content", f"status={r1g.status_code} body={data1g}")
        return False

    r2 = ctx.request(
        "POST",
        f"/chat/{ctx.conversation_id}/project",
        json_body={"project_id": ctx.uploaded_project_id},
    )
    data2 = _json_or_text(r2)
    if r2.status_code != 200 or not isinstance(data2, dict):
        _print_fail("chat/project-bind", f"status={r2.status_code} body={data2}")
        return False

    r3 = ctx.request(
        "POST",
        "/chat",
        json_body={
            "message": "what does this project contain?",
            "lang": "en",
            "conversation_id": ctx.conversation_id,
            "use_existing": True,
        },
    )
    data3 = _json_or_text(r3)
    response = str((data3 or {}).get("response") or "") if isinstance(data3, dict) else ""
    context = (data3 or {}).get("context") if isinstance(data3, dict) else None
    source_origin = context.get("source_origin") if isinstance(context, dict) else []
    if _looks_like_internal_leak(response):
        _print_fail("project-context", "internal-prompt-leak-detected")
        return False
    if (
        r3.status_code == 200
        and ctx.uploaded_project_id.lower() in response.lower()
        and isinstance(context, dict)
        and str(context.get("active_project_id") or "") == ctx.uploaded_project_id
        and "manifest" in list(source_origin or [])
        and str(context.get("web_status") or "") == "not-used"
    ):
        r4 = ctx.request(
            "POST",
            f"/chat/{ctx.conversation_id}/agent_step",
            json_body={
                "message": "where is auth handled?",
                "lang": "en",
                "use_web": False,
                "max_tool_calls": 3,
                "synthesize": False,
            },
            files_scope=False,  # uses main API key; file-scope allows AEGIS_API_KEY as fallback
        )
        data4 = _json_or_text(r4)
        resp4 = str((data4 or {}).get("response") or "") if isinstance(data4, dict) else ""
        if r4.status_code != 200 or "auth" not in resp4.lower():
            _print_fail("agent_step", f"status={r4.status_code} body={data4}")
            return False
        _print_ok("agent_step", "ok")
        r5 = ctx.request(
            "POST",
            f"/chat/{ctx.conversation_id}/agent_run",
            json_body={
                "message": "where is auth handled?",
                "lang": "en",
                "use_web": False,
                "max_iterations": 2,
                "max_total_tool_calls": 6,
                "synthesize": False,
            },
            files_scope=False,
        )
        data5 = _json_or_text(r5)
        resp5 = str((data5 or {}).get("response") or "") if isinstance(data5, dict) else ""
        if r5.status_code != 200 or "auth" not in resp5.lower():
            _print_fail("agent_run", f"status={r5.status_code} body={data5}")
            return False
        _print_ok("agent_run", "ok")
        _print_ok("project-context", f"project={ctx.uploaded_project_id}")
        return True
    _print_fail("project-context", f"status={r3.status_code} body={data3}")
    return False


def check_turns_and_ops(ctx: ClientCtx) -> bool:
    if not ctx.conversation_id:
        _print_fail("chat/turns", "missing conversation_id")
        return False

    r1 = ctx.request("GET", f"/chat/{ctx.conversation_id}/turns", json_body=None)
    data1 = _json_or_text(r1)
    if r1.status_code != 200 or not isinstance(data1, dict) or not isinstance(data1.get("items"), list) or not data1.get("items"):
        _print_fail("chat/turns", f"status={r1.status_code} body={data1}")
        return False

    r2 = ctx.request("GET", "/files/av/status", json_body=None, files_scope=True)
    data2 = _json_or_text(r2)
    if r2.status_code != 200 or not isinstance(data2, dict) or not isinstance(data2.get("clamav"), dict):
        _print_fail("files/av/status", f"status={r2.status_code} body={data2}")
        return False

    r3 = ctx.request("GET", "/files/av/recent", json_body=None, files_scope=True, params={"limit": 5})
    data3 = _json_or_text(r3)
    if r3.status_code != 200 or not isinstance(data3, dict) or not isinstance(data3.get("items"), list):
        _print_fail("files/av/recent", f"status={r3.status_code} body={data3}")
        return False

    _print_ok("chat/turns", f"items={len(data1.get('items') or [])}")
    _print_ok("files/av/status", f"status={data2.get('clamav', {}).get('status')}")
    _print_ok("files/av/recent", f"items={len(data3.get('items') or [])}")
    return True


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
        status = str(data2.get("status") or "unknown")
        if ctx.strict_capabilities:
            ready = bool(data2.get("ready"))
            if not ready or status != "ready":
                _print_fail("system/readyz", f"status={status} body={data2}")
                return False
            image = data2.get("image") if isinstance(data2.get("image"), dict) else {}
            if str(image.get("status") or "") != "ready":
                _print_fail("system/readyz", f"image_status={image.get('status')} body={data2}")
                return False
        _print_ok("system/readyz", f"ready={data2.get('ready')} status={status}")

        # Strict project surface: legacy /tools endpoints must be gone (404) or explicitly 410.
        # This prevents drift between two competing project APIs.
        if ctx.strict_capabilities:
            r3 = ctx.request("GET", "/tools/tree", json_body=None)
            if r3.status_code not in {404, 410}:
                _print_fail("tools/legacy", f"expected 404/410 got {r3.status_code} body={_json_or_text(r3)}")
                return False
            _print_ok("tools/legacy", f"status={r3.status_code}")
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
    if ctx.uploaded_path:
        try:
            r = ctx.request(
                "POST",
                "/files/delete_project",
                json_body={"project_id": ctx.uploaded_project_id or None, "path": ctx.uploaded_path},
                files_scope=True,
            )
            if r.status_code == 200:
                _print_ok("cleanup", "uploaded project removed")
            else:
                _print_fail("cleanup", f"status={r.status_code} body={_json_or_text(r)}")
        except Exception as exc:  # noqa: BLE001
            _print_fail("cleanup", str(exc))
    if ctx.conversation_id:
        try:
            r = ctx.request("DELETE", f"/chat/{ctx.conversation_id}", json_body=None)
            if r.status_code in {200, 404}:
                _print_ok("cleanup-conversation", f"status={r.status_code}")
            else:
                _print_fail("cleanup-conversation", f"status={r.status_code} body={_json_or_text(r)}")
        except Exception as exc:  # noqa: BLE001
            _print_fail("cleanup-conversation", str(exc))
    if ctx.cleanup_artifacts:
        _cleanup_local_artifacts(ctx)


def _normalize_rel_path(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").lstrip("./")


def _resolve_data_image_path(raw_path: str) -> Optional[Path]:
    rel = _normalize_rel_path(raw_path)
    if not rel:
        return None
    candidate = Path(rel)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        resolved = candidate.resolve()
    except Exception:
        return None
    images_root = (ROOT / "data" / "images").resolve()
    try:
        resolved.relative_to(images_root)
    except Exception:
        return None
    return resolved


def _prune_image_log(log_file: Path, removed_rel_paths: set[str]) -> int:
    if not removed_rel_paths or not log_file.exists():
        return 0
    removed_lines = 0
    kept: list[str] = []
    try:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return 0
    for line in lines:
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            kept.append(raw)
            continue
        rel = _normalize_rel_path(str((row or {}).get("path") or ""))
        if rel in removed_rel_paths:
            removed_lines += 1
            continue
        kept.append(raw)
    try:
        if kept:
            log_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
        else:
            log_file.unlink(missing_ok=True)
    except Exception:
        return removed_lines
    return removed_lines


def _remove_conversation_turn_trace(conversation_id: str) -> int:
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        return 0
    removed = 0
    turns_root = ROOT / "data" / "conversation_turns"
    turns_file = turns_root / f"{conv_id}.json"
    turns_dir = turns_root / conv_id
    try:
        if turns_file.exists():
            turns_file.unlink()
            removed += 1
    except Exception:
        pass
    try:
        if turns_dir.exists() and turns_dir.is_dir():
            shutil.rmtree(turns_dir, ignore_errors=True)
            removed += 1
    except Exception:
        pass
    return removed


def _cleanup_local_artifacts(ctx: ClientCtx) -> None:
    removed_images = 0
    removed_turns = 0
    removed_log_rows = 0
    removed_memory_conv = 0
    removed_rel_paths: set[str] = set()

    for raw_path in list(ctx.generated_image_paths):
        resolved = _resolve_data_image_path(raw_path)
        if resolved is None:
            continue
        rel = _normalize_rel_path(str(resolved.relative_to(ROOT)))
        removed_rel_paths.add(rel)
        try:
            if resolved.exists():
                resolved.unlink()
                removed_images += 1
        except Exception:
            continue

    if removed_rel_paths:
        image_log_file = ROOT / "data" / "images" / "log.jsonl"
        removed_log_rows = _prune_image_log(image_log_file, removed_rel_paths)

    if ctx.conversation_id:
        removed_turns = _remove_conversation_turn_trace(ctx.conversation_id)

        conversations_file = ROOT / "data" / "conversations.json"
        try:
            if conversations_file.exists():
                payload = json.loads(conversations_file.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(payload, dict) and str(ctx.conversation_id) in payload:
                    payload.pop(str(ctx.conversation_id), None)
                    conversations_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    removed_memory_conv = 1
        except Exception:
            removed_memory_conv = 0

    _print_ok(
        "cleanup-local",
        f"images={removed_images} log_rows={removed_log_rows} turns={removed_turns} conversations={removed_memory_conv}",
    )


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
    p.add_argument(
        "--strict-capabilities",
        action="store_true",
        help="Fail unless runtime is fully ready (no degraded/fallback-only), including real image backend generation.",
    )
    p.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep local E2E artifacts (generated images/log rows/turn traces) instead of cleaning them.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.inprocess:
        # Keep in-process smoke deterministic and lightweight.
        os.environ["AEGIS_DISABLE_DB"] = "1"
        os.environ["AEGIS_LLM_WARMUP"] = "0"
        # In-process must not hang waiting for local image backends.
        os.environ.setdefault("AEGIS_IMAGE_TIMEOUT", "3")
        # Reduce memory/latency spikes for in-process checks.
        os.environ.setdefault("AEGIS_FAST_MODE", "1")
        # Avoid loading heavy retrieval/embedding stacks during in-process smoke.
        os.environ.setdefault("AEGIS_DISABLE_RETRIEVAL", "1")
        os.environ.setdefault("AEGIS_DISABLE_EMBEDDINGS", "1")
        os.environ.setdefault("AEGIS_CLAMAV_STATUS_ON_START", "0")
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

        # Some environments deadlock with ASGI TestClient. Run an ephemeral local uvicorn instead.
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
            return _run_checks(args, base_url=base_url, transport=RequestsTransport())
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    return _run_checks(args, base_url=args.base_url, transport=RequestsTransport())


def _run_checks(args: argparse.Namespace, *, base_url: str, transport: Transport) -> int:
    ctx = ClientCtx(
        base_url=base_url,
        timeout=float(args.timeout),
        api_key=(args.api_key or "").strip(),
        files_api_key=(args.files_api_key or args.api_key or "").strip(),
        transport=transport,
        strict_capabilities=bool(args.strict_capabilities),
        cleanup_artifacts=not bool(args.keep_artifacts),
    )

    checks = [check_health]
    if not args.skip_auth:
        checks.append(check_auth_token)
    if not args.skip_chat:
        checks.append(check_chat)
        if args.inprocess:
            checks.append(check_contextual_web)
    if not args.skip_image:
        checks.append(check_image)
    if not args.skip_ingest:
        checks.append(check_upload_and_ingest)
        if not args.skip_chat:
            checks.append(check_project_context)
            checks.append(check_turns_and_ops)
    if not args.skip_system:
        checks.append(check_system)
    if not args.skip_crypto:
        checks.append(check_crypto)

    ok = True
    for fn in checks:
        try:
            if bool(args.inprocess):
                print(f"[run] {fn.__name__}", flush=True)
            ok = fn(ctx) and ok
        except Exception as exc:  # noqa: BLE001
            _print_fail(fn.__name__, str(exc))
            ok = False

    cleanup(ctx)
    print(json.dumps({"ok": ok}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
