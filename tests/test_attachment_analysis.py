from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.api.chat as chat_api


class DummyUploadFile:
    def __init__(self, *, filename: str, content_type: str, payload: bytes):
        self.filename = filename
        self.content_type = content_type
        self._payload = payload

    async def read(self) -> bytes:
        return self._payload


@pytest.mark.anyio
async def test_analyze_attachment_document_text():
    file = DummyUploadFile(
        filename="notes.txt",
        content_type="text/plain",
        payload=b"hello from attachment",
    )
    payload = await chat_api.analyze_attachment_endpoint(file=file, lang="en")
    assert payload.kind == "document"
    assert payload.filename == "notes.txt"
    assert "hello from attachment" in payload.description


@pytest.mark.anyio
async def test_analyze_attachment_image_uses_single_visual_context_mode(monkeypatch):
    seen: dict[str, str] = {}

    def fake_analyze(_payload: bytes, *, lang: str, mode: str, psm=None, oem=None) -> str:  # noqa: ANN001
        seen["lang"] = lang
        seen["mode"] = mode
        return "image-ok"

    monkeypatch.setattr(chat_api, "analyze_image_bytes", fake_analyze)
    file = DummyUploadFile(
        filename="shot.png",
        content_type="image/png",
        payload=b"not-a-real-image",
    )
    payload = await chat_api.analyze_attachment_endpoint(file=file, lang="en")
    assert payload.kind == "image"
    assert payload.description == "image-ok"
    assert seen == {"lang": "en", "mode": "scene"}


@pytest.mark.anyio
async def test_analyze_image_endpoint_uses_scene_mode(monkeypatch):
    seen: dict[str, str] = {}

    def fake_analyze(_payload: bytes, *, lang: str, mode: str, psm=None, oem=None) -> str:  # noqa: ANN001
        seen["lang"] = lang
        seen["mode"] = mode
        return "ok"

    monkeypatch.setattr(chat_api, "analyze_image_bytes", fake_analyze)
    file = DummyUploadFile(
        filename="screen.png",
        content_type="image/png",
        payload=b"fake-image",
    )
    resp = await chat_api.analyze_image_endpoint(file=file, lang="en")
    assert resp.description == "ok"
    assert seen == {"lang": "en", "mode": "scene"}


@pytest.mark.anyio
async def test_analyze_attachment_rejects_too_large_payload(monkeypatch):
    monkeypatch.setattr(chat_api, "MAX_ATTACHMENT_BYTES", 8)
    file = DummyUploadFile(
        filename="big.txt",
        content_type="text/plain",
        payload=b"x" * 64,
    )
    with pytest.raises(HTTPException) as exc:
        await chat_api.analyze_attachment_endpoint(file=file, lang="en")
    assert exc.value.status_code == 400
    assert "too large" in str(exc.value.detail).lower()
