from __future__ import annotations

from app.scripts import no_loop_stress_check as nls


def test_no_loop_stress_passes_when_budgets_and_stop_reason_are_valid(monkeypatch):
    monkeypatch.setattr(nls, "time", type("_T", (), {"perf_counter": staticmethod(lambda: 1.0), "sleep": staticmethod(lambda *_a, **_k: None)}))
    monkeypatch.setattr(
        nls,
        "_post_json",
        lambda *_a, **_k: {
            "ok": True,
            "iterations": [{"iteration": 1}],
            "iterations_completed": 1,
            "total_tool_calls": 1,
            "stop_reason": "plan_satisfied",
        },
    )

    payload = nls.run_no_loop_stress(
        base_url="http://127.0.0.1:8000",
        api_key="k",
        runs=3,
        request_timeout=5,
        max_seconds_per_run=5.0,
        max_iterations=3,
        max_total_tool_calls=8,
        max_failures=0,
    )
    assert payload["ok"] is True
    assert payload["failed_runs"] == 0
    assert payload["summary"]["stop_reason_counts"].get("plan_satisfied") == 3


def test_no_loop_stress_fails_on_tool_budget_exceeded(monkeypatch):
    monkeypatch.setattr(nls, "time", type("_T", (), {"perf_counter": staticmethod(lambda: 1.0), "sleep": staticmethod(lambda *_a, **_k: None)}))
    monkeypatch.setattr(
        nls,
        "_post_json",
        lambda *_a, **_k: {
            "ok": True,
            "iterations": [{"iteration": 1}],
            "iterations_completed": 1,
            "total_tool_calls": 99,
            "stop_reason": "plan_satisfied",
        },
    )

    payload = nls.run_no_loop_stress(
        base_url="http://127.0.0.1:8000",
        api_key="k",
        runs=2,
        request_timeout=5,
        max_seconds_per_run=5.0,
        max_iterations=3,
        max_total_tool_calls=8,
        max_failures=0,
    )
    assert payload["ok"] is False
    assert payload["failed_runs"] >= 1


def test_no_loop_stress_auth_edge_counts_expected_unauthorized(monkeypatch):
    monkeypatch.setattr(nls, "time", type("_T", (), {"perf_counter": staticmethod(lambda: 1.0), "sleep": staticmethod(lambda *_a, **_k: None)}))

    def _fake_post(_url: str, _payload: dict, *, headers: dict, timeout: int):  # noqa: ANN001
        _ = timeout
        key = str(headers.get("X-API-Key") or "")
        if key == "bad-edge-key":
            raise RuntimeError("POST status=401 body=unauthorized")
        return {
            "ok": True,
            "iterations": [{"iteration": 1}],
            "iterations_completed": 1,
            "total_tool_calls": 1,
            "stop_reason": "plan_satisfied",
        }

    monkeypatch.setattr(nls, "_post_json", _fake_post)

    payload = nls.run_no_loop_stress(
        base_url="http://127.0.0.1:8000",
        api_key="good-key",
        runs=4,
        auth_edge_every=2,
        auth_edge_invalid_key="bad-edge-key",
        max_auth_edge_unexpected_failures=0,
    )
    assert payload["ok"] is True
    assert payload["auth_edge"]["runs"] == 2
    assert payload["auth_edge"]["unauthorized"] == 2
    assert payload["auth_edge"]["unexpected_failures"] == 0


def test_no_loop_stress_auth_edge_unexpected_success_fails(monkeypatch):
    monkeypatch.setattr(nls, "time", type("_T", (), {"perf_counter": staticmethod(lambda: 1.0), "sleep": staticmethod(lambda *_a, **_k: None)}))
    monkeypatch.setattr(
        nls,
        "_post_json",
        lambda *_a, **_k: {
            "ok": True,
            "iterations": [{"iteration": 1}],
            "iterations_completed": 1,
            "total_tool_calls": 1,
            "stop_reason": "plan_satisfied",
        },
    )

    payload = nls.run_no_loop_stress(
        base_url="http://127.0.0.1:8000",
        api_key="good-key",
        runs=2,
        auth_edge_every=1,
        max_auth_edge_unexpected_failures=0,
    )
    assert payload["ok"] is False
    assert payload["auth_edge"]["unexpected_failures"] >= 0
    assert payload["failed_runs"] >= 1
