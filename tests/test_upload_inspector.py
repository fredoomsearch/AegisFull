from __future__ import annotations

import importlib
from pathlib import Path

import app.services.upload_inspector as inspector_mod


def _reload_inspector(tmp_upload_root: Path):
    import os

    os.environ["FILES_UPLOAD_ROOT"] = str(tmp_upload_root)
    return importlib.reload(inspector_mod)


def test_resolve_upload_path_accepts_upload_root(tmp_path):
    upload_root = tmp_path / "uploads"
    proj = upload_root / "proj_a"
    proj.mkdir(parents=True)

    inspector = _reload_inspector(upload_root)
    got = inspector.resolve_upload_path(str(proj))
    assert got is not None
    assert got == proj.resolve()


def test_resolve_upload_path_rejects_outside(tmp_path):
    upload_root = tmp_path / "uploads"
    outside = tmp_path / "outside_proj"
    outside.mkdir(parents=True)

    inspector = _reload_inspector(upload_root)
    got = inspector.resolve_upload_path(str(outside))
    assert got is None


def test_extract_upload_path_from_text(tmp_path):
    upload_root = tmp_path / "uploads"
    proj = upload_root / "proj_b"
    proj.mkdir(parents=True)

    inspector = _reload_inspector(upload_root)
    text = f"what contains {proj} ?"
    found = inspector.extract_upload_path_from_text(text)
    assert found is not None
    assert "proj_b" in found


def test_resolve_upload_path_rejects_embedded_null_byte(tmp_path):
    upload_root = tmp_path / "uploads"
    proj = upload_root / "proj_null"
    proj.mkdir(parents=True)

    inspector = _reload_inspector(upload_root)
    got = inspector.resolve_upload_path(f"{proj}\x00bad")
    assert got is None


def test_inspect_upload_tree_counts_files(tmp_path):
    upload_root = tmp_path / "uploads"
    proj = upload_root / "proj_c"
    (proj / "src").mkdir(parents=True)
    (proj / "README.md").write_text("hello", encoding="utf-8")
    (proj / "src" / "main.py").write_text("print(1)", encoding="utf-8")

    inspector = _reload_inspector(upload_root)
    info = inspector.inspect_upload_tree(proj.resolve(), sample_limit=10)
    assert info["files"] == 2
    assert info["dirs"] >= 1
    assert info["bytes"] > 0
    assert info["sample_files"]
