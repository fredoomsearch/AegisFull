from __future__ import annotations

import uuid

import pytest

from app.services.conversation_turns import delete_turns


async def _post_chat(client, conv_id: str, **payload):  # type: ignore[no-untyped-def]
    body = {"conversation_id": conv_id, "use_existing": True, "lang": "en"}
    body.update(payload)
    return await client.post("/chat", json=body)


async def _get_last_turn(client, conv_id: str) -> dict:  # type: ignore[no-untyped-def]
    r = await client.get(f"/chat/{conv_id}/turns")
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert items
    return items[-1]


@pytest.mark.anyio
async def test_chat_quick_time_response_creates_turn_record():
    import httpx
    import main

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    actual_conv_id = conv_id
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await _post_chat(client, conv_id, message="what time is it in new york?")
            assert r.status_code == 200
            payload = r.json()
            response_text = str(payload.get("response") or "")
            assert response_text
            actual_conv_id = str(payload.get("conversation_id") or conv_id)

            last_turn = await _get_last_turn(client, actual_conv_id)
            assert last_turn.get("assistant_message") == response_text
            assert last_turn.get("status") == "success"
    finally:
        delete_turns(actual_conv_id)


@pytest.mark.anyio
async def test_chat_validation_response_creates_turn_record():
    import httpx
    import main

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    actual_conv_id = conv_id
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await _post_chat(client, conv_id, message="not-a-url", mode="url")
            assert r.status_code == 200
            payload = r.json()
            response_text = str(payload.get("response") or "")
            assert "valid link" in response_text.lower()
            actual_conv_id = str(payload.get("conversation_id") or conv_id)

            last_turn = await _get_last_turn(client, actual_conv_id)
            assert last_turn.get("assistant_message") == response_text
            assert last_turn.get("status") == "error"
    finally:
        delete_turns(actual_conv_id)


@pytest.mark.anyio
async def test_chat_synthesize_false_skips_llm_and_keeps_turn_record(monkeypatch):
    import httpx
    import main
    from app.api import chat as chat_api

    async def _fake_web_context(*_args, **_kwargs):  # noqa: ANN001
        return (
            [
                {
                    "title": "Python 3.12 Release Notes",
                    "url": "https://docs.python.org/3.12/whatsnew/3.12.html",
                    "snippet": "Release highlights.",
                }
            ],
            "Python 3.12 release notes and highlights.",
            {"status": "ready", "source": "live", "provider": "stub", "results": 1, "attempted": True},
        )

    async def _fail_llm(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("_run_llm_generate should not be called when synthesize=false")

    monkeypatch.setattr(chat_api, "_build_web_context", _fake_web_context)
    monkeypatch.setattr(chat_api, "_run_llm_generate", _fail_llm)

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    actual_conv_id = conv_id
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await _post_chat(
                client,
                conv_id,
                message="web: latest python 3.12 release notes",
                use_web=True,
                synthesize=False,
            )
            assert r.status_code == 200
            payload = r.json()
            response_text = str(payload.get("response") or "")
            assert "release" in response_text.lower()
            actual_conv_id = str(payload.get("conversation_id") or conv_id)

            context = payload.get("context") or {}
            assert context.get("source_plan") == "web_only"
            assert context.get("effective_tool") == "evidence_only"

            last_turn = await _get_last_turn(client, actual_conv_id)
            assert last_turn.get("assistant_message") == response_text
            assert last_turn.get("status") == "success"
    finally:
        delete_turns(actual_conv_id)


@pytest.mark.anyio
async def test_chat_social_turn_does_not_call_web_even_when_client_requests_web(monkeypatch):
    import httpx
    import main
    from app.api import chat as chat_api

    async def _fail_web(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("_build_web_context should not be called for social chat")

    async def _fake_llm(*_args, **_kwargs):  # noqa: ANN001
        return "I am AEGIS. I can help with project analysis, code, files, and grounded web answers when needed."

    monkeypatch.setattr(chat_api, "_build_web_context", _fail_web)
    monkeypatch.setattr(chat_api, "_run_llm_generate", _fake_llm)

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    actual_conv_id = conv_id
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await _post_chat(
                client,
                conv_id,
                message="what can you do",
                mode="web",
                use_web=True,
            )
            assert r.status_code == 200
            payload = r.json()
            response_text = str(payload.get("response") or "")
            assert "AEGIS" in response_text
            actual_conv_id = str(payload.get("conversation_id") or conv_id)

            context = payload.get("context") or {}
            assert context.get("source_plan") == "local_only"

            last_turn = await _get_last_turn(client, actual_conv_id)
            assert last_turn.get("assistant_message") == response_text
            assert last_turn.get("status") == "success"
    finally:
        delete_turns(actual_conv_id)


@pytest.mark.anyio
async def test_chat_internet_access_turn_stays_local_even_when_client_requests_web(monkeypatch):
    import httpx
    import main
    from app.api import chat as chat_api

    async def _fail_web(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("_build_web_context should not be called for internet-capability chat")

    async def _fail_llm(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("_run_llm_generate should not be called for deterministic meta response")

    monkeypatch.setattr(chat_api, "_build_web_context", _fail_web)
    monkeypatch.setattr(chat_api, "_run_llm_generate", _fail_llm)

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    actual_conv_id = conv_id
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await _post_chat(
                client,
                conv_id,
                message="do you have access to internet?",
                mode="web",
                use_web=True,
            )
            assert r.status_code == 200
            payload = r.json()
            response_text = str(payload.get("response") or "")
            assert "web:" in response_text.lower()
            actual_conv_id = str(payload.get("conversation_id") or conv_id)

            context = payload.get("context") or {}
            assert context.get("source_plan") == "local_only"
            assert context.get("effective_tool") == "meta_fact"

            last_turn = await _get_last_turn(client, actual_conv_id)
            assert last_turn.get("assistant_message") == response_text
            assert last_turn.get("status") == "success"
    finally:
        delete_turns(actual_conv_id)


@pytest.mark.anyio
async def test_chat_code_learning_turn_falls_back_to_llm_when_web_is_unavailable(monkeypatch):
    import httpx
    import main
    from app.api import chat as chat_api

    async def _empty_web_context(*_args, **_kwargs):  # noqa: ANN001
        return [], "", {"status": "unavailable", "source": "none", "provider": "stub", "results": 0, "attempted": True}

    async def _fake_llm(*_args, **_kwargs):  # noqa: ANN001
        return "Use `sorted(items)` for a new list or `items.sort()` to sort in place."

    monkeypatch.setattr(chat_api, "_build_web_context", _empty_web_context)
    monkeypatch.setattr(chat_api, "_run_llm_generate", _fake_llm)

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    actual_conv_id = conv_id
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await _post_chat(
                client,
                conv_id,
                message="Ok can u search how is builded a sort function whit python this for handle a list?",
                mode="web",
                use_web=True,
            )
            assert r.status_code == 200
            payload = r.json()
            response_text = str(payload.get("response") or "")
            assert "sorted(items)" in response_text
            assert "web evidence" not in response_text.lower()
            actual_conv_id = str(payload.get("conversation_id") or conv_id)

            last_turn = await _get_last_turn(client, actual_conv_id)
            assert last_turn.get("assistant_message") == response_text
            assert last_turn.get("status") == "success"
    finally:
        delete_turns(actual_conv_id)
