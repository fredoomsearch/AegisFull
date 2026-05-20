from __future__ import annotations

from app.services import capabilities_service, embedding_service
from app.services.capabilities_service import summarize_runtime_capabilities


def test_embedding_status_probe_does_not_force_model_load(monkeypatch):
    seen: dict[str, object] = {}

    def fake_get_embedding_status(*, ensure_loaded: bool = False) -> dict:
        seen["ensure_loaded"] = ensure_loaded
        return {"status": "ok", "loaded": False, "mode": None}

    monkeypatch.setattr(embedding_service, "get_embedding_status", fake_get_embedding_status)

    data = capabilities_service._embedding_status()

    assert data["status"] == "ok"
    assert seen["ensure_loaded"] is False


def test_summarize_runtime_capabilities_reports_degraded_with_project_tools(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "standard")
    data = summarize_runtime_capabilities(
        {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "configured", "available": True, "model_exists": True, "loaded": False},
            "web_search": {"status": "degraded", "probe_enabled": True},
            "image": {"status": "fallback-only", "images_dir_exists": True},
            "clamav": {"status": "missing"},
            "project_tools": {"status": "ready", "available": True},
        }
    )

    assert data["ready"] is True
    assert data["status"] == "degraded"
    assert data["checks"]["project_tools"] is True
    assert data["levels"]["web_search"] == "degraded"
    assert data["levels"]["image"] == "fallback-only"
    assert data["levels"]["llm"] == "ready"
    assert "image:fallback-only" in data["degraded_reasons"]
    assert "web:degraded" in data["degraded_reasons"]


def test_summarize_runtime_capabilities_does_not_mark_degraded_for_web_cooldown_without_probe(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "standard")
    data = summarize_runtime_capabilities(
        {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "configured", "available": True, "model_exists": True, "loaded": False},
            "web_search": {"status": "cooldown", "probe_enabled": False},
            "image": {"status": "ready", "images_dir_exists": True},
            "clamav": {"status": "ready"},
            "project_tools": {"status": "ready", "available": True},
        }
    )
    assert data["ready"] is True
    assert data["status"] == "ready"
    assert "web:cooldown" not in data["degraded_reasons"]


def test_summarize_runtime_capabilities_strict_core_keeps_image_browser_non_blocking(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    monkeypatch.setenv("AEGIS_PRODUCT_TRACK", "core")
    data = summarize_runtime_capabilities(
        {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "configured", "available": True, "model_exists": True, "loaded": False},
            "web_search": {"status": "ready"},
            "image": {"status": "degraded", "images_dir_exists": True},
            "clamav": {"status": "ready"},
            "project_tools": {"status": "ready", "available": True},
            "browser_runtime": {"status": "missing"},
        }
    )
    assert data["ready"] is True
    assert data["status"] == "degraded"
    assert data["product_track"] == "core"


def test_summarize_runtime_capabilities_strict_full_blocks_on_image_or_browser(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    monkeypatch.setenv("AEGIS_PRODUCT_TRACK", "full")
    data = summarize_runtime_capabilities(
        {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "configured", "available": True, "model_exists": True, "loaded": False},
            "web_search": {"status": "ready"},
            "image": {"status": "degraded", "images_dir_exists": True},
            "clamav": {"status": "ready"},
            "project_tools": {"status": "ready", "available": True},
            "browser_runtime": {"status": "missing"},
        }
    )
    assert data["ready"] is False
    assert data["status"] == "error"
    assert data["product_track"] == "full"


def test_summarize_runtime_capabilities_dedupes_degraded_reasons(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    monkeypatch.setenv("AEGIS_PRODUCT_TRACK", "full")
    data = summarize_runtime_capabilities(
        {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "configured", "available": True, "model_exists": True, "loaded": False},
            "web_search": {"status": "ready"},
            "image": {"status": "degraded", "images_dir_exists": True},
            "clamav": {"status": "ready"},
            "project_tools": {"status": "ready", "available": True},
            "browser_runtime": {"status": "ready"},
        }
    )
    assert data["degraded_reasons"] == ["image:degraded"]
