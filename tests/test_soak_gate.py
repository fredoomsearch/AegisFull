from __future__ import annotations

from app.scripts import soak_gate


def test_soak_gate_retries_transient_transport_error(monkeypatch):
    clock = {"t": -20.0}

    def _fake_time():
        clock["t"] += 20.0
        return float(clock["t"])

    monkeypatch.setattr(soak_gate.time, "time", _fake_time)
    monkeypatch.setattr(soak_gate.time, "sleep", lambda *_a, **_k: None)

    post_calls = {"count": 0}

    def _fake_get_json(url: str, **_kwargs):
        if url.endswith("/system/metrics"):
            return {"rates": {"safety_fallback_rate": 0.0, "poll_401_rate": 0.0}}
        return {}

    def _fake_post_json(_url: str, _payload: dict, **_kwargs):
        post_calls["count"] += 1
        if post_calls["count"] == 1:
            raise RuntimeError("transient transport error")
        return {"context": {"source_plan": "web_only"}}

    monkeypatch.setattr(soak_gate, "_get_json", _fake_get_json)
    monkeypatch.setattr(soak_gate, "_post_json", _fake_post_json)

    payload = soak_gate.run_soak_gate(
        base_url="http://127.0.0.1:8000",
        api_key="k",
        duration_hours=0.01,
        interval_seconds=0.1,
        attempts_per_tick=2,
        max_transport_failures=0,
        min_route_checked=1,
    )
    assert payload["ok"] is True
    assert payload["route_checked"] >= 1
    assert payload["failures"] == 0
    assert post_calls["count"] >= 2


def test_soak_gate_startup_grace_ignores_first_failed_tick_until_route_recovers(monkeypatch):
    clock = {"t": 0.0}

    def _fake_time():
        clock["t"] += 1.0
        return float(clock["t"])

    monkeypatch.setattr(soak_gate.time, "time", _fake_time)
    monkeypatch.setattr(soak_gate.time, "sleep", lambda *_a, **_k: None)

    calls = {"count": 0}

    def _fake_get_json(url: str, **_kwargs):
        if url.endswith("/system/metrics"):
            return {"rates": {"safety_fallback_rate": 0.0, "poll_401_rate": 0.0}}
        return {}

    def _fake_post_json(_url: str, _payload: dict, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("startup transport miss")
        return {"context": {"source_plan": "web_only"}}

    monkeypatch.setattr(soak_gate, "_get_json", _fake_get_json)
    monkeypatch.setattr(soak_gate, "_post_json", _fake_post_json)

    payload = soak_gate.run_soak_gate(
        base_url="http://127.0.0.1:8000",
        api_key="k",
        duration_hours=0.0001,
        interval_seconds=0.1,
        attempts_per_tick=1,
        max_transport_failures=0,
        min_route_checked=1,
        startup_transport_grace=1,
        min_route_attempt_ticks=2,
    )
    assert payload["ok"] is True
    assert payload["route_checked"] >= 1
    assert payload["failures"] == 0
    assert len(payload.get("startup_warnings") or []) >= 1


def test_soak_gate_requires_route_coverage(monkeypatch):
    clock = {"t": -20.0}

    def _fake_time():
        clock["t"] += 20.0
        return float(clock["t"])

    monkeypatch.setattr(soak_gate.time, "time", _fake_time)
    monkeypatch.setattr(soak_gate.time, "sleep", lambda *_a, **_k: None)

    def _fake_get_json(url: str, **_kwargs):
        if url.endswith("/system/metrics"):
            return {"rates": {"safety_fallback_rate": 0.0, "poll_401_rate": 0.0}}
        return {}

    def _always_fail_post(_url: str, _payload: dict, **_kwargs):
        raise RuntimeError("transport down")

    monkeypatch.setattr(soak_gate, "_get_json", _fake_get_json)
    monkeypatch.setattr(soak_gate, "_post_json", _always_fail_post)

    payload = soak_gate.run_soak_gate(
        base_url="http://127.0.0.1:8000",
        api_key="k",
        duration_hours=0.01,
        interval_seconds=0.1,
        attempts_per_tick=1,
        max_transport_failures=10,
        min_route_checked=1,
    )
    assert payload["ok"] is False
    assert payload["route_checked"] == 0
    assert payload["checks"]["route_coverage"]["ok"] is False
