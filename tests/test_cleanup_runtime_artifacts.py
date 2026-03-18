from __future__ import annotations

from pathlib import Path

from app.scripts import cleanup_runtime_artifacts as cleanup_mod


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_cleanup_runtime_artifacts_removes_known_files(tmp_path: Path):
    _touch(tmp_path / "data/images/a.png", "img")
    _touch(tmp_path / "data/images/log.jsonl", '{"ok":true}\n')
    _touch(tmp_path / "data/conversation_turns/conv1/t1.json", "{}")
    _touch(tmp_path / "data/validation_state.json", "{}")
    _touch(tmp_path / "data/keep_me.txt", "keep")

    result = cleanup_mod.cleanup_runtime_artifacts(tmp_path, dry_run=False, aggressive=False).as_dict()
    assert result["ok"] is True
    assert result["removed_count"] >= 4
    assert not (tmp_path / "data/images/a.png").exists()
    assert not (tmp_path / "data/images/log.jsonl").exists()
    assert not (tmp_path / "data/conversation_turns/conv1/t1.json").exists()
    assert not (tmp_path / "data/validation_state.json").exists()
    assert (tmp_path / "data/keep_me.txt").exists()


def test_cleanup_runtime_artifacts_dry_run_keeps_files(tmp_path: Path):
    _touch(tmp_path / "data/images/a.png", "img")
    _touch(tmp_path / "data/av_scan_events.jsonl", '{"scan":"ok"}\n')

    result = cleanup_mod.cleanup_runtime_artifacts(tmp_path, dry_run=True, aggressive=True).as_dict()
    assert result["ok"] is True
    assert result["removed_count"] >= 1
    assert (tmp_path / "data/images/a.png").exists()
    assert (tmp_path / "data/av_scan_events.jsonl").exists()
