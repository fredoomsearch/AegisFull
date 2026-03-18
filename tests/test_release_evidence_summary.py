from __future__ import annotations

import json
from pathlib import Path

from app.scripts import release_evidence_summary as summary


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_summarize_full_bundle_ok(tmp_path: Path):
    _write_json(tmp_path / "doctor_full.json", {"ok": True, "failed": 0})
    _write_json(tmp_path / "image_backend_probe.json", {"ok": True, "checkpoint_count": 1})
    (tmp_path / "verify_full.log").write_text("[ok] verify-full checks passed.\n", encoding="utf-8")
    (tmp_path / "hard_contract.log").write_text('{"ok": true}\n', encoding="utf-8")
    _write_json(tmp_path / "soak_gate.json", {"ok": True})
    _write_json(tmp_path / "system_readyz.json", {"ready": True, "status": "ready"})

    payload = summary.summarize_full_bundle(tmp_path)
    assert payload["ok"] is True
    assert payload["failed_checks"] == 0


def test_summarize_full_bundle_fails_missing_artifacts(tmp_path: Path):
    payload = summary.summarize_full_bundle(tmp_path)
    assert payload["ok"] is False
    assert payload["failed_checks"] == 6
    names = {row["name"] for row in payload["checks"] if not row["ok"]}
    assert "doctor_full" in names
    assert "image_backend_probe" in names
    assert "verify_full" in names
    assert "hard_contract" in names
    assert "soak_gate" in names
    assert "system_readyz" in names


def test_hard_contract_checker_uses_last_json_line(tmp_path: Path):
    log = tmp_path / "hard_contract.log"
    log.write_text("line\nnot-json\n{\"ok\": false}\n{\"ok\": true}\n", encoding="utf-8")
    check = summary._check_hard_contract(log)  # noqa: SLF001
    assert check.ok is True
