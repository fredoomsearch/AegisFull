from __future__ import annotations

import importlib

from app.models.llm_utils import build_messages


def test_durable_memory_persists_and_summarizes(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AEGIS_DURABLE_MEMORY_PERSIST", "1")

    from app.services import durable_memory

    durable_memory = importlib.reload(durable_memory)
    durable_memory.profiles.clear()

    profile = durable_memory.update_durable_memory(
        "demo-user",
        "Call me Ana. I prefer concise answers and step-by-step help.",
        "",
        session_state={"answer_style": {"include_steps": True}},
        mode="chat",
    )

    assert profile["subject"] == "demo-user"
    assert any("name: Ana" in item for item in profile["facts"])
    assert any("concise" in item for item in profile["preferences"])

    summary = durable_memory.get_durable_memory_summary("demo-user")
    assert "Facts:" in summary
    assert "Preferences:" in summary
    assert "Ana" in summary

    reloaded = importlib.reload(durable_memory)
    reloaded_summary = reloaded.get_durable_memory_summary("demo-user")
    assert "Ana" in reloaded_summary
    assert reloaded.load_durable_memory().get("demo-user") is not None


def test_build_messages_includes_durable_memory_snippet():
    messages = build_messages(
        "conv-1",
        "what is new?",
        durable_memory_snippet="Facts: name: Ana\nPreferences: prefers concise answers",
        session_state={"conversation_act": "other"},
    )
    system_prompt = messages[0]["content"]
    assert "Durable cross-session memory" in system_prompt
    assert "name: Ana" in system_prompt
