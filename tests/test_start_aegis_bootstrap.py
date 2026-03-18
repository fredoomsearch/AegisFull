from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


SCRIPT_SRC = Path(__file__).resolve().parents[1] / "start_aegis.sh"


def _write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_fake_python(path: Path, label: str) -> None:
    _write_exec(
        path,
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"" + label + ":$0 $*\" > \"$FAKE_OUT\"\n"
        "exit 0\n",
    )


def _write_activate(path: Path, venv_root: Path) -> None:
    _write_exec(
        path,
        "#!/usr/bin/env bash\n"
        f'export VIRTUAL_ENV="{venv_root}"\n'
        f'export PATH="{venv_root / "bin"}:$PATH"\n',
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app" / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / "app" / "scripts" / "start_with_preflight.py").write_text("print('stub')\n", encoding="utf-8")
    (repo / "start_aegis.sh").write_text(SCRIPT_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "start_aegis.sh").chmod((repo / "start_aegis.sh").stat().st_mode | stat.S_IXUSR)
    return repo


def test_start_aegis_prefers_project_venv_by_default(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    project_venv = repo / "venv"
    foreign_venv = tmp_path / "foreign"
    out_file = tmp_path / "chosen_python.txt"

    _write_fake_python(project_venv / "bin" / "python", "project")
    _write_activate(project_venv / "bin" / "activate", project_venv)
    _write_fake_python(foreign_venv / "bin" / "python", "foreign")

    env = os.environ.copy()
    env.update(
        {
            "AEGIS_API_KEY": "k",
            "FILES_API_KEY": "k",
            "FAKE_OUT": str(out_file),
            "VIRTUAL_ENV": str(foreign_venv),
        }
    )

    completed = subprocess.run(
        ["bash", str(repo / "start_aegis.sh"), "--sentinel"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    chosen = out_file.read_text(encoding="utf-8").strip()
    assert chosen.startswith("project:")
    assert str(project_venv / "bin" / "python") in chosen


def test_start_aegis_can_respect_active_venv_when_enabled(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    project_venv = repo / "venv"
    foreign_venv = tmp_path / "foreign"
    out_file = tmp_path / "chosen_python.txt"

    _write_fake_python(project_venv / "bin" / "python", "project")
    _write_activate(project_venv / "bin" / "activate", project_venv)
    _write_fake_python(foreign_venv / "bin" / "python", "foreign")

    env = os.environ.copy()
    env.update(
        {
            "AEGIS_API_KEY": "k",
            "FILES_API_KEY": "k",
            "AEGIS_RESPECT_ACTIVE_VENV": "1",
            "FAKE_OUT": str(out_file),
            "VIRTUAL_ENV": str(foreign_venv),
        }
    )

    completed = subprocess.run(
        ["bash", str(repo / "start_aegis.sh"), "--sentinel"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    chosen = out_file.read_text(encoding="utf-8").strip()
    assert chosen.startswith("foreign:")
    assert str(foreign_venv / "bin" / "python") in chosen
