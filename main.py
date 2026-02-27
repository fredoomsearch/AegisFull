"""
AEGIS main FastAPI application entrypoint.

Run:
  uvicorn main:app --reload --log-level debug
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.api.files import router as files_router
from app.db.base import engine, init_db
from app.services.web_search import start_background_warmup

logger = logging.getLogger("aegis.main")
if not logger.handlers:
    logging.basicConfig(
        level=os.getenv("AEGIS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

LLM_WARMUP_ON_START = os.getenv("AEGIS_LLM_WARMUP", "1").lower() in {"1", "true", "yes", "on"}
DISABLE_DB = os.getenv("AEGIS_DISABLE_DB", "0").lower() in {"1", "true", "yes", "on"}

# Trust reverse-proxy headers for client IP
TRUST_PROXY = os.getenv("AEGIS_TRUST_PROXY", "0").lower() in {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _git_sha_cached() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], timeout=1).decode().strip()
    except Exception:
        return "unknown"


GIT_SHA = _git_sha_cached()

app = FastAPI(title="AEGIS Chat", version="0.1.0")

# Routers
app.include_router(files_router)
app.include_router(api_router)

# CORS
_cors_origins_raw = os.getenv("AEGIS_CORS_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] or ["*"]
_cors_has_wildcard = "*" in _cors_origins
_cors_creds_raw = (os.getenv("AEGIS_CORS_ALLOW_CREDENTIALS", "auto") or "auto").strip().lower()
if _cors_creds_raw == "auto":
    _cors_allow_credentials = not _cors_has_wildcard
elif _cors_creds_raw in {"1", "true", "yes", "on"}:
    _cors_allow_credentials = True
elif _cors_creds_raw in {"0", "false", "no", "off"}:
    _cors_allow_credentials = False
else:
    logger.warning(
        "Invalid AEGIS_CORS_ALLOW_CREDENTIALS=%r. Using auto mode.",
        _cors_creds_raw,
    )
    _cors_allow_credentials = not _cors_has_wildcard

if _cors_allow_credentials and _cors_has_wildcard:
    logger.warning(
        "CORS wildcard with credentials is unsafe/invalid. Forcing allow_credentials=False. "
        "Set AEGIS_CORS_ORIGINS to explicit origins for credentialed CORS."
    )
    _cors_allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECURE_HEADERS_ENABLED = _env_bool("AEGIS_SECURE_HEADERS", True)
HSTS_SECONDS = int(os.getenv("AEGIS_HSTS_SECONDS", "0"))
HSTS_INCLUDE_SUBDOMAINS = _env_bool("AEGIS_HSTS_INCLUDE_SUBDOMAINS", True)
HSTS_PRELOAD = _env_bool("AEGIS_HSTS_PRELOAD", False)

# Rate limiting
RATE_LIMIT = int(os.getenv("AEGIS_RATE_LIMIT_PER_MINUTE", "120"))
RATE_LIMIT_BUCKET_TTL = int(os.getenv("AEGIS_RATE_LIMIT_BUCKET_TTL", "120"))

_rate_overrides_raw = os.getenv("AEGIS_RATE_LIMITS", "")
_rate_overrides: List[Tuple[str, int]] = []
for part in _rate_overrides_raw.split(","):
    part = part.strip()
    if not part or "=" not in part:
        continue
    prefix, value = part.split("=", 1)
    prefix = prefix.strip()
    try:
        limit_val = int(value.strip())
    except ValueError:
        continue
    if prefix:
        _rate_overrides.append((prefix, limit_val))


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit_per_minute: int) -> bool:
        if limit_per_minute <= 0:
            return True

        now = time.time()
        window_start = now - 60.0

        dq = self._buckets[key]
        while dq and dq[0] < window_start:
            dq.popleft()

        if len(dq) >= limit_per_minute:
            return False

        dq.append(now)
        return True

    def gc(self, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        if len(self._buckets) < 10000:
            return
        cutoff = time.time() - float(ttl_seconds)
        for k, dq in list(self._buckets.items()):
            if not dq or dq[-1] < cutoff:
                self._buckets.pop(k, None)


rate_limiter = SlidingWindowRateLimiter()


def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip() or "unknown"
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _error_payload(detail: object, status_code: int, trace_id: Optional[str]) -> dict:
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail") or str(detail)
    else:
        message = str(detail)
    return {
        "detail": detail,
        "error": {"message": message, "code": status_code, "trace_id": trace_id},
    }


@app.middleware("http")
async def add_trace_and_rate_limit(request: Request, call_next):
    trace_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.trace_id = trace_id
    request.state.logger = logging.LoggerAdapter(logger, {"trace_id": trace_id})

    # rate limiting
    limit = RATE_LIMIT
    for prefix, override in _rate_overrides:
        if request.url.path.startswith(prefix):
            limit = override
            break

    if limit > 0:
        ip = _client_ip(request)
        key = f"{ip}:{request.url.path}"
        if not rate_limiter.allow(key, limit):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        rate_limiter.gc(RATE_LIMIT_BUCKET_TTL)

    response = await call_next(request)
    response.headers["X-Request-ID"] = trace_id
    if SECURE_HEADERS_ENABLED:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

    if HSTS_SECONDS > 0:
        req_scheme = request.url.scheme
        if req_scheme != "https":
            req_scheme = (request.headers.get("x-forwarded-proto") or req_scheme).split(",")[0].strip().lower()
        if req_scheme == "https":
            hsts = f"max-age={HSTS_SECONDS}"
            if HSTS_INCLUDE_SUBDOMAINS:
                hsts += "; includeSubDomains"
            if HSTS_PRELOAD:
                hsts += "; preload"
            response.headers.setdefault("Strict-Transport-Security", hsts)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(status_code=exc.status_code, content=_error_payload(exc.detail, exc.status_code, trace_id))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", None)
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content=_error_payload("Internal server error", 500, trace_id))


# Static UI
BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "ui"

if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=False), name="ui-static")
else:
    logger.warning("[main] UI_DIR does not exist: %s", UI_DIR)

# Serve data/ (for generated images/logs) read-only
DATA_DIR = BASE_DIR / "data"
if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR), html=False), name="data-static")
else:
    logger.warning("[main] DATA_DIR does not exist: %s", DATA_DIR)

FAVICON_PATH = UI_DIR / "urlimg.png"


def _clamav_status() -> str:
    """
    Lightweight ClamAV status check: see if clamdscan/clamscan exists and optionally ping clamd.
    Returns a short string for logging; does not raise.
    """
    clamdscan = shutil.which("clamdscan")
    clamscan = shutil.which("clamscan")
    if not clamdscan and not clamscan:
        return "ClamAV: scanner not found"

    # Try clamdscan --version (quick) or clamscan --version
    scanner = clamdscan or clamscan
    try:
        out = subprocess.check_output([scanner, "--version"], timeout=3, stderr=subprocess.STDOUT, text=True)
        version = (out.splitlines() or ["unknown"])[0].strip()
    except Exception:
        version = "unknown"

    # If clamdscan is present, try a quick ping to clamd
    if clamdscan:
        try:
            subprocess.check_output(["clamdscan", "--fdpass", "--stdout", "--version"], timeout=3, stderr=subprocess.STDOUT)
            return f"ClamAV: clamdscan available ({version})"
        except Exception:
            return f"ClamAV: clamdscan present but ping failed ({version})"

    return f"ClamAV: clamscan available ({version})"


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = UI_DIR / "index.html"
    if not index_path.exists():
        logger.error("[main] index.html NOT FOUND at %s", index_path)
        return HTMLResponse("<h1>UI not found</h1>", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    if FAVICON_PATH.exists():
        return FileResponse(str(FAVICON_PATH))
    return HTMLResponse("", status_code=204)


def _warm_llm_once() -> None:
    try:
        logger.info("[main] Warming up LLM backend...")
        from app.llm_client_offload import generate_response  # local import (safer for startup/tests)

        generate_response(
            [
                {"role": "system", "content": "You are AEGIS."},
                {"role": "user", "content": "ping"},
            ],
            max_new_tokens=8,
        )
        logger.info("[main] LLM warm-up completed.")
    except Exception:
        logger.warning("[main] LLM warm-up skipped (backend not ready).", exc_info=True)


def _log_security_posture() -> None:
    auth_mode = (os.getenv("AEGIS_AUTH_MODE", "on") or "on").strip().lower()
    if auth_mode in {"off", "local"}:
        logger.warning(
            "[security] AEGIS_AUTH_MODE=%s. Use 'on' in production and avoid local bypass behind proxies.",
            auth_mode,
        )
    if _cors_has_wildcard:
        logger.warning(
            "[security] AEGIS_CORS_ORIGINS includes '*'. Set explicit origins in production."
        )
    if HSTS_SECONDS <= 0:
        logger.info("[security] HSTS disabled (AEGIS_HSTS_SECONDS=0). Enable behind HTTPS reverse proxy.")
    weak_tokens = {"my-secret-key", "changeme", "change-me", "dev", "test", "password"}
    for env_name in ("AEGIS_API_KEY", "FILES_API_KEY", "ADMIN_API_KEY"):
        raw = (os.getenv(env_name) or "").strip()
        if not raw:
            continue
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if any(k.lower() in weak_tokens for k in keys):
            logger.warning("[security] %s contains weak default-like credential(s). Rotate before production.", env_name)


@app.on_event("startup")
def on_startup() -> None:
    if DISABLE_DB:
        logger.info("[main] DB init skipped (AEGIS_DISABLE_DB=1).")
    else:
        import app.db.models  # noqa: F401  # register models lazily

        logger.info("[main] Initializing DB...")
        init_db(engine)
        logger.info("[main] Database ready.")
    logger.info("[main] %s", _clamav_status())
    _log_security_posture()
    if LLM_WARMUP_ON_START:
        _warm_llm_once()
    start_background_warmup()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": app.version, "git_sha": GIT_SHA}
