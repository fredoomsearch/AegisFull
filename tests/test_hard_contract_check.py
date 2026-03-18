from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path

from app.scripts import hard_contract_check as hcc
from app.scripts.hard_contract_check import _run_adversarial


def test_hard_contract_script_compiles():
    target = Path(__file__).resolve().parents[1] / "app" / "scripts" / "hard_contract_check.py"
    py_compile.compile(str(target), doraise=True)


def test_hard_contract_adversarial_signal_is_clean():
    result = _run_adversarial(min_cases=500)
    assert result["ok"] is True
    assert float(result["wrong_route_rate"]) <= 0.005


def test_hard_contract_strict_requires_base_url(monkeypatch, capsys):
    monkeypatch.setattr(
        hcc,
        "_run_adversarial",
        lambda min_cases: {"ok": True, "result": {"ok": True, "total": max(500, min_cases), "passed": max(500, min_cases)}, "wrong_route_rate": 0.0},
    )
    monkeypatch.setattr(sys, "argv", ["hard_contract_check.py", "--strict"])
    rc = hcc.main()
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 1
    assert payload["ok"] is False
    assert payload["checks"]["runtime_metrics"]["ok"] is False


def test_hard_contract_strict_runs_soak_gate(monkeypatch, capsys):
    monkeypatch.setattr(
        hcc,
        "_run_adversarial",
        lambda min_cases: {"ok": True, "result": {"ok": True, "total": max(500, min_cases), "passed": max(500, min_cases)}, "wrong_route_rate": 0.0},
    )
    monkeypatch.setattr(
        hcc,
        "_fetch_runtime_metrics",
        lambda **_kwargs: {"rates": {"safety_fallback_rate": 0.0, "poll_401_rate": 0.0}, "window_seconds": 900},
    )
    monkeypatch.setattr(
        hcc,
        "run_soak_gate",
        lambda **_kwargs: {"ok": True, "ticks": 2, "route_checked": 2, "failures": 0, "checks": {}},
    )
    monkeypatch.setattr(
        hcc,
        "run_no_loop_stress",
        lambda **_kwargs: {"ok": True, "runs": 2, "failed_runs": 0, "max_failures": 0, "summary": {}},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hard_contract_check.py",
            "--strict",
            "--base-url",
            "http://127.0.0.1:8000",
            "--api-key",
            "k",
        ],
    )
    rc = hcc.main()
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert payload["ok"] is True
    assert payload["checks"]["soak_gate"]["ok"] is True
    assert payload["checks"]["no_loop_stress"]["ok"] is True


def test_hard_contract_forwards_no_loop_auth_edge_invalid_key(monkeypatch, capsys):
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        hcc,
        "_run_adversarial",
        lambda min_cases: {"ok": True, "result": {"ok": True, "total": max(500, min_cases), "passed": max(500, min_cases)}, "wrong_route_rate": 0.0},
    )
    monkeypatch.setattr(
        hcc,
        "_fetch_runtime_metrics",
        lambda **_kwargs: {"rates": {"safety_fallback_rate": 0.0, "poll_401_rate": 0.0}, "window_seconds": 900},
    )
    monkeypatch.setattr(
        hcc,
        "run_soak_gate",
        lambda **_kwargs: {"ok": True, "ticks": 2, "route_checked": 2, "failures": 0, "checks": {}},
    )

    def _fake_no_loop(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "runs": 2, "failed_runs": 0, "max_failures": 0, "summary": {}, "auth_edge": {}}

    monkeypatch.setattr(hcc, "run_no_loop_stress", _fake_no_loop)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hard_contract_check.py",
            "--strict",
            "--base-url",
            "http://127.0.0.1:8000",
            "--api-key",
            "k",
            "--no-loop-auth-edge-invalid-key",
            "forced-invalid-key",
        ],
    )
    rc = hcc.main()
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert payload["ok"] is True
    assert seen.get("auth_edge_invalid_key") == "forced-invalid-key"


def test_hard_contract_forwards_soak_startup_controls(monkeypatch, capsys):
    seen_soak: dict[str, object] = {}

    monkeypatch.setattr(
        hcc,
        "_run_adversarial",
        lambda min_cases: {"ok": True, "result": {"ok": True, "total": max(500, min_cases), "passed": max(500, min_cases)}, "wrong_route_rate": 0.0},
    )
    monkeypatch.setattr(
        hcc,
        "_fetch_runtime_metrics",
        lambda **_kwargs: {"rates": {"safety_fallback_rate": 0.0, "poll_401_rate": 0.0}, "window_seconds": 900},
    )

    def _fake_soak(**kwargs):
        seen_soak.update(kwargs)
        return {"ok": True, "ticks": 2, "route_checked": 2, "failures": 0, "checks": {}}

    monkeypatch.setattr(hcc, "run_soak_gate", _fake_soak)
    monkeypatch.setattr(
        hcc,
        "run_no_loop_stress",
        lambda **_kwargs: {"ok": True, "runs": 2, "failed_runs": 0, "max_failures": 0, "summary": {}, "auth_edge": {}},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hard_contract_check.py",
            "--strict",
            "--base-url",
            "http://127.0.0.1:8000",
            "--api-key",
            "k",
            "--soak-startup-transport-grace",
            "2",
            "--soak-min-route-attempt-ticks",
            "5",
        ],
    )
    rc = hcc.main()
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert payload["ok"] is True
    assert seen_soak.get("startup_transport_grace") == 2
    assert seen_soak.get("min_route_attempt_ticks") == 5


def test_hard_contract_fails_on_route_confidence_thresholds(monkeypatch, capsys):
    monkeypatch.setattr(
        hcc,
        "_run_adversarial",
        lambda min_cases: {"ok": True, "result": {"ok": True, "total": max(500, min_cases), "passed": max(500, min_cases)}, "wrong_route_rate": 0.0},
    )
    monkeypatch.setattr(
        hcc,
        "_fetch_runtime_metrics",
        lambda **_kwargs: {
            "rates": {
                "safety_fallback_rate": 0.0,
                "poll_401_rate": 0.0,
                "ambiguous_route_rate": 0.2,
                "low_confidence_route_rate": 0.8,
            },
            "window_seconds": 900,
        },
    )
    monkeypatch.setattr(
        hcc,
        "run_soak_gate",
        lambda **_kwargs: {"ok": True, "ticks": 2, "route_checked": 2, "failures": 0, "checks": {}},
    )
    monkeypatch.setattr(
        hcc,
        "run_no_loop_stress",
        lambda **_kwargs: {"ok": True, "runs": 2, "failed_runs": 0, "max_failures": 0, "summary": {}},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hard_contract_check.py",
            "--strict",
            "--base-url",
            "http://127.0.0.1:8000",
            "--api-key",
            "k",
            "--max-ambiguous-route-rate",
            "0.05",
            "--max-low-confidence-route-rate",
            "0.50",
        ],
    )
    rc = hcc.main()
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 1
    assert payload["ok"] is False
    assert payload["checks"]["ambiguous_route_threshold"]["ok"] is False
    assert payload["checks"]["low_confidence_route_threshold"]["ok"] is False
