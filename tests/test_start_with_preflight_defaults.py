from __future__ import annotations

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


def test_runtime_profile_default_normalizes_env(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    assert start_with_preflight._runtime_profile_default() == "strict"
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "unexpected")
    assert start_with_preflight._runtime_profile_default() == "standard"


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


def test_start_with_preflight_strict_disallows_skip_no_loop_stress(monkeypatch):
    class _Args:
        runtime_profile = "strict"
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
