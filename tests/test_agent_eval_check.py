from __future__ import annotations

from app.scripts.agent_eval_check import run_agent_eval_cases


def test_agent_eval_cases_pass():
    result = run_agent_eval_cases()
    assert result["ok"] is True
    assert result["passed"] == result["total"]
    assert result["total"] >= 16
