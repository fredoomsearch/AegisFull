from __future__ import annotations

from app.services import validation_state


def test_validation_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(validation_state, "STATE_FILE", tmp_path / "validation_state.json")

    validation_state.start_flow("startup_gate", ["pytest-smoke", "readyz"])
    validation_state.mark_step("startup_gate", "pytest-smoke", "passed", "ok")
    validation_state.mark_step("startup_gate", "readyz", "failed", "not-ready")
    validation_state.finish_flow("startup_gate", "failed", "readyz")

    data = validation_state.snapshot()
    flow = data["flows"]["startup_gate"]
    assert flow["status"] == "failed"
    assert flow["detail"] == "readyz"
    assert flow["steps"]["pytest-smoke"]["status"] == "passed"
    assert flow["steps"]["readyz"]["status"] == "failed"
    assert data["last_updated_ms"] >= flow["updated_at_ms"]
