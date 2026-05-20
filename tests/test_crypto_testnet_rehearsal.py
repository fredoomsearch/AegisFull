from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.scripts import crypto_testnet_rehearsal as rehearsal


def _build_args(**overrides):
    base = {
        "base_url": "http://127.0.0.1:8000",
        "api_key": "",
        "files_api_key": "",
        "timeout": 5.0,
        "skip_auth": True,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 0.1,
        "horizon_minutes": 15,
        "regime": "",
        "execution_mode": "testnet",
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
        "max_exposure_quote": 100.0,
        "max_order_size_pct": 15.0,
        "submit_if_allowed": True,
        "out_dir": "artifacts/release_evidence/crypto_testnet_rehearsal",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _summary_json_path(root: Path) -> Path:
    matches = list((root / "artifacts/release_evidence/crypto_testnet_rehearsal").glob("*/summary.json"))
    assert len(matches) == 1
    return matches[0]


def test_rehearsal_main_writes_blocked_preview_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rehearsal, "ROOT", tmp_path)
    monkeypatch.setattr(rehearsal, "parse_args", lambda: _build_args())
    monkeypatch.setattr(rehearsal.e2e, "check_health", lambda ctx: True)
    monkeypatch.setattr(rehearsal.time, "strftime", lambda *_args, **_kwargs: "20260514T000000Z")

    def fake_request_json(_ctx, method, path, **kwargs):
        if method == "GET" and path == "/crypto/state":
            return 200, {"execution": {"mode": "testnet"}, "summary": {"has_prediction": True}}
        if method == "POST" and path == "/crypto/trade/preview":
            return 200, {
                "execution_mode": "testnet",
                "execution_note": "preview fill",
                "risk_gate": {
                    "allowed": False,
                    "reason": "calibration_size_reduction_required",
                    "operator_guidance": {
                        "status": "downgrade",
                        "action": "raise_thresholds_or_reduce_size",
                    },
                    "calibration_controls": {
                        "max_order_notional": 7.5,
                        "max_quantity": 0.075,
                        "recommended_reduction_pct": 0.25,
                        "sizing_basis": "visible_liquidity_notional",
                    },
                    "blocked_checks": ["calibration_order_notional", "calibration_quantity"],
                },
            }
        if method == "GET" and path == "/crypto/trades":
            return 200, []
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(rehearsal, "_request_json", fake_request_json)

    exit_code = rehearsal.main()

    assert exit_code == 0
    summary_path = _summary_json_path(tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["decision"]["preview_allowed"] is False
    assert payload["decision"]["submit_attempted"] is False
    assert payload["decision"]["submit_skipped_reason"] == "preview_blocked"
    assert payload["preview"]["calibration"]["max_quantity"] == 0.075
    assert payload["preview"]["calibration"]["operator_status"] == "downgrade"
    assert summary_path.with_suffix(".md").exists()


def test_rehearsal_main_submits_when_preview_allowed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rehearsal, "ROOT", tmp_path)
    monkeypatch.setattr(rehearsal, "parse_args", lambda: _build_args())
    monkeypatch.setattr(rehearsal.e2e, "check_health", lambda ctx: True)
    monkeypatch.setattr(rehearsal.time, "strftime", lambda *_args, **_kwargs: "20260514T000000Z")

    def fake_request_json(_ctx, method, path, **kwargs):
        if method == "GET" and path == "/crypto/state":
            return 200, {"execution": {"mode": "testnet"}, "summary": {"has_prediction": True}}
        if method == "POST" and path == "/crypto/trade/preview":
            return 200, {
                "execution_mode": "testnet",
                "execution_note": "preview fill",
                "risk_gate": {
                    "allowed": True,
                    "reason": "ok",
                    "operator_guidance": {"status": "trust", "action": "normal_size"},
                    "calibration_controls": None,
                    "blocked_checks": [],
                },
            }
        if method == "POST" and path == "/crypto/trade":
            body = kwargs.get("json_body") or {}
            return 200, {
                "status": "SENT_TO_EXCHANGE",
                "execution_mode": "testnet",
                "message": f"sent {body.get('symbol')}",
            }
        if method == "GET" and path == "/crypto/trades":
            return 200, [{"id": "trade_1", "symbol": "BTCUSDT", "side": "BUY"}]
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(rehearsal, "_request_json", fake_request_json)

    exit_code = rehearsal.main()

    assert exit_code == 0
    summary_path = _summary_json_path(tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["decision"]["preview_allowed"] is True
    assert payload["decision"]["submit_attempted"] is True
    assert payload["decision"]["submit_skipped_reason"] is None
    assert payload["trade"]["body"]["status"] == "SENT_TO_EXCHANGE"
    assert len(payload["recent_trades"]["body"]) == 1