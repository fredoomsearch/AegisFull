from __future__ import annotations


def test_auto_routes_hard_turn_to_groq(monkeypatch):
    import app.llm_client_offload as offload
    import app.models.llm_client as llm_client

    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "auto")
    monkeypatch.setattr(offload, "llm_status", lambda: {"remote_ready": True})

    captured: dict[str, object] = {}

    def fake_generate(messages, **kwargs):
        captured["kwargs"] = dict(kwargs)
        captured["messages"] = list(messages)
        return "groq-ok"

    monkeypatch.setattr(offload, "generate_response", fake_generate)

    answer = llm_client.generate_response(
        [{"role": "user", "content": "Build a FastAPI login endpoint with Angular frontend"}],
        mode="code",
    )

    assert answer == "groq-ok"
    assert captured["kwargs"]["preferred_provider"] == "groq"
    from app.models.llm_client import llm_route_policy
    route = llm_route_policy([{"role": "user", "content": "Build a FastAPI login endpoint with Angular frontend"}], mode="code")
    assert route["quantitative"]["gate"] == "prefer_remote"
    assert route["quantitative"]["confidence_bucket"] in {"low", "medium"}


def test_auto_routes_simple_turn_to_local(monkeypatch):
    import app.llm_client_offload as offload
    import app.models.llm_client as llm_client

    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "auto")
    monkeypatch.setattr(offload, "llm_status", lambda: {"remote_ready": True})

    captured: dict[str, object] = {}

    def fake_generate(messages, **kwargs):
        captured["kwargs"] = dict(kwargs)
        captured["messages"] = list(messages)
        return "local-ok"

    monkeypatch.setattr(offload, "generate_response", fake_generate)

    answer = llm_client.generate_response(
        [{"role": "user", "content": "What is the capital of Japan?"}],
        mode="chat",
    )

    assert answer == "local-ok"
    assert captured["kwargs"]["preferred_provider"] == "local"
    from app.models.llm_client import llm_route_policy
    route = llm_route_policy([{"role": "user", "content": "What is the capital of Japan?"}], mode="chat")
    assert route["quantitative"]["gate"] == "allow_local"
    assert route["quantitative"]["confidence_bucket"] == "high"
