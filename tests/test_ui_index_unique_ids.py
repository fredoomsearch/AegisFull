from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


def test_ui_index_has_unique_dom_ids() -> None:
    html = (Path(__file__).resolve().parents[1] / "ui" / "index.html").read_text(encoding="utf-8")
    ids = re.findall(r"\bid=['\"]([^'\"]+)['\"]", html)
    counts = Counter(ids)
    duplicated = sorted([name for name, qty in counts.items() if qty > 1])
    assert duplicated == []
