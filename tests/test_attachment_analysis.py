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


def test_attachment_context_response_answers_from_local_image_context():
    payload = chat_api._maybe_attachment_context_response(
        (
            "what is that image?\n\n"
            "[Attachment context image: cedula.jpg]\n"
            "Local visual analysis (no external services):\n"
            "- Resolution: 1200x760.\n"
            "Detected text (local OCR):\n"
            "```text\n"
            "REPUBLICA DE COLOMBIA\n"
            "CEDULA DE CIUDADANIA\n"
            "1038418201\n"
            "```\n"
        ),
        "en",
    )
    assert payload is not None
    assert payload["tool_kind"] == "attachment_context"
    assert "cedula.jpg" in payload["response"]
    assert "identity-document image" in payload["response"].lower()
    assert "1038418201" not in payload["response"]
    assert "1038...01" in payload["response"]


def test_attachment_context_response_ignores_project_question_with_attachment_noise():
    payload = chat_api._maybe_attachment_context_response(
        (
            "can u explain me all the tree of active project?\n\n"
            "[Attachment context image: trust1.png]\n"
            "Local visual analysis (no external services):\n"
            "- Resolution: 1200x760.\n"
        ),
        "en",
    )
    assert payload is None


def test_attachment_context_response_yields_to_active_project_file_focus(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_load_active_project_manifest",
        lambda _state: {"file_tree": ["src/app/app.routes.ts", "src/app/app.module.ts"]},
    )
    payload = chat_api._maybe_attachment_context_response(
        (
            "app.routes.ts que es este archivo ?\n\n"
            "[Attachment context document: 10928234.pdf]\n"
            "Extracted text from document `10928234.pdf`:\n\n"
            "```text\n"
            "CERTIFICATE\n"
            "This is to certify that Julian Grajales...\n"
            "```\n"
        ),
        "es",
        {
            "active_project_id": "demo-project",
            "next_tool": "project_manifest",
            "current_task": "explica el proyecto activo",
        },
    )
    assert payload is None


def test_attachment_context_response_summarizes_html_document():
    payload = chat_api._maybe_attachment_context_response(
        (
            "explain attached file\n\n"
            "[Attachment context document: index.html]\n"
            "Extracted text from document `index.html`:\n\n"
            "```text\n"
            "<!doctype html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "<meta name=\"description\" content=\"Portfolio of Julian Grajales - Full-Stack and Data Developer.\" />\n"
            "<title>Julian Grajales | Portfolio</title>\n"
            "</head>\n"
            "</html>\n"
            "```\n"
        ),
        "en",
    )
    assert payload is not None
    response = payload["response"].lower()
    assert "html page" in response
    assert "portfolio" in response
    assert "julian grajales | portfolio" in response


def test_attachment_context_response_summarizes_fastapi_code():
    payload = chat_api._maybe_attachment_context_response(
        (
            "what makes this code exactly?\n\n"
            "[Attachment context document: main.py]\n"
            "Extracted text from document `main.py`:\n\n"
            "```text\n"
            "from fastapi import FastAPI, Request\n"
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app = FastAPI()\n"
            "app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:4200'])\n"
            "app.include_router(api.router)\n"
            "@app.on_event('startup')\n"
            "async def startup_event():\n"
            "    Base.metadata.create_all(bind=engine)\n"
            "@app.post('/api/payu/notification')\n"
            "async def payu_notification(request: Request):\n"
            "    pass\n"
            "```\n"
        ),
        "en",
    )
    assert payload is not None
    response = payload["response"].lower()
    assert "fastapi backend entrypoint" in response
    assert "cors" in response
    assert "/api/payu/notification" in response
    assert "database" in response


def test_attachment_context_response_summarizes_markdown_guide():
    payload = chat_api._maybe_attachment_context_response(
        (
            "explain this file\n\n"
            "[Attachment context document: architecture_guide.md]\n"
            "Extracted text from document `architecture_guide.md`:\n\n"
            "```text\n"
            "# Aegis Architecture Guide\n"
            "## API Surface\n"
            "- chat\n"
            "- files\n"
            "- image\n"
            "```\n"
        ),
        "en",
    )
    assert payload is not None
    response = payload["response"].lower()
    assert "markdown guide" in response
    assert "aegis architecture guide" in response
    assert "list items" in response


def test_attachment_context_response_summarizes_json_config():
    payload = chat_api._maybe_attachment_context_response(
        (
            "summarize the attached config\n\n"
            "[Attachment context document: config.json]\n"
            "Extracted text from document `config.json`:\n\n"
            "```text\n"
            "{\"name\":\"aegis\",\"features\":{\"web\":true},\"providers\":[\"groq\",\"local\"]}\n"
            "```\n"
        ),
        "en",
    )
    assert payload is not None
    response = payload["response"].lower()
    assert "json/config file" in response
    assert "name" in response
    assert "features" in response
    assert "providers" in response


def test_attachment_context_response_summarizes_csv_table():
    payload = chat_api._maybe_attachment_context_response(
        (
            "what is in this file?\n\n"
            "[Attachment context document: prices.csv]\n"
            "Extracted text from document `prices.csv`:\n\n"
            "```text\n"
            "symbol,price,volume\n"
            "BTCUSDT,68000,120\n"
            "ETHUSDT,3200,80\n"
            "```\n"
        ),
        "en",
    )
    assert payload is not None
    response = payload["response"].lower()
    assert "csv or tabular file" in response
    assert "symbol, price, volume" in response
    assert "2 data rows" in response


def test_attachment_context_response_summarizes_error_log():
    payload = chat_api._maybe_attachment_context_response(
        (
            "explain this log\n\n"
            "[Attachment context document: server.log]\n"
            "Extracted text from document `server.log`:\n\n"
            "```text\n"
            "Traceback (most recent call last):\n"
            "ValueError: bad input\n"
            "```\n"
        ),
        "en",
    )
    assert payload is not None
    response = payload["response"].lower()
    assert "log or error output" in response
    assert "traceback" in response
