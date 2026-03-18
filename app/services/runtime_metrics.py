from __future__ import annotations

"""
Runtime metrics and lightweight observability counters.

Why this module exists:
- Track routing/safety/polling behavior with deterministic counters.
- Feed release gates and `/system/*` with machine-readable reliability signals.
"""

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict
from app.utils.runtime_helpers import now_ms as _now_ms

_lock = threading.Lock()
_counters: Dict[str, int] = defaultdict(int)
_events: Deque[dict] = deque(maxlen=max(500, int(os.getenv("AEGIS_RUNTIME_METRICS_MAX_EVENTS", "8000"))))
_persist_path = Path(os.getenv("AEGIS_RUNTIME_METRICS_FILE", "data/runtime_metrics.json"))

_POLL_PATH_PATTERNS = [
    re.compile(r"^/chat/[^/]+/(events|turns|state)$"),
    re.compile(r"^/chat/list$"),
    re.compile(r"^/files/projects(?:/.*)?$"),
    re.compile(r"^/files/tree$"),
    re.compile(r"^/system/(readyz|snapshot)$"),
]

def _is_poll_path(path: str) -> bool:
    cleaned = str(path or "").strip()
    if not cleaned:
        return False
    return any(p.search(cleaned) for p in _POLL_PATH_PATTERNS)


def _persist_locked() -> None:
    try:
        _persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "counters": dict(_counters),
            "events": list(_events),
            "updated_at_ms": _now_ms(),
        }
        tmp = _persist_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_persist_path)
    except Exception:
        # Metrics persistence is best-effort only.
        pass


def _record_event(kind: str, *, value: int = 1, tags: Dict[str, Any] | None = None) -> None:
    ts_ms = _now_ms()
    with _lock:
        _counters[kind] += int(value)
        _events.append(
            {
                "ts_ms": ts_ms,
                "kind": str(kind or "").strip(),
                "value": int(value),
                "tags": dict(tags or {}),
            }
        )
        _persist_locked()


def incr(name: str, amount: int = 1) -> None:
    _record_event(str(name or "").strip() or "unknown", value=max(1, int(amount)))


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    try:
        score = float(value)
    except Exception:
        return "unknown"
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    if score >= 0.0:
        return "low"
    return "unknown"


def record_route_decision(
    source_plan: str,
    *,
    reason: str = "",
    routing_confidence: float | None = None,
    ambiguous_route: bool = False,
) -> None:
    """
    What it does:
    - Records one routing decision with confidence and ambiguity tags.

    Why it exists:
    - Feed hard-contract thresholds and explain route quality drift.

    Called from ->
    - chat and agent orchestration paths

    Calls ->
    - internal event/counter recorder with bucketed confidence tags
    """
    plan = str(source_plan or "unknown").strip().lower() or "unknown"
    bucket = _confidence_bucket(routing_confidence)
    tags = {
        "source_plan": plan,
        "reason": str(reason or "").strip()[:120],
        "confidence_bucket": bucket,
        "ambiguous_route": bool(ambiguous_route),
    }
    if routing_confidence is not None:
        try:
            tags["routing_confidence"] = float(routing_confidence)
        except Exception:
            pass
    _record_event("route_decision", tags=tags)
    _record_event(f"route_source_plan:{plan}")
    _record_event(f"route_confidence_bucket:{bucket}")
    if bool(ambiguous_route):
        _record_event("ambiguous_route")


def record_stale_tool_block(reason: str = "") -> None:
    _record_event("stale_tool_block", tags={"reason": str(reason or "").strip()[:120]})


def record_safety_fallback(kind: str = "generic") -> None:
    normalized = str(kind or "generic").strip().lower() or "generic"
    _record_event("safety_fallback", tags={"kind": normalized})
    _record_event(f"safety_fallback:{normalized}")


