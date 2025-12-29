from app.api import chat as chat_api


def test_healthz_ok(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    payload = res.json()
    assert payload.get("status") == "ok"
    assert "version" in payload


def test_chat_basic(monkeypatch, client):
    monkeypatch.setattr(chat_api, "generate_response", lambda *args, **kwargs: "ok")
    res = client.post("/chat", json={"message": "hola"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["response"] == "ok"
    assert payload["conversation_id"]


def test_chat_truncates(monkeypatch, client):
    monkeypatch.setattr(chat_api, "MAX_RESPONSE_CHARS", 32)
    monkeypatch.setattr(chat_api, "generate_response", lambda *args, **kwargs: "x" * 200)
    res = client.post("/chat", json={"message": "hola", "lang": "es"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["response"].endswith("[respuesta truncada]")


def test_websearch_lang(monkeypatch, client):
    seen = {}

    def fake_search(q, n, lang=None):
        seen["q"] = q
        seen["n"] = n
        seen["lang"] = lang
        return [{"title": "Test", "snippet": "Ok", "link": "https://example.com"}]

    monkeypatch.setattr(chat_api, "web_search_structured", fake_search)
    res = client.get("/websearch", params={"q": "hello", "n": 2, "lang": "en"})
    assert res.status_code == 200
    payload = res.json()
    assert seen["q"] == "hello"
    assert seen["n"] == 2
    assert seen["lang"] == "en"
    assert payload["results"]
