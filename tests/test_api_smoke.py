from concurrent.futures import ThreadPoolExecutor

import pytest
import main
from app.api import chat as chat_api


@pytest.fixture(autouse=True)
def _fresh_executor(monkeypatch):
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(chat_api, "_executor", executor)
    try:
        yield
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def test_healthz_ok():
    payload = main.healthz()
    assert payload.get("status") == "ok"
    assert "version" in payload


def test_chat_clean_model_output():
    payload = chat_api.clean_model_output("[INST] ok [/INST]")
    assert payload == "ok"


def test_chat_truncates(monkeypatch):
    monkeypatch.setattr(chat_api, "MAX_RESPONSE_CHARS", 32)
    payload = chat_api._truncate_response("x" * 200, lang="es")
    assert payload.endswith("[respuesta truncada]")


@pytest.mark.anyio
async def test_websearch_lang(monkeypatch):
    seen = {}

    def fake_search(q, n, lang=None):
        seen["q"] = q
        seen["n"] = n
        seen["lang"] = lang
        return ([{"title": "Test", "snippet": "Ok", "link": "https://example.com"}], {"status": "live", "source": "live"})

    monkeypatch.setattr(chat_api, "web_search_structured_with_meta", fake_search)
    payload = (await chat_api.websearch(q="hello", n=2, lang="en")).model_dump()
    assert seen["q"] == "hello"
    assert seen["n"] == 2
    assert seen["lang"] == "en"
    assert payload["results"]


@pytest.mark.anyio
async def test_websearch_failure_is_soft(monkeypatch):
    def boom(q, n, lang=None):
        raise RuntimeError("no network")

    monkeypatch.setattr(chat_api, "web_search_structured_with_meta", boom)
    payload = (await chat_api.websearch(q="hello", n=2, lang="en")).model_dump()
    assert payload["results"] == []
    assert payload["meta"]["status"] == "unavailable"
    assert payload["meta"]["source"] == "none"
