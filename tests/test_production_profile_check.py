from __future__ import annotations

from app.scripts import production_profile_check as ppc


def test_run_checks_strict_profile_happy_path(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    monkeypatch.setenv("AEGIS_AUTH_MODE", "on")
    monkeypatch.setenv("AEGIS_API_KEY", "A" * 32)
    monkeypatch.setenv("FILES_API_KEY", "B" * 32)
    monkeypatch.setenv("ADMIN_API_KEY", "C" * 32)
    monkeypatch.setenv("AEGIS_CORS_ORIGINS", "https://aegis.example.com")
    monkeypatch.setenv("AEGIS_HSTS_SECONDS", "31536000")
    monkeypatch.setenv("FILES_AV_FAIL_OPEN", "0")
    monkeypatch.setenv("AEGIS_IMAGE_ENDPOINT", "http://127.0.0.1:8188/prompt")
    monkeypatch.setattr(ppc, "find_brave_binary", lambda: "/usr/bin/google-chrome")
    monkeypatch.setattr(ppc, "_check_tcp_reachable", lambda *_a, **_k: (True, "ok"))

    out = ppc.run_checks(require_browser=True, require_image_endpoint=True)
    assert out["ok"] is True
    assert out["failed"] == 0


def test_run_checks_detects_security_issues(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "standard")
    monkeypatch.setenv("AEGIS_AUTH_MODE", "off")
    monkeypatch.setenv("AEGIS_API_KEY", "my-secret-key")
    monkeypatch.setenv("FILES_API_KEY", "short")
    monkeypatch.setenv("ADMIN_API_KEY", "short")
    monkeypatch.setenv("AEGIS_CORS_ORIGINS", "*")
    monkeypatch.setenv("AEGIS_HSTS_SECONDS", "0")
    monkeypatch.setenv("FILES_AV_FAIL_OPEN", "1")
    monkeypatch.delenv("AEGIS_IMAGE_ENDPOINT", raising=False)
    monkeypatch.setattr(ppc, "find_brave_binary", lambda: None)

    out = ppc.run_checks(require_browser=True, require_image_endpoint=True)
    assert out["ok"] is False
    names = {row["name"] for row in out["checks"] if not row["ok"]}
    assert "runtime_profile" in names
    assert "auth_mode" in names
    assert "AEGIS_API_KEY" in names
    assert "cors_origins" in names
    assert "hsts_seconds" in names
    assert "av_fail_open" in names
    assert "browser_binary" in names
    assert "image_endpoint" in names

