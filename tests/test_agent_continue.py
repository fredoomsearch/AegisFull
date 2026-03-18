from __future__ import annotations

import uuid

import pytest

from app.api import chat as chat_api
from app.schemas import AgentContinueRequest, AgentRunResponse


@pytest.mark.anyio
async def test_agent_continue_uses_state_next_step_when_message_missing(monkeypatch):
    conv_id = str(uuid.uuid4())
    state = {
        "next_step": "inspect app/auth.py",
        "current_subtask": "review auth symbols",
        "current_task": "audit login flow",
        "goal": "understand backend architecture",
    }

    monkeypatch.setattr(chat_api, "_open_db_session", lambda: (None, None, False))
    monkeypatch.setattr(chat_api, "_load_conversation_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(chat_api, "_close_db_session", lambda *_args, **_kwargs: None)

    captured = {}
    events = []
    monkeypatch.setattr(chat_api, "record_event", lambda conv, name, **kwargs: events.append((conv, name, kwargs.get("data") or {})))

    async def _fake_agent_run(conversation_id, body, request):  # noqa: ANN001
        captured["conversation_id"] = conversation_id
        captured["message"] = body.message
        return AgentRunResponse(
            ok=True,
            conversation_id=conversation_id,
            response="ok",
            iterations=[],
            evidence=[],
            sources=[],
            web_meta={"status": "not-used", "source": "not-used"},
        )

    monkeypatch.setattr(chat_api, "agent_run", _fake_agent_run)

    req = AgentContinueRequest(message=None, lang="en", use_web=False)
    out = await chat_api.agent_continue(conv_id, req, request=object())  # type: ignore[arg-type]
    assert out.ok is True
    assert captured["conversation_id"] == conv_id
    assert captured["message"] == "inspect app/auth.py"
    assert any(name == "agent_continue_seed" and data.get("source") == "next_step" for _conv, name, data in events)


@pytest.mark.anyio
async def test_agent_continue_falls_back_to_continue_when_state_empty(monkeypatch):
    conv_id = str(uuid.uuid4())
    monkeypatch.setattr(chat_api, "_open_db_session", lambda: (None, None, False))
    monkeypatch.setattr(chat_api, "_load_conversation_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chat_api, "_close_db_session", lambda *_args, **_kwargs: None)

    captured = {}
    events = []
    monkeypatch.setattr(chat_api, "record_event", lambda conv, name, **kwargs: events.append((conv, name, kwargs.get("data") or {})))

    async def _fake_agent_run(conversation_id, body, request):  # noqa: ANN001
        captured["message"] = body.message
        return AgentRunResponse(
            ok=True,
            conversation_id=conversation_id,
            response="ok",
            iterations=[],
            evidence=[],
            sources=[],
            web_meta={"status": "not-used", "source": "not-used"},
        )

    monkeypatch.setattr(chat_api, "agent_run", _fake_agent_run)

    req = AgentContinueRequest(message=None, lang="es", use_web=False)
    out = await chat_api.agent_continue(conv_id, req, request=object())  # type: ignore[arg-type]
    assert out.ok is True
    assert captured["message"] == "continue"
    assert any(name == "agent_continue_seed" and data.get("source") == "default_continue" for _conv, name, data in events)
