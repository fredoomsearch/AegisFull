from __future__ import annotations

from app.scripts.adversarial_eval_check import run_adversarial_eval_cases


def test_adversarial_eval_cases_pass_and_cover_500_plus():
    result = run_adversarial_eval_cases(min_cases=500)
    assert result["ok"] is True
    assert int(result["total"]) >= 500
    assert int(result["passed"]) == int(result["total"])