def record_chat_source(
    *,
    source_plan: str,
    source_origin: list[str] | None,
    web_source: str,
) -> None:
    origin = [str(x or "").strip().lower() for x in (source_origin or []) if str(x or "").strip()]
    web_src = str(web_source or "").strip().lower()
    plan = str(source_plan or "").strip().lower() or "local_only"

    if web_src == "live":
        source_kind = "web_live"
    elif web_src == "cache":
        source_kind = "web_cache"
    elif web_src == "stale-cache":
        source_kind = "web_stale_cache"
    elif any(x in {"local", "manifest"} for x in origin):
        source_kind = "local_project"
    else:
        source_kind = "local_model"

    _record_event(
        "chat_response",
        tags={
            "source_kind": source_kind,
            "source_plan": plan,
            "web_source": web_src or "none",
        },
    )
    _record_event(f"source_kind:{source_kind}")


def record_http_response(path: str, status_code: int) -> None:
    """
    What it does:
    - Tracks HTTP response counters and poll-specific auth noise.

    Why it exists:
    - Separate normal auth failures from hidden polling 401 spam.

    Called from ->
    - API middleware/response instrumentation

    Calls ->
    - internal event recorder with poll-path classifiers
    """
    code = int(status_code)
    cleaned = str(path or "").strip() or "/"
    _record_event("http_response")
    _record_event(f"http_status:{code}")

    is_poll = _is_poll_path(cleaned)
    if is_poll:
        _record_event("poll_request", tags={"path": cleaned, "status": code})
        if code in {401, 403}:
            _record_event("poll_401", tags={"path": cleaned, "status": code})
    elif code in {401, 403}:
        _record_event("auth_401_other", tags={"path": cleaned, "status": code})


def _window_counts(window_seconds: int) -> Dict[str, int]:
    cutoff_ms = _now_ms() - max(1, int(window_seconds)) * 1000
    out: Dict[str, int] = defaultdict(int)
    with _lock:
        for ev in _events:
            if int(ev.get("ts_ms") or 0) < cutoff_ms:
                continue
            kind = str(ev.get("kind") or "").strip()
            if not kind:
                continue
            out[kind] += int(ev.get("value") or 1)
    return dict(out)


def snapshot(window_seconds: int = 900) -> Dict[str, Any]:
    """
    What it does:
    - Builds machine-readable totals/rates/distributions for a metrics window.

    Why it exists:
    - Single source for readiness alerts and release-gate checks.

    Called from ->
    - `/system/metrics`, `/system/readyz`, hard-contract tooling

    Calls ->
    - window aggregation helpers over persisted event stream
    """
    window = _window_counts(window_seconds)
    with _lock:
        totals = dict(_counters)

    chat_responses = max(1, int(window.get("chat_response") or 0))
    poll_total = max(1, int(window.get("poll_request") or 0))
    route_total = max(1, int(window.get("route_decision") or 0))
    safety_count = int(window.get("safety_fallback") or 0)
    poll_401 = int(window.get("poll_401") or 0)
    ambiguous_routes = int(window.get("ambiguous_route") or 0)
    low_conf_routes = int(window.get("route_confidence_bucket:low") or 0)

    source_distribution = {
        "web_live": int(window.get("source_kind:web_live") or 0),
        "web_cache": int(window.get("source_kind:web_cache") or 0),
        "web_stale_cache": int(window.get("source_kind:web_stale_cache") or 0),
        "local_project": int(window.get("source_kind:local_project") or 0),
        "local_model": int(window.get("source_kind:local_model") or 0),
    }
    route_confidence_distribution = {
        "high": int(window.get("route_confidence_bucket:high") or 0),
        "medium": int(window.get("route_confidence_bucket:medium") or 0),
        "low": int(window.get("route_confidence_bucket:low") or 0),
        "unknown": int(window.get("route_confidence_bucket:unknown") or 0),
    }

    return {
        "window_seconds": int(window_seconds),
        "totals": totals,
        "window": window,
        "rates": {
            "safety_fallback_rate": float(safety_count) / float(chat_responses),
            "poll_401_rate": float(poll_401) / float(poll_total),
            "ambiguous_route_rate": float(ambiguous_routes) / float(route_total),
            "low_confidence_route_rate": float(low_conf_routes) / float(route_total),
        },
        "source_distribution_window": source_distribution,
        "route_confidence_distribution_window": route_confidence_distribution,
    }
