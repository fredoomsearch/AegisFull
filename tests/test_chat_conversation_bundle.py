from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.services.conversation_turns import (
    TURNS_DIR,
    append_turn_item,
    finish_turn,
    start_turn,
)


@pytest.mark.anyio
async def test_conversation_bundle_returns_turns_and_meta():
    import httpx
    import main

    conversation_id = str(uuid.uuid4())
    turn = start_turn(
        conversation_id,
        user_message="hello",
        mode="chat",
        source_plan="local_only",
    )
    turn_id = str(turn["turn_id"])
    append_turn_item(conversation_id, turn_id, kind="plan", payload={"next_tool": "project_manifest"})
    finish_turn(
        conversation_id,
        turn_id,
        status="success",
        assistant_message="ok",
        response_context={"source_plan": "local_only"},
    )

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get(f"/chat/{conversation_id}/bundle", params={"limit": 50})
        assert r.status_code == 200
        data = r.json() or {}
        assert data.get("conversation", {}).get("id") == conversation_id
        assert int(data.get("turn_count") or 0) >= 1
        assert data.get("last_turn_id") == turn_id
        turns = data.get("turns") or []
        assert turns and turns[-1].get("turn_id") == turn_id

    target = Path(TURNS_DIR) / f"{conversation_id}.json"
    if target.exists():
        target.unlink()


@pytest.mark.anyio
async def test_conversation_state_exposes_turn_meta():
    import httpx
    import main

    conversation_id = str(uuid.uuid4())
    turn = start_turn(
        conversation_id,
        user_message="state",
        mode="chat",
        source_plan="local_only",
    )
    turn_id = str(turn["turn_id"])
    finish_turn(
        conversation_id,
        turn_id,
        status="success",
        assistant_message="ok",
        response_context={"source_plan": "local_only"},
    )

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get(f"/chat/{conversation_id}/state")
        assert r.status_code == 200
        data = r.json() or {}
        assert int(data.get("turn_count") or 0) >= 1
        assert data.get("last_turn_id") == turn_id

    target = Path(TURNS_DIR) / f"{conversation_id}.json"
    if target.exists():
        target.unlink()
