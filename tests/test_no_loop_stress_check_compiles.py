import py_compile
from pathlib import Path


def test_no_loop_stress_check_script_compiles():
    target = Path(__file__).resolve().parents[1] / "app" / "scripts" / "no_loop_stress_check.py"
    py_compile.compile(str(target), doraise=True)
