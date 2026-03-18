from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.mark.anyio
async def test_generate_image_exposes_checkpoint_fallback_metadata(monkeypatch, tmp_path: Path):
    import main
    from app.api import image as image_api

    out = tmp_path / "img.png"
    out.write_bytes(b"png")
    seen: dict[str, str] = {}

    monkeypatch.setattr(
        image_api,
        "_resolve_checkpoint",
        lambda _base: (
            "DreamShaper_8_pruned.safetensors",
            "sd_turbo.safetensors",
            ["DreamShaper_8_pruned.safetensors"],
            None,
        ),
    )

    def _fake_call(req, checkpoint_name=None):
        seen["checkpoint"] = str(checkpoint_name or "")
        return out, True, None

    monkeypatch.setattr(image_api, "_call_local_sd", _fake_call)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/image/generate",
            json={"prompt": "test prompt"},
            headers={"X-API-Key": "test-files-key"},
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload.get("checkpoint_selected") == "DreamShaper_8_pruned.safetensors"
        assert payload.get("checkpoint_configured") == "sd_turbo.safetensors"
        assert payload.get("checkpoint_fallback_used") is True
        assert seen.get("checkpoint") == "DreamShaper_8_pruned.safetensors"


@pytest.mark.anyio
async def test_image_checkpoints_endpoint_returns_resolved_state(monkeypatch):
    import main
    from app.api import image as image_api

    monkeypatch.setattr(image_api, "_resolve_endpoint_and_base", lambda: ("http://127.0.0.1:8188/prompt", "http://127.0.0.1:8188"))
    monkeypatch.setattr(
        image_api,
        "_resolve_checkpoint",
        lambda _base: (
            "DreamShaper_8_pruned.safetensors",
            "DreamShaper_8_pruned.safetensors",
            ["DreamShaper_8_pruned.safetensors"],
            None,
        ),
    )

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/image/checkpoints", headers={"X-API-Key": "test-files-key"})
        assert res.status_code == 200
        data = res.json()
        assert data["selected_checkpoint"] == "DreamShaper_8_pruned.safetensors"
        assert data["configured_checkpoint"] == "DreamShaper_8_pruned.safetensors"
        assert data["available_checkpoints"] == ["DreamShaper_8_pruned.safetensors"]
        assert data["checkpoint_fallback_used"] is False

