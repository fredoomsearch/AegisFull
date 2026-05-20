from __future__ import annotations

from pathlib import Path
import sys

from app.scripts import verify_full


def test_verify_full_runtime_profile_default_normalizes_env(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    assert verify_full._runtime_profile_default() == "strict"
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "unexpected")
    assert verify_full._runtime_profile_default() == "standard"


def test_verify_full_steps_include_host_prereq():
    assert verify_full.VERIFY_FULL_STEPS[0] == "host-prereq"


def test_verify_full_parse_args_reads_no_loop_auth_edge_env(monkeypatch):
    monkeypatch.setenv("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_EVERY", "4")
    monkeypatch.setenv("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_INVALID_KEY", "forced-invalid-key")
    monkeypatch.setattr(sys, "argv", ["verify_full.py"])
    args = verify_full.parse_args()
    assert args.no_loop_auth_edge_every == 4
    assert args.no_loop_auth_edge_invalid_key == "forced-invalid-key"


def test_verify_full_host_prereq_rejects_invalid_scheme():
    ok, detail = verify_full._host_prereq("ftp://example.com", timeout=5)
    assert ok is False
    assert "invalid-base-url-scheme" in detail


def test_verify_full_host_prereq_checks_healthz(monkeypatch):
    class _Resp:
        status_code = 200

    monkeypatch.setattr(verify_full.requests, "get", lambda *_args, **_kwargs: _Resp())
    ok, detail = verify_full._host_prereq("http://127.0.0.1:8000", timeout=5)
    assert ok is True
    assert detail == "ok"


def test_verify_full_check_readyz_strict_rejects_degraded(monkeypatch):
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ready": True, "status": "degraded"}

    monkeypatch.setattr(verify_full.requests, "get", lambda *_args, **_kwargs: _Resp())
    ok, detail, data = verify_full._check_readyz(
        "http://127.0.0.1:8000",
        "k",
        timeout=5,
        strict=True,
        product_track="full",
    )
    assert ok is False
    assert "strict-readyz-requires-status-ready" in detail
    assert isinstance(data, dict)


def test_verify_full_check_readyz_strict_accepts_ready(monkeypatch):
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ready": True, "status": "ready"}

    monkeypatch.setattr(verify_full.requests, "get", lambda *_args, **_kwargs: _Resp())
    ok, detail, data = verify_full._check_readyz(
        "http://127.0.0.1:8000",
        "k",
        timeout=5,
        strict=True,
        product_track="full",
    )
    assert ok is True
    assert detail == "ok"
    assert isinstance(data, dict)


def test_verify_full_check_readyz_strict_core_accepts_degraded(monkeypatch):
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ready": True, "status": "degraded"}

    monkeypatch.setattr(verify_full.requests, "get", lambda *_args, **_kwargs: _Resp())
    ok, detail, data = verify_full._check_readyz(
        "http://127.0.0.1:8000",
        "k",
        timeout=5,
        strict=True,
        product_track="core",
    )
    assert ok is True
    assert detail == "ok"
    assert isinstance(data, dict)


def test_verify_full_strict_wrapper_pins_runtime_profile_and_track():
    target = Path(__file__).resolve().parents[1] / "verify_full_strict.sh"
    src = target.read_text(encoding="utf-8")

    assert "--runtime-profile strict" in src
    assert "--product-track full" in src
    assert "--strict-browser-smoke" in src


def test_verify_full_readyz_debug_lines_include_process_and_degraded_context():
    lines = verify_full._readyz_debug_lines(
        "http://127.0.0.1:8000",
        {
            "status": "degraded",
            "process": {"pid": 123, "hostname": "host-a", "uptime_s": 42.1},
            "degraded_reasons": ["image:fallback-only", "clamav:missing"],
            "checks": {"llm": True, "image": False},
        },
    )
    assert any("pid=123" in line for line in lines)
    assert any("readyz.status: degraded" in line for line in lines)
    assert any("degraded_reasons: image:fallback-only, clamav:missing" in line for line in lines)
    assert any("checks:" in line for line in lines)


