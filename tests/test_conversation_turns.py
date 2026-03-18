from __future__ import annotations

import uuid
from pathlib import Path

from app.services.conversation_turns import (
    TURNS_DIR,
    append_turn_item,
    delete_turns,
    export_turns_bundle,
    finish_turn,
    get_turn,
    get_turns_meta,
    list_turns,
    start_turn,
)


def test_conversation_turn_items_roundtrip():
    conversation_id = f"conv-test-turns-{uuid.uuid4().hex[:8]}"
    turn = start_turn(
        conversation_id,
        user_message="hello",
        mode="chat",
        source_plan="local_only",
    )
    turn_id = str(turn["turn_id"])
    try:
        append_turn_item(conversation_id, turn_id, kind="plan", payload={"mode": "chat"})
        finish_turn(
            conversation_id,
            turn_id,
            status="success",
            assistant_message="ok",
            response_context={"source_plan": "local_only"},
        )

        items = list_turns(conversation_id, limit=10)
        assert items
        last = items[-1]
        assert last["user_message"] == "hello"
        assert any(item.get("kind") == "plan" for item in last.get("items", []))
        assert last["status"] == "success"
        assert last["assistant_message"] == "ok"

        fetched = get_turn(conversation_id, turn_id)
        assert fetched and fetched.get("turn_id") == turn_id
        fetched_slim = get_turn(conversation_id, turn_id, include_items=False)
        assert fetched_slim and fetched_slim.get("turn_id") == turn_id
        assert "items" not in fetched_slim
    finally:
        target = Path(TURNS_DIR) / f"{conversation_id}.json"
        if target.exists():
            target.unlink()


def test_conversation_turn_records_replan_items():
    conversation_id = f"conv-test-replan-{uuid.uuid4().hex[:8]}"
    turn = start_turn(
        conversation_id,
        user_message="find auth file",
        mode="chat",
        source_plan="local_only",
    )
    turn_id = str(turn["turn_id"])
    try:
        append_turn_item(
            conversation_id,
            turn_id,
            kind="tool_call",
            payload={"tool": "project_symbol_search", "query": "auth"},
        )
        append_turn_item(
            conversation_id,
            turn_id,
            kind="replan",
            payload={
                "next_tool": "project_manifest",
                "next_step": "Use manifest summary before asking the LLM",
                "missing_evidence": ["matching symbol"],
            },
        )
        finish_turn(
            conversation_id,
            turn_id,
            status="success",
            assistant_message="Need project evidence first.",
            response_context={
                "source_plan": "local_only",
                "next_tool": "project_manifest",
                "missing_evidence": ["matching symbol"],
            },
        )

        items = list_turns(conversation_id, limit=10)
        assert items
        last = items[-1]
        kinds = [item.get("kind") for item in last.get("items", [])]
        assert "tool_call" in kinds
        assert "replan" in kinds
        replan = next(item for item in last.get("items", []) if item.get("kind") == "replan")
        assert replan["payload"]["next_tool"] == "project_manifest"
        assert replan["payload"]["missing_evidence"] == ["matching symbol"]
        assert last["response_context"]["next_tool"] == "project_manifest"
    finally:
        target = Path(TURNS_DIR) / f"{conversation_id}.json"
        if target.exists():
            target.unlink()


def test_conversation_turn_can_record_source_selection_item():
    conversation_id = f"conv-test-source-{uuid.uuid4().hex[:8]}"
    turn = start_turn(
        conversation_id,
        user_message="show me the code",
        mode="chat",
        source_plan="local_only",
    )
    turn_id = str(turn["turn_id"])
    try:
        append_turn_item(
            conversation_id,
            turn_id,
            kind="source_selection",
            payload={
                "source_plan": "local_only",
                "next_tool": "project_excerpt",
                "tool_candidates": ["project_excerpt", "project_symbols"],
                "llm_required": False,
            },
        )
        finish_turn(
            conversation_id,
            turn_id,
            status="success",
            assistant_message="File app/service.py...",
            response_context={"source_plan": "local_only", "next_tool": "project_excerpt"},
        )
        items = list_turns(conversation_id, limit=10)
        assert items
        last = items[-1]
        source_item = next(item for item in last.get("items", []) if item.get("kind") == "source_selection")
        assert source_item["payload"]["source_plan"] == "local_only"
        assert source_item["payload"]["next_tool"] == "project_excerpt"
        assert source_item["payload"]["llm_required"] is False
    finally:
        target = Path(TURNS_DIR) / f"{conversation_id}.json"
        if target.exists():
            target.unlink()


def test_conversation_turn_meta_and_bundle_export():
    conversation_id = f"conv-test-meta-{uuid.uuid4().hex[:8]}"
    turn = start_turn(
        conversation_id,
        user_message="bundle",
        mode="chat",
        source_plan="local_only",
    )
    turn_id = str(turn["turn_id"])
    try:
        finish_turn(
            conversation_id,
            turn_id,
            status="success",
            assistant_message="ok",
            response_context={"source_plan": "local_only"},
        )
        meta = get_turns_meta(conversation_id)
        assert int(meta.get("turn_count") or 0) >= 1
        assert meta.get("last_turn_id") == turn_id

        bundle = export_turns_bundle(conversation_id, limit=20)
        assert bundle.get("conversation_id") == conversation_id
        assert bundle.get("last_turn_id") == turn_id
        assert bundle.get("items")
    finally:
        target = Path(TURNS_DIR) / f"{conversation_id}.json"
        if target.exists():
            target.unlink()


def test_delete_turns_removes_file_and_legacy_dir():
    conversation_id = f"conv-test-del-{uuid.uuid4().hex[:8]}"
    turns_root = Path(TURNS_DIR)
    file_path = turns_root / f"{conversation_id}.json"
    legacy_dir = turns_root / conversation_id
    legacy_file = legacy_dir / "t1.json"
    turns_root.mkdir(parents=True, exist_ok=True)
    file_path.write_text("[]", encoding="utf-8")
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("{}", encoding="utf-8")

    removed = delete_turns(conversation_id)
    assert removed is True
    assert not file_path.exists()
    assert not legacy_dir.exists()
