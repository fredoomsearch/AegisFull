import py_compile
from pathlib import Path


def test_soak_gate_script_compiles():
    target = Path(__file__).resolve().parents[1] / "app" / "scripts" / "soak_gate.py"
    py_compile.compile(str(target), doraise=True)

