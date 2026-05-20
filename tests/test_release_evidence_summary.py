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


def test_summarize_core_bundle_ok_without_optional_soak(tmp_path: Path):
    _write_json(tmp_path / "doctor_core.json", {"ok": True, "failed": 0})
    (tmp_path / "verify_full_core.log").write_text("[ok] verify-full checks passed.\n", encoding="utf-8")
    (tmp_path / "hard_contract_core.log").write_text('{"ok": true}\n', encoding="utf-8")
    _write_json(tmp_path / "system_readyz.json", {"ready": True, "status": "ready"})

    payload = summary.summarize_core_bundle(tmp_path)

    assert payload["ok"] is True
    assert payload["track"] == "core"
    assert payload["failed_checks"] == 0
    assert payload["total_checks"] == 4


def test_summarize_core_bundle_includes_optional_soak_when_present(tmp_path: Path):
    _write_json(tmp_path / "doctor_core.json", {"ok": True, "failed": 0})
    (tmp_path / "verify_full_core.log").write_text("[ok] verify-full checks passed.\n", encoding="utf-8")
    (tmp_path / "hard_contract_core.log").write_text('{"ok": true}\n', encoding="utf-8")
    _write_json(tmp_path / "system_readyz.json", {"ready": True, "status": "ready"})
    _write_json(tmp_path / "soak_gate_core.json", {"ok": True})

    payload = summary.summarize_core_bundle(tmp_path)

    assert payload["ok"] is True
    assert payload["total_checks"] == 5
    soak_row = next(row for row in payload["checks"] if row["name"] == "soak_gate_core")
    assert soak_row["ok"] is True


def test_summarize_full_bundle_includes_crypto_testnet_rehearsal_when_present(tmp_path: Path):
    _write_json(tmp_path / "doctor_full.json", {"ok": True, "failed": 0})
    _write_json(tmp_path / "image_backend_probe.json", {"ok": True, "checkpoint_count": 1})
    (tmp_path / "verify_full.log").write_text("[ok] verify-full checks passed.\n", encoding="utf-8")
    (tmp_path / "hard_contract.log").write_text('{"ok": true}\n', encoding="utf-8")
    _write_json(tmp_path / "soak_gate.json", {"ok": True})
    _write_json(tmp_path / "system_readyz.json", {"ready": True, "status": "ready"})

    rehearsal_dir = tmp_path / "crypto_testnet_rehearsal" / "20260514T000000Z_btcusdt_testnet"
    rehearsal_dir.mkdir(parents=True)
    _write_json(
        rehearsal_dir / "summary.json",
        {
            "ok": True,
            "request": {"execution_mode": "testnet"},
            "preview": {"status_code": 200},
            "decision": {
                "effective_preview_mode": "testnet",
                "preview_allowed": False,
                "submit_attempted": False,
                "submit_skipped_reason": "preview_blocked",
            },
        },
    )

    payload = summary.summarize_full_bundle(tmp_path)

    assert payload["ok"] is True
    assert payload["total_checks"] == 7
    crypto_row = next(row for row in payload["checks"] if row["name"] == "crypto_testnet_rehearsal")
    assert crypto_row["ok"] is True
    assert "preview_allowed=False" in crypto_row["detail"]


def test_summarize_full_bundle_fails_crypto_testnet_rehearsal_when_mode_falls_back(tmp_path: Path):
    _write_json(tmp_path / "doctor_full.json", {"ok": True, "failed": 0})
    _write_json(tmp_path / "image_backend_probe.json", {"ok": True, "checkpoint_count": 1})
    (tmp_path / "verify_full.log").write_text("[ok] verify-full checks passed.\n", encoding="utf-8")
    (tmp_path / "hard_contract.log").write_text('{"ok": true}\n', encoding="utf-8")
    _write_json(tmp_path / "soak_gate.json", {"ok": True})
    _write_json(tmp_path / "system_readyz.json", {"ready": True, "status": "ready"})

    rehearsal_dir = tmp_path / "crypto_testnet_rehearsal" / "20260514T000000Z_btcusdt_testnet"
    rehearsal_dir.mkdir(parents=True)
    _write_json(
        rehearsal_dir / "summary.json",
        {
            "ok": True,
            "request": {"execution_mode": "testnet"},
            "preview": {"status_code": 200},
            "decision": {
                "effective_preview_mode": "simulated",
                "preview_allowed": True,
                "submit_attempted": False,
                "submit_skipped_reason": "effective_mode=simulated",
            },
        },
    )

    payload = summary.summarize_full_bundle(tmp_path)

    assert payload["ok"] is False
    crypto_row = next(row for row in payload["checks"] if row["name"] == "crypto_testnet_rehearsal")
    assert crypto_row["ok"] is False
    assert "effective_preview_mode=simulated" in crypto_row["detail"]
