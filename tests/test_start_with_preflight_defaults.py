from __future__ import annotations

import types
import sys

from app.scripts import start_with_preflight


def test_default_browser_smoke_cmd_points_to_repo_script():
    cmd = start_with_preflight._default_browser_smoke_cmd(
        "http://127.0.0.1:8000",
        "my-secret-key",
        "my-secret-key",
        strict=False,
    )
    assert "app.scripts.browser_smoke" in cmd
    assert "--base-url http://127.0.0.1:8000" in cmd
    assert "--api-key my-secret-key" in cmd
    assert "--strict" not in cmd


def test_default_browser_smoke_cmd_can_be_strict():
    cmd = start_with_preflight._default_browser_smoke_cmd(
        "http://127.0.0.1:8000",
        "my-secret-key",
        "my-secret-key",
        strict=True,
    )
    assert "app.scripts.browser_smoke" in cmd
    assert "--strict" in cmd
    assert "--crypto-proof" in cmd
    assert "--geo-proof" in cmd
    assert "--memory-speed-proof" in cmd
    assert "--web-proof" in cmd
    assert "--project-proof" not in cmd
    assert "--files-proof" not in cmd
    assert "--image-proof" not in cmd
    assert "--url-proof" not in cmd


def test_runtime_profile_default_normalizes_env(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    assert start_with_preflight._runtime_profile_default() == "strict"
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "unexpected")
    assert start_with_preflight._runtime_profile_default() == "standard"


def test_contract_mode_default_normalizes_env(monkeypatch):
    monkeypatch.setenv("AEGIS_START_CONTRACT_MODE", "strict")
    assert start_with_preflight._contract_mode_default() == "strict"
    monkeypatch.setenv("AEGIS_START_CONTRACT_MODE", "unexpected")
    assert start_with_preflight._contract_mode_default() == "full"