def test_verify_full_strict_requires_base_url(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        base_url = ""
        api_key = ""
        files_api_key = ""
        health_timeout = 5
        pytest_timeout = 60
        e2e_timeout = 60
        browser_smoke_cmd = ""
        strict_browser_smoke = False
        skip_ui_contract = False
        skip_hard_contract = False
        hard_contract_timeout = 60
        skip_pytest = False
        skip_e2e = False

    marks = []
    finishes = []
    monkeypatch.setattr(verify_full, "parse_args", lambda: _Args())
    monkeypatch.setattr(verify_full, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "mark_step", lambda *a, **_k: marks.append(a))
    monkeypatch.setattr(verify_full, "finish_flow", lambda *a, **_k: finishes.append(a))
    rc = verify_full.main()
    assert rc == 2
    assert any("host-prereq" in m for m in marks)
    assert finishes and finishes[-1][1] == "failed"


def test_verify_full_strict_disallows_skip_e2e(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        base_url = "http://127.0.0.1:8000"
        api_key = ""
        files_api_key = ""
        health_timeout = 5
        pytest_timeout = 60
        e2e_timeout = 60
        browser_smoke_cmd = ""
        strict_browser_smoke = False
        skip_ui_contract = False
        skip_hard_contract = False
        hard_contract_timeout = 60
        skip_pytest = False
        skip_e2e = True

    marks = []
    monkeypatch.setattr(verify_full, "parse_args", lambda: _Args())
    monkeypatch.setattr(verify_full, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "mark_step", lambda *a, **_k: marks.append(a))
    monkeypatch.setattr(verify_full, "finish_flow", lambda *_a, **_k: None)
    rc = verify_full.main()
    assert rc == 2
    assert any("e2e-strict" in m for m in marks)


def test_verify_full_strict_disallows_skip_hard_contract(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        base_url = "http://127.0.0.1:8000"
        api_key = ""
        files_api_key = ""
        health_timeout = 5
        pytest_timeout = 60
        e2e_timeout = 60
        browser_smoke_cmd = ""
        strict_browser_smoke = False
        skip_ui_contract = False
        skip_hard_contract = True
        hard_contract_timeout = 60
        skip_pytest = False
        skip_e2e = False

    marks = []
    monkeypatch.setattr(verify_full, "parse_args", lambda: _Args())
    monkeypatch.setattr(verify_full, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "mark_step", lambda *a, **_k: marks.append(a))
    monkeypatch.setattr(verify_full, "finish_flow", lambda *_a, **_k: None)
    rc = verify_full.main()
    assert rc == 2
    assert any("hard-contract" in m for m in marks)


def test_verify_full_strict_disallows_skip_no_loop_stress(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        base_url = "http://127.0.0.1:8000"
        api_key = ""
        files_api_key = ""
        health_timeout = 5
        pytest_timeout = 60
        e2e_timeout = 60
        browser_smoke_cmd = ""
        strict_browser_smoke = False
        skip_ui_contract = False
        skip_hard_contract = False
        skip_no_loop_stress = True
        hard_contract_timeout = 60
        no_loop_timeout = 60
        no_loop_runs = 6
        skip_pytest = False
        skip_e2e = False

    marks = []
    monkeypatch.setattr(verify_full, "parse_args", lambda: _Args())
    monkeypatch.setattr(verify_full, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "mark_step", lambda *a, **_k: marks.append(a))
    monkeypatch.setattr(verify_full, "finish_flow", lambda *_a, **_k: None)
    rc = verify_full.main()
    assert rc == 2
    assert any("no-loop-stress" in m for m in marks)


def test_verify_full_strict_fails_when_readyz_degraded(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        base_url = "http://127.0.0.1:8000"
        api_key = "k"
        files_api_key = "k"
        health_timeout = 5
        pytest_timeout = 60
        e2e_timeout = 60
        browser_smoke_cmd = ""
        strict_browser_smoke = False
        skip_ui_contract = False
        skip_hard_contract = False
        hard_contract_timeout = 60
        skip_pytest = False
        skip_e2e = False

    marks = []
    finishes = []
    monkeypatch.setattr(verify_full, "parse_args", lambda: _Args())
    monkeypatch.setattr(verify_full, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "mark_step", lambda *a, **_k: marks.append(a))
    monkeypatch.setattr(verify_full, "finish_flow", lambda *a, **_k: finishes.append(a))
    monkeypatch.setattr(verify_full, "_host_prereq", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(verify_full, "_run", lambda *_a, **_k: 0)
    monkeypatch.setattr(verify_full, "_check_readyz", lambda *_a, **_k: (False, "strict-readyz-requires-status-ready:degraded"))
    rc = verify_full.main()
    assert rc == 2
    assert any(step == "readyz" and status == "failed" for _flow, step, status, *_rest in marks)
    assert finishes and finishes[-1][2] == "readyz"


def test_verify_full_strict_passes_when_readyz_ready(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        base_url = "http://127.0.0.1:8000"
        api_key = "k"
        files_api_key = "k"
        health_timeout = 5
        pytest_timeout = 60
        e2e_timeout = 60
        browser_smoke_cmd = "echo browser-ok"
        strict_browser_smoke = False
        skip_ui_contract = False
        skip_hard_contract = False
        hard_contract_timeout = 60
        skip_pytest = False
        skip_e2e = False

    marks = []
    finishes = []
    monkeypatch.setattr(verify_full, "parse_args", lambda: _Args())
    monkeypatch.setattr(verify_full, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "mark_step", lambda *a, **_k: marks.append(a))
    monkeypatch.setattr(verify_full, "finish_flow", lambda *a, **_k: finishes.append(a))
    monkeypatch.setattr(verify_full, "_host_prereq", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(verify_full, "_run", lambda *_a, **_k: 0)
    monkeypatch.setattr(verify_full, "_check_readyz", lambda *_a, **_k: (True, "ok"))
    rc = verify_full.main()
    assert rc == 0
    assert any(step == "readyz" and status == "passed" for _flow, step, status, *_rest in marks)
    assert finishes and finishes[-1][1] == "passed"


def test_verify_full_forwards_no_loop_auth_edge_controls(monkeypatch):
    class _Args:
        runtime_profile = "standard"
        base_url = "http://127.0.0.1:8000"
        api_key = "k"
        files_api_key = "k"
        health_timeout = 5
        pytest_timeout = 60
        e2e_timeout = 60
        browser_smoke_cmd = ""
        strict_browser_smoke = False
        skip_ui_contract = True
        skip_hard_contract = False
        skip_no_loop_stress = False
        hard_contract_timeout = 60
        no_loop_timeout = 60
        no_loop_runs = 6
        no_loop_request_timeout = 33
        no_loop_max_seconds_per_run = 22.5
        max_no_loop_failures = 1
        no_loop_auth_edge_every = 2
        no_loop_auth_edge_invalid_key = "forced-invalid-key"
        max_no_loop_auth_edge_unexpected_failures = 0
        skip_pytest = True
        skip_e2e = True

    cmds: list[list[str]] = []
    monkeypatch.setattr(verify_full, "parse_args", lambda: _Args())
    monkeypatch.setattr(verify_full, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "mark_step", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "finish_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(verify_full, "_host_prereq", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(verify_full, "_check_readyz", lambda *_a, **_k: (True, "ok"))

    def _capture_run(cmd, **_kwargs):
        cmds.append(list(cmd))
        return 0

    monkeypatch.setattr(verify_full, "_run", _capture_run)
    rc = verify_full.main()
    assert rc == 0

    hard_contract_cmd = next(c for c in cmds if len(c) >= 3 and c[2] == "app.scripts.hard_contract_check")
    assert "--no-loop-auth-edge-every" in hard_contract_cmd
    assert "--no-loop-auth-edge-invalid-key" in hard_contract_cmd
    assert "forced-invalid-key" in hard_contract_cmd

    no_loop_cmd = next(c for c in cmds if len(c) >= 3 and c[2] == "app.scripts.no_loop_stress_check")
    assert "--auth-edge-every" in no_loop_cmd
    assert "--auth-edge-invalid-key" in no_loop_cmd
    assert "forced-invalid-key" in no_loop_cmd
