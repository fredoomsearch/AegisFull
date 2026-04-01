from __future__ import annotations

from pathlib import Path

from app.scripts import readme_exports


def test_render_shell_includes_export_prefix_and_contract_mode():
    text = readme_exports.render_shell("strict")
    assert "export AEGIS_RUNTIME_PROFILE=strict" in text
    assert "export AEGIS_START_CONTRACT_MODE=strict" in text


def test_render_env_includes_contract_mode_override():
    text = readme_exports.render_env("none")
    assert "AEGIS_START_CONTRACT_MODE=none" in text
    assert "AEGIS_RUNTIME_PROFILE=strict" in text


def test_write_env_file_writes_env_style_output(tmp_path: Path):
    target = tmp_path / ".env.strict.full.local"
    written = readme_exports.write_env_file(target, contract_mode="full", overwrite=False)
    body = written.read_text(encoding="utf-8")
    assert written == target.resolve()
    assert "AEGIS_START_CONTRACT_MODE=full" in body
    assert "export " not in body
