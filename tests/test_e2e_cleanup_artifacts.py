from __future__ import annotations

import json
from pathlib import Path

from app.scripts import e2e_flow_check


def _ctx() -> e2e_flow_check.ClientCtx:
    return e2e_flow_check.ClientCtx(
        base_url="http://127.0.0.1:8000",
        timeout=5.0,
        api_key="k",
        files_api_key="k",
        transport=e2e_flow_check.RequestsTransport(),
    )


def test_cleanup_local_artifacts_removes_generated_images_and_prunes_log(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e_flow_check, "ROOT", tmp_path)
    images_dir = tmp_path / "data" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    img_a = images_dir / "a.png"
    img_b = images_dir / "b.png"
    img_a.write_bytes(b"a")
    img_b.write_bytes(b"b")

    log_file = images_dir / "log.jsonl"
    log_file.write_text(
        "\n".join(
            [
                json.dumps({"path": "data/images/a.png", "backend_ok": False}),
                json.dumps({"path": "data/images/b.png", "backend_ok": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ctx = _ctx()
    ctx.generated_image_paths = ["data/images/a.png"]
    e2e_flow_check._cleanup_local_artifacts(ctx)

    assert not img_a.exists()
    assert img_b.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "data/images/a.png" not in content
    assert "data/images/b.png" in content


def test_cleanup_local_artifacts_removes_turn_trace_file(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e_flow_check, "ROOT", tmp_path)
    turns_dir = tmp_path / "data" / "conversation_turns"
    turns_dir.mkdir(parents=True, exist_ok=True)
    conv_id = "abc123"
    turn_file = turns_dir / f"{conv_id}.json"
    turn_file.write_text("[]", encoding="utf-8")

    ctx = _ctx()
    ctx.conversation_id = conv_id
    e2e_flow_check._cleanup_local_artifacts(ctx)

    assert not turn_file.exists()


def test_cleanup_local_artifacts_removes_legacy_turn_trace_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e_flow_check, "ROOT", tmp_path)
    conv_id = "legacy-conv"
    turns_dir = tmp_path / "data" / "conversation_turns" / conv_id
    turns_dir.mkdir(parents=True, exist_ok=True)
    (turns_dir / "t1.json").write_text("{}", encoding="utf-8")

    ctx = _ctx()
    ctx.conversation_id = conv_id
    e2e_flow_check._cleanup_local_artifacts(ctx)

    assert not turns_dir.exists()


def test_cleanup_local_artifacts_removes_memory_conversation_json(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e_flow_check, "ROOT", tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    conv_id = "conv-x"
    conv_file = data_dir / "conversations.json"
    conv_file.write_text(
        json.dumps(
            {
                conv_id: {"summary": "", "messages": [], "state": {}},
                "other": {"summary": "", "messages": [], "state": {}},
            }
        ),
        encoding="utf-8",
    )

    ctx = _ctx()
    ctx.conversation_id = conv_id
    e2e_flow_check._cleanup_local_artifacts(ctx)

    payload = json.loads(conv_file.read_text(encoding="utf-8"))
    assert conv_id not in payload
    assert "other" in payload
