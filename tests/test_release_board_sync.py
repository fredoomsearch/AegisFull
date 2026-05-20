from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.scripts import release_board_sync


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_latest_evidence_snapshot_reports_missing_when_no_bundles(tmp_path: Path):
    rendered = release_board_sync.build_latest_evidence_snapshot(tmp_path)

    assert "Latest full bundle: `missing`" in rendered
    assert "Bundle stamp: `n/a`" in rendered
    assert "Bundle freshness: `unknown`" in rendered
    assert "Overall: `UNKNOWN`" in rendered
    assert "Crypto testnet rehearsal: `missing`" in rendered


def test_build_latest_core_evidence_snapshot_reports_missing_when_no_bundles(tmp_path: Path):
    rendered = release_board_sync.build_latest_evidence_snapshot(tmp_path, track="core")

    assert "Latest core bundle: `missing`" in rendered
    assert "Bundle stamp: `n/a`" in rendered
    assert "Bundle freshness: `unknown`" in rendered
    assert "Overall: `UNKNOWN`" in rendered
    assert "Optional soak gate: `not-run`" in rendered


def test_build_latest_evidence_snapshot_uses_release_summary_when_present(tmp_path: Path):
    bundle = tmp_path / "20260514_120000"
    _write_json(
        bundle / "release_summary.json",
        {
            "ok": True,
            "passed_checks": 7,
            "total_checks": 7,
            "checks": [
                {"name": "doctor_full", "ok": True, "detail": "ok"},
                {"name": "image_backend_probe", "ok": True, "detail": "ok"},
                {"name": "verify_full", "ok": True, "detail": "ok"},
                {"name": "hard_contract", "ok": True, "detail": "ok"},
                {"name": "soak_gate", "ok": True, "detail": "ok"},
                {"name": "system_readyz", "ok": True, "detail": "ok"},
                {
                    "name": "crypto_testnet_rehearsal",
                    "ok": True,
                    "detail": "preview_allowed=False submit_attempted=False",
                },
            ],
        },
    )

    rendered = release_board_sync.build_latest_evidence_snapshot(
        tmp_path,
        now=datetime(2026, 5, 14, 18, 0, 0),
    )

    assert "Latest full bundle: `" in rendered
    assert "Bundle stamp: `2026-05-14 12:00:00`" in rendered
    assert "Bundle freshness: `fresh • age=6h`" in rendered
    assert "Summary source: `" in rendered
    assert "release_summary.json" in rendered
    assert "Overall: `PASS`" in rendered
    assert "Checks: `7/7` passed" in rendered
    assert "Crypto testnet rehearsal: `PASS`" in rendered


def test_build_latest_evidence_snapshot_marks_old_bundle_as_stale(tmp_path: Path):
    bundle = tmp_path / "20260312_023820"
    _write_json(
        bundle / "release_summary.json",
        {
            "ok": False,
            "passed_checks": 0,
            "total_checks": 6,
            "checks": [
                {"name": "doctor_full", "ok": False, "detail": "missing"},
            ],
        },
    )

    rendered = release_board_sync.build_latest_evidence_snapshot(
        tmp_path,
        now=datetime(2026, 5, 19, 0, 0, 0),
    )

    assert "Bundle stamp: `2026-03-12 02:38:20`" in rendered
    assert "Bundle freshness: `stale • age=68d`" in rendered


def test_update_release_board_replaces_generated_block(tmp_path: Path):
    board = tmp_path / "release_board.md"
    board.write_text(
        "# Board\n\n## Release Evidence View\n\n### Latest Full Bundle Snapshot\n\n"
        "<!-- BEGIN AUTO RELEASE EVIDENCE -->\nold\n<!-- END AUTO RELEASE EVIDENCE -->\n\n"
        "### Latest Core Bundle Snapshot\n\n"
        "<!-- BEGIN AUTO CORE RELEASE EVIDENCE -->\nold-core\n<!-- END AUTO CORE RELEASE EVIDENCE -->\n\n"
        "## Tail\n",
        encoding="utf-8",
    )

    release_board_sync.update_release_board(
        board,
        evidence_root=tmp_path / "missing",
        core_evidence_root=tmp_path / "missing-core",
    )

    body = board.read_text(encoding="utf-8")
    assert "old" not in body
    assert "old-core" not in body
    assert "Latest full bundle: `missing`" in body
    assert "Latest core bundle: `missing`" in body
    assert body.count("Bundle stamp: `n/a`") == 2
    assert body.count("Bundle freshness: `unknown`") == 2
    assert "## Tail" in body