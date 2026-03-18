from __future__ import annotations

import asyncio

from app.api import system as system_api


def test_readyz_reports_fallback_only_when_core_ready(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "standard")
    monkeypatch.setattr(
        system_api,
        "collect_runtime_capabilities",
        lambda **_kwargs: {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "configured", "available": True, "model_exists": True, "loaded": False},
            "web_search": {"status": "ready", "provider_count": 2},
            "image": {"status": "fallback-only", "images_dir_exists": True, "fallback_only": True, "backend_reachable": False},
            "clamav": {"status": "missing"},
            "project_tools": {"status": "ready", "available": True},
        },
    )
    monkeypatch.setattr(system_api, "validation_runtime_snapshot", lambda: {"last_updated_ms": 123, "flows": {"startup_gate": {"status": "passed"}}})

    data = asyncio.run(system_api.readyz())
    assert data["ready"] is True
    assert data["status"] == "degraded"
    assert "image:fallback-only" in data["degraded_reasons"]
    assert "clamav:missing" in data["degraded_reasons"]
    assert data["checks"]["project_tools"] is True
    assert "host-prereq" in data["validation"]["startup_gate"]
    assert "browser-smoke" in data["validation"]["startup_gate"]
    assert "no-loop-stress" in data["validation"]["startup_gate"]
    assert "host-prereq" in data["validation"]["verify_full"]
    assert "ui-contract" in data["validation"]["verify_full"]
    assert "no-loop-stress" in data["validation"]["verify_full"]
    assert data["validation"]["browser_smoke_default"] is True
    assert data["validation"]["browser_smoke_strict_default"] is False
    assert "agent-evals" in data["validation"]["verify_full"]
    assert data["validation"]["last_runs"]["startup_gate"]["status"] == "passed"


def test_snapshot_exposes_validation_tiers(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "standard")
    monkeypatch.setattr(
        system_api,
        "collect_runtime_capabilities",
        lambda **_kwargs: {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "configured", "available": True, "model_exists": True, "loaded": False},
            "web_search": {"status": "ready", "provider_count": 2},
            "image": {"status": "ready", "images_dir_exists": True, "fallback_only": False, "backend_reachable": True},
            "clamav": {"status": "ready"},
            "project_tools": {"status": "ready", "available": True},
        },
    )
    monkeypatch.setattr(system_api.job_manager, "list_jobs", lambda limit=5: [])
    monkeypatch.setattr(system_api.crypto_prediction_log, "pair_predictions_with_outcomes", lambda limit=10: [])
    monkeypatch.setattr(system_api.crypto_prediction_log, "recent_stats", lambda limit=200: {})
    monkeypatch.setattr(system_api, "_pnl_snapshot", lambda: {})
    monkeypatch.setattr(system_api.health_state, "snapshot", lambda: {})
    monkeypatch.setattr(
        system_api,
        "validation_runtime_snapshot",
        lambda: {
            "last_updated_ms": 456,
            "flows": {
                "startup_gate": {"status": "passed"},
                "verify_full": {"status": "running"},
            },
        },
    )

    data = asyncio.run(system_api.system_snapshot())
    assert isinstance(data.get("resources"), dict)
    assert isinstance(data.get("agent_profile"), dict)
    assert "pytest-smoke" in data["validation"]["startup_gate"]
    assert "host-prereq" in data["validation"]["startup_gate"]
    assert "host-prereq" in data["validation"]["verify_full"]
    assert "pytest-full" in data["validation"]["verify_full"]
    assert "agent-evals" in data["validation"]["verify_full"]
    assert "ui-contract" in data["validation"]["verify_full"]
    assert "no-loop-stress" in data["validation"]["verify_full"]
    assert data["validation"]["scripts"]["start_with_preflight"] is True
    assert data["validation"]["scripts"]["verify_full"] is True
    assert data["validation"]["scripts"]["agent_eval_check"] is True
    assert data["validation"]["scripts"]["no_loop_stress_check"] is True
    assert data["validation"]["last_runs"]["verify_full"]["status"] == "running"
    assert data["validation"]["last_updated_ms"] == 456


def test_validation_snapshot_reflects_strict_runtime_profile(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    monkeypatch.setenv("AEGIS_PRODUCT_TRACK", "full")
    data = system_api._validation_snapshot()
    assert data["runtime_profile_default"] == "strict"
    assert data["browser_smoke_strict_default"] is True
