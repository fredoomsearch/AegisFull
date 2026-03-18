import py_compile
from pathlib import Path


def test_browser_smoke_script_compiles():
    target = Path(__file__).resolve().parents[1] / "app" / "scripts" / "browser_smoke.py"
    py_compile.compile(str(target), doraise=True)


def test_browser_smoke_uses_python_webdriver_refresh_api():
    target = Path(__file__).resolve().parents[1] / "app" / "scripts" / "browser_smoke.py"
    src = target.read_text(encoding="utf-8")
    assert ".navigate().refresh()" not in src
    assert "driver.refresh()" in src


def test_browser_smoke_uses_keyboard_submit_with_fallback_click():
    target = Path(__file__).resolve().parents[1] / "app" / "scripts" / "browser_smoke.py"
    src = target.read_text(encoding="utf-8")
    assert "Keys.ENTER" in src
    assert "send_btn.click()" in src
