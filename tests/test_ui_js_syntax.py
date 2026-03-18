import shutil
import subprocess
from pathlib import Path

import pytest


def test_ui_app_js_has_valid_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed; skipping UI JS syntax check")

    app_js = Path(__file__).resolve().parents[1] / "ui" / "app.js"
    assert app_js.exists(), "ui/app.js missing"

    proc = subprocess.run(
        [node, "--check", str(app_js)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout

