from __future__ import annotations

from app.scripts import doctor


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


def test_http_json_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def _fake_get(url: str, headers=None, timeout=0):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("first-call-timeout")
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(doctor.requests, "get", _fake_get)
    ok, detail, payload, status = doctor._http_json(  # noqa: SLF001
        "http://127.0.0.1:8000",
        "/system/readyz",
        "",
        timeout=2,
        attempts=2,
        backoff_seconds=0.0,
    )
    assert ok is True
    assert detail == "ok"
    assert status == 200
    assert payload == {"ok": True}
    assert calls["n"] == 2


def test_http_json_returns_last_error_after_retries(monkeypatch):
    def _fake_get(url: str, headers=None, timeout=0):  # noqa: ARG001
        raise TimeoutError("always-timeout")

    monkeypatch.setattr(doctor.requests, "get", _fake_get)
    ok, detail, payload, status = doctor._http_json(  # noqa: SLF001
        "http://127.0.0.1:8000",
        "/system/readyz",
        "",
        timeout=2,
        attempts=2,
        backoff_seconds=0.0,
    )
    assert ok is False
    assert "always-timeout" in detail
    assert payload is None
    assert status == 0