def test_parse_args_uses_runtime_profile_env(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    monkeypatch.setattr(sys, "argv", ["start_with_preflight.py"])
    args = start_with_preflight.parse_args()
    assert args.runtime_profile == "strict"


def test_parse_args_reads_no_loop_auth_edge_env(monkeypatch):
    monkeypatch.setenv("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_EVERY", "3")
    monkeypatch.setenv("AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_INVALID_KEY", "forced-invalid-key")
    monkeypatch.setattr(sys, "argv", ["start_with_preflight.py"])
    args = start_with_preflight.parse_args()
    assert args.no_loop_auth_edge_every == 3
    assert args.no_loop_auth_edge_invalid_key == "forced-invalid-key"


def test_parse_args_uses_contract_mode_env(monkeypatch):
    monkeypatch.setenv("AEGIS_START_CONTRACT_MODE", "none")
    monkeypatch.setattr(sys, "argv", ["start_with_preflight.py"])
    args = start_with_preflight.parse_args()
    assert args.contract_mode == "none"


def test_host_prereq_checks_require_db_config_when_db_enabled(monkeypatch):
    monkeypatch.setattr(start_with_preflight, "_port_bindable", lambda *_args, **_kwargs: (True, "ok"))
    errors, warns = start_with_preflight._host_prereq_checks(
        host="127.0.0.1",
        port=8000,
        env={},
    )
    assert warns == []
    assert any("DB required" in e for e in errors)


def test_host_prereq_checks_allow_no_db_when_disabled(monkeypatch):
    monkeypatch.setattr(start_with_preflight, "_port_bindable", lambda *_args, **_kwargs: (True, "ok"))
    errors, warns = start_with_preflight._host_prereq_checks(
        host="127.0.0.1",
        port=8000,
        env={"AEGIS_DISABLE_DB": "1"},
    )
    assert errors == []
    assert warns == []


def test_host_prereq_checks_propagate_bind_errors(monkeypatch):
    monkeypatch.setattr(start_with_preflight, "_port_bindable", lambda *_args, **_kwargs: (False, "cannot bind 127.0.0.1:8000"))
    errors, _warns = start_with_preflight._host_prereq_checks(
        host="127.0.0.1",
        port=8000,
        env={"AEGIS_DISABLE_DB": "1"},
    )
    assert any("cannot bind" in e for e in errors)


def test_check_readyz_strict_rejects_degraded(monkeypatch):
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ready": True, "status": "degraded"}

    monkeypatch.setattr(start_with_preflight.requests, "get", lambda *_a, **_k: _Resp())
    ok, detail, _data = start_with_preflight._check_readyz(
        "http://127.0.0.1:8000",
        "k",
        strict=True,
        product_track="full",
    )
    assert ok is False
    assert "strict-readyz-requires-status-ready" in detail


def test_check_readyz_strict_accepts_ready(monkeypatch):
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ready": True, "status": "ready"}

    monkeypatch.setattr(start_with_preflight.requests, "get", lambda *_a, **_k: _Resp())
    ok, detail, _data = start_with_preflight._check_readyz(
        "http://127.0.0.1:8000",
        "k",
        strict=True,
        product_track="full",
    )
    assert ok is True
    assert detail == "readyz ready=true"


def test_check_readyz_strict_core_accepts_degraded(monkeypatch):
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ready": True, "status": "degraded"}

    monkeypatch.setattr(start_with_preflight.requests, "get", lambda *_a, **_k: _Resp())
    ok, detail, _data = start_with_preflight._check_readyz(
        "http://127.0.0.1:8000",
        "k",
        strict=True,
        product_track="core",
    )
    assert ok is True
    assert detail == "readyz ready=true"


def test_wait_health_logs_progress_when_server_is_slow(monkeypatch, capsys):
    child = types.SimpleNamespace(poll=lambda: None)
    state = {"calls": 0, "now": 0.0}

    def fake_get(*_args, **_kwargs):
        state["calls"] += 1
        raise RuntimeError("connection refused")

    def fake_time():
        return state["now"]

    def fake_sleep(seconds):
        state["now"] += float(seconds)

    monkeypatch.setattr(start_with_preflight.requests, "get", fake_get)
    monkeypatch.setattr(start_with_preflight.time, "time", fake_time)
    monkeypatch.setattr(start_with_preflight.time, "sleep", fake_sleep)

    ok = start_with_preflight._wait_health(
        "http://127.0.0.1:8000",
        5,
        child,
        log_interval_s=2,
    )
    out = capsys.readouterr().out
    assert ok is False
    assert "[wait] healthz pending:" in out
    assert "last_error=connection refused" in out


def test_readyz_debug_lines_include_process_and_degraded_context():
    lines = start_with_preflight._readyz_debug_lines(
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


def test_start_with_preflight_strict_disallows_skip_no_loop_stress(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        contract_mode = "full"
        product_track = "full"
        app = "main:app"
        host = "127.0.0.1"
        port = 8000
        reload = False
        log_level = "info"
        api_key = "k"
        files_api_key = "k"
        admin_api_key = "k"
        check_base_url = "http://127.0.0.1:8000"
        health_timeout = 5
        e2e_timeout = 5
        preflight_timeout = 5
        pytest_timeout = 5
        pytest_smoke_tests = ""
        skip_pytest_smoke = True
        skip_preflight = True
        skip_post_e2e = True
        skip_ui_contract = False
        skip_hard_contract = False
        skip_no_loop_stress = True
        skip_browser_smoke = False
        strict_browser_smoke = False
        browser_smoke_cmd = ""
        browser_smoke_timeout = 30
        hard_contract_timeout = 30
        no_loop_timeout = 30
        no_loop_runs = 4
        strict_security = False
        strict_capabilities = False
        disable_db = True

    finished = []
    monkeypatch.setattr(start_with_preflight, "parse_args", lambda: _Args())
    monkeypatch.setattr(start_with_preflight, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(start_with_preflight, "finish_flow", lambda *a, **_k: finished.append(a))
    rc = start_with_preflight.main()
    assert rc == 2
    assert finished
    assert finished[-1][2] == "no-loop-stress-disabled-in-strict"


def test_start_with_preflight_strict_contract_can_boot_without_full_contract_gates(monkeypatch):
    class _Args:
        runtime_profile = "strict"
        contract_mode = "strict"
        product_track = "full"
        app = "main:app"
        host = "127.0.0.1"
        port = 8000
        reload = False
        log_level = "info"
        api_key = "k"
        files_api_key = "k"
        admin_api_key = "k"
        check_base_url = "http://127.0.0.1:8000"
        health_timeout = 5
        e2e_timeout = 5
        preflight_timeout = 5
        pytest_timeout = 5
        pytest_smoke_tests = ""
        skip_pytest_smoke = True
        skip_preflight = True
        skip_post_e2e = False
        skip_ui_contract = True
        skip_hard_contract = True
        skip_no_loop_stress = True
        skip_browser_smoke = True
        strict_browser_smoke = False
        browser_smoke_cmd = ""
        browser_smoke_timeout = 30
        hard_contract_timeout = 30
        no_loop_timeout = 30
        no_loop_runs = 4
        no_loop_request_timeout = 45
        no_loop_max_seconds_per_run = 35.0
        max_no_loop_failures = 0
        no_loop_auth_edge_every = 0
        no_loop_auth_edge_invalid_key = "invalid-no-loop-key"
        max_no_loop_auth_edge_unexpected_failures = 0
        strict_security = False
        strict_capabilities = False
        disable_db = True

    class _Proc:
        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def send_signal(self, _sig):
            return None

    monkeypatch.setattr(start_with_preflight, "parse_args", lambda: _Args())
    monkeypatch.setattr(start_with_preflight, "start_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(start_with_preflight, "finish_flow", lambda *_a, **_k: None)
    monkeypatch.setattr(start_with_preflight, "mark_step", lambda *_a, **_k: None)
    monkeypatch.setattr(start_with_preflight, "_security_checks", lambda *_a, **_k: ([], []))
    monkeypatch.setattr(start_with_preflight, "_host_prereq_checks", lambda **_k: ([], []))
    monkeypatch.setattr(start_with_preflight, "_wait_health", lambda *_a, **_k: True)
    monkeypatch.setattr(start_with_preflight, "_check_readyz", lambda *_a, **_k: (True, "readyz ready=true", {"status": "ready"}))
    monkeypatch.setattr(start_with_preflight, "_run_cmd", lambda *_a, **_k: 0)
    monkeypatch.setattr(start_with_preflight.subprocess, "Popen", lambda *_a, **_k: _Proc())
    monkeypatch.setattr(start_with_preflight.signal, "signal", lambda *_a, **_k: None)

    rc = start_with_preflight.main()
    assert rc == 0
