from __future__ import annotations

import pytest

from fastapi import HTTPException

from app.api import toolssupport


def test_legacy_tools_gate_always_410():
    with pytest.raises(HTTPException) as exc:
        toolssupport._legacy_tools_gate()
    assert exc.value.status_code == 410
