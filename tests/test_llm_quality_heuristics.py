from __future__ import annotations

from app.models.llm_utils import looks_like_low_value_response


def test_looks_like_low_value_response_detects_ack_only():
    assert looks_like_low_value_response("ok") is True
    assert looks_like_low_value_response("OK.") is True
    assert looks_like_low_value_response("Sure.") is True


def test_looks_like_low_value_response_does_not_flag_code():
    assert looks_like_low_value_response("```python\nprint('ok')\n```") is False


def test_looks_like_low_value_response_does_not_flag_substantive_text():
    assert looks_like_low_value_response("Here are the steps:\n1) Do X\n2) Do Y\n") is False

