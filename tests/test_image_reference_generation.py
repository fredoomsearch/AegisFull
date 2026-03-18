from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest


@pytest.mark.anyio
async def test_generate_with_reference_uses_ocr_and_returns_metadata(monkeypatch, tmp_path: Path):
    import main
    from app.api import image as image_api

    out = image_api.IMAGES_DIR / f"test_ref_{uuid.uuid4().hex}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"png")

    monkeypatch.setattr(image_api, "analyze_image_bytes", lambda *_a, **_k: "detected login form")
    monkeypatch.setattr(image_api, "_call_local_sd", lambda *_a, **_k: (out, True, None))

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        files = {"file": ("ref.png", b"fake-image", "image/png")}
        data = {
            "prompt": "build login mockup",
            "include_ocr": "1",
            "lang": "en",
            "steps": "10",
        }
        r = await client.post(
            "/image/generate_with_reference",
            files=files,
            data=data,
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("reference_used") is True
        assert payload.get("ocr_used") is True
        assert payload.get("backend_ok") is True
        assert str(payload.get("image_path") or "").startswith("data/images/")


@pytest.mark.anyio
async def test_generate_with_reference_rejects_non_image_upload():
    import main

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        files = {"file": ("readme.txt", b"hello", "text/plain")}
        data = {"prompt": "test"}
        r = await client.post(
            "/image/generate_with_reference",
            files=files,
            data=data,
            headers={"X-API-Key": "test-files-key"},
        )
        assert r.status_code == 400
        detail = r.json().get("detail")
        assert "must be an image" in str(detail)
