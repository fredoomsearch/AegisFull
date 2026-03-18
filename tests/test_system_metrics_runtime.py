from __future__ import annotations

import asyncio

from app.api import system as system_api


def test_system_metrics_endpoint_returns_runtime_snapshot(monkeypatch):
    monkeypatch.setattr(
        system_api.runtime_metrics,
        "snapshot",
        lambda window_seconds=900: {
            "window_seconds": window_seconds,
            "totals": {"chat_response": 10},
            "window": {"chat_response": 4, "poll_401": 1, "poll_request": 20, "safety_fallback": 0},
            "rates": {"safety_fallback_rate": 0.0, "poll_401_rate": 0.05},
            "source_distribution_window": {"web_live": 2, "local_project": 2},
        },
    )
    data = asyncio.run(system_api.runtime_metrics_snapshot(window_seconds=300))
    assert data["window_seconds"] == 300
    assert data["rates"]["poll_401_rate"] == 0.05


def test_readyz_runtime_metrics_alerts_expose_breaches(monkeypatch):
    monkeypatch.setattr(
        system_api,
        "collect_runtime_capabilities",
        lambda **_kwargs: {
            "embeddings": {"status": "ready"},
            "retrieval": {"status": "ready"},
            "llm": {"status": "ready"},
            "image": {"status": "ready"},
            "web_search": {"status": "ready"},
            "clamav": {"status": "ready"},
            "project_tools": {"status": "ready"},
            "browser_runtime": {"status": "ready"},
        },
    )
    monkeypatch.setattr(
        system_api,
        "summarize_runtime_capabilities",
        lambda _caps: {"ready": True, "status": "ready", "checks": {}, "degraded_reasons": []},
    )
    monkeypatch.setattr(system_api.job_manager, "list_jobs", lambda limit=3: [])
    monkeypatch.setattr(
        system_api.runtime_metrics,
        "snapshot",
        lambda window_seconds=300: {
            "window_seconds": window_seconds,
            "totals": {},
            "window": {"poll_401": 10, "poll_request": 20, "safety_fallback": 4, "chat_response": 10},
            "rates": {
                "safety_fallback_rate": 0.4,
                "poll_401_rate": 0.5,
                "ambiguous_route_rate": 0.6,
                "low_confidence_route_rate": 0.9,
            },
            "source_distribution_window": {},
            "route_confidence_distribution_window": {},
        },
    )
    data = asyncio.run(system_api.readyz())
    alerts = (((data.get("runtime_metrics") or {}).get("alerts")) or {})
    assert alerts.get("ok") is False
    breaches = set(alerts.get("breaches") or [])
    assert "safety_fallback_rate" in breaches
    assert "poll_401_rate" in breaches
    assert "ambiguous_route_rate" in breaches
    assert "low_confidence_route_rate" in breaches
