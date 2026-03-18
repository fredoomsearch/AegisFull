from __future__ import annotations

import json
from pathlib import Path

from app.services.project_introspection import (
    build_project_impact_report,
    build_project_improvement_ideas,
    build_project_intelligence_summary,
    build_symbol_rename_plan,
)
from app.services.project_manifest import build_project_manifest, load_project_manifest, save_project_manifest
from app.services import project_store


def test_build_project_manifest_detects_stack(tmp_path: Path):
    root = tmp_path / "sample_project"
    root.mkdir()
    (root / "README.md").write_text("# Demo Project\nUses FastAPI and React.\n", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"dependencies": {"react": "^19.0.0"}}), encoding="utf-8")
    (root / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_app():\n    assert True\n", encoding="utf-8")

    manifest = build_project_manifest(root, "sample_project", chunk_count=12, chunked_files=3)

    assert manifest["project_id"] == "sample_project"
    assert "fastapi" in manifest["frameworks"]
    assert "react" in manifest["frameworks"]
    assert "requirements.txt" in manifest["package_files"]
    assert "package.json" in manifest["package_files"]
    assert "app.py" in manifest["entrypoints"]
    assert manifest["stats"]["chunk_count"] == 12
    architecture = manifest["architecture"]
    assert architecture["backend"] is True
    assert architecture["frontend"] is True
    assert architecture["tests"] is True
    assert "backend" in architecture["layers"]
    assert "frontend" in architecture["layers"]


def test_build_project_improvement_ideas_flags_missing_ci_and_docs(tmp_path: Path):
    root = tmp_path / "idea_project"
    root.mkdir()
    (root / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")

    manifest = build_project_manifest(root, "idea_project", chunk_count=1, chunked_files=1)
    ideas = build_project_improvement_ideas(manifest, lang="en")
    idea_ids = {item.get("id") for item in ideas}

    assert "tests" in idea_ids
    assert "ci" in idea_ids
    assert "readme" in idea_ids


def test_project_intelligence_summary_and_impact_report(tmp_path: Path):
    root = tmp_path / "intelligence_project"
    (root / "app").mkdir(parents=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    (root / "app" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "from app.service import login\n\n"
        "router = APIRouter()\n\n"
        "@router.get('/login')\n"
        "def login_route():\n"
        "    return login()\n\n"
        "@router.post('/token')\n"
        "def issue_token():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from app.routes import router as auth_router\n\n"
        "app = FastAPI()\n"
        "app.include_router(auth_router, prefix='/auth')\n",
        encoding="utf-8",
    )
    (root / "app" / "controller.py").write_text(
        "from app.service import login\n\n\ndef run():\n    return login()\n",
        encoding="utf-8",
    )
    (root / "app" / "legacy.py").write_text("def login():\n    return 'legacy'\n", encoding="utf-8")
    (root / "app" / "config.py").write_text(
        "import os\n\n\ndef load_key():\n    return os.getenv('API_KEY', '')\n",
        encoding="utf-8",
    )
    (root / "app" / "format_a.py").write_text(
        "def normalize_email(value):\n    value = value.strip().lower()\n    return value\n",
        encoding="utf-8",
    )
    (root / "app" / "format_b.py").write_text(
        "def normalize_username(value):\n    value = value.strip().lower()\n    return value\n",
        encoding="utf-8",
    )
    (root / "app" / "orphan.py").write_text("def dead_helper():\n    return 1\n", encoding="utf-8")

    manifest = build_project_manifest(root, "intelligence_project", chunk_count=9, chunked_files=8)
    summary = build_project_intelligence_summary(root, manifest=manifest)

    assert summary["files_scanned"] >= 6
    assert summary["internal_edge_count"] >= 1
    assert summary["route_count"] >= 2
    assert summary["runtime_surface_count"] >= 1
    assert any(item.get("path") == "app/service.py" and int(item.get("inbound_refs") or 0) >= 1 for item in summary["hotspots"])
    assert any(item.get("path") == "app/routes.py" and int(item.get("route_count") or 0) >= 2 for item in summary["route_hotspots"])
    assert any(item.get("method") == "GET" and item.get("route") == "/login" for item in summary["routes"])
    assert any(item.get("resolved_route") == "/auth/login" and item.get("handler") == "login_route" for item in summary["routes"])
    assert any(item.get("path") == "app/main.py" and item.get("app_name") == "app" and int(item.get("served_route_count") or 0) >= 2 for item in summary["runtime_surfaces"])
    assert any(item.get("symbol") == "login" for item in summary["shared_symbol_clusters"])
    assert any(item.get("symbol") == "login" and int(item.get("reference_count") or 0) >= 1 for item in summary["symbol_hotspots"])
    assert any(item.get("symbol") == "login" and int(item.get("call_edge_count") or 0) >= 1 for item in summary["symbol_call_hotspots"])
    assert any(item.get("symbol") == "login_route" and "route-handler" in (item.get("reasons") or []) for item in summary["public_api_symbols"])
    assert any(item.get("symbol") == "login" and int(item.get("definition_count") or 0) >= 2 for item in summary["refactor_candidates"])
    assert any(item.get("symbol") == "dead_helper" and item.get("path") == "app/orphan.py" for item in summary["isolated_symbol_candidates"])
    assert any(item.get("env") == "API_KEY" for item in summary["env_var_hotspots"])
    assert any("app/format_a.py" in item.get("paths", []) and "app/format_b.py" in item.get("paths", []) for item in summary["duplicate_logic_clusters"])

    impact = build_project_impact_report(root, manifest=manifest, q="login")
    assert any(item.get("path") == "app/service.py" for item in impact["defined_in"])
    assert any(item.get("path") == "app/controller.py" for item in impact["referenced_by_files"])
    assert any(item.get("from_path") == "app/controller.py" and item.get("to_path") == "app/service.py" for item in impact["call_edges_to"])
    assert any(item.get("method") == "GET" and item.get("resolved_route") == "/auth/login" for item in impact["routes_in_scope"])
    assert any(item.get("path") == "app/main.py" and item.get("app_name") == "app" for item in impact["runtime_surfaces_in_scope"])
    assert any(item.get("symbol") == "login_route" for item in impact["public_api_symbols_in_scope"])
    assert any(item.get("symbol") == "login" for item in impact["refactor_candidates"])
    assert impact["rename_scope"]["safety"]["level"] in {"low", "medium", "high"}

    impact = build_project_impact_report(root, manifest=manifest, q="service.py")
    assert "app/service.py" in impact["matched_files"]
    assert any(item.get("path") == "app/controller.py" for item in impact["imported_by"])
    assert "app/legacy.py" in impact["same_symbol_neighbors"]

    env_impact = build_project_impact_report(root, manifest=manifest, q="config.py")
    assert any(item.get("env") == "API_KEY" for item in env_impact["env_vars_in_scope"])

    route_impact = build_project_impact_report(root, manifest=manifest, q="routes.py")
    assert any(item.get("method") == "POST" and item.get("resolved_route") == "/auth/token" for item in route_impact["routes_in_scope"])
    assert any(item.get("path") == "app/main.py" and int(item.get("served_route_count") or 0) >= 2 for item in route_impact["runtime_surfaces_in_scope"])

    isolated_impact = build_project_impact_report(root, manifest=manifest, q="orphan.py")
    assert any(item.get("symbol") == "dead_helper" for item in isolated_impact["isolated_symbols_in_scope"])

    dup_impact = build_project_impact_report(root, manifest=manifest, q="normalize_email")
    assert any("app/format_b.py" in item.get("paths", []) for item in dup_impact["duplicate_logic_neighbors"])

    rename_plan = build_symbol_rename_plan(root, manifest=manifest, symbol="login", new_symbol="authenticate")
    assert rename_plan["operation_count"] >= 2
    assert "app/service.py" in rename_plan["changed_paths"]
    assert "app/controller.py" in rename_plan["changed_paths"]
    assert any("authenticate" in item.get("content", "") for item in rename_plan["operations"])
    assert rename_plan["rename_safety"]["level"] in {"low", "medium", "high"}


def test_save_and_load_project_manifest(tmp_path: Path):
    root = tmp_path / "saved_project"
    root.mkdir()
    (root / "README.md").write_text("# Saved Project\n", encoding="utf-8")

    manifest_path = save_project_manifest(root, "saved_project", chunk_count=2, chunked_files=1)
    loaded = load_project_manifest(manifest_path)

    assert loaded is not None
    assert loaded["project_id"] == "saved_project"
    assert loaded["stats"]["chunk_count"] == 2


def test_project_store_register_and_update(tmp_path: Path, monkeypatch):
    root = tmp_path / "stored_project"
    root.mkdir()
    monkeypatch.setattr(project_store, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(project_store, "STORE_FILE", tmp_path / ".aegis_projects.json")

    record = project_store.register_project("stored_project", root, source="upload-zip", status="uploaded")
    assert record["project_id"] == "stored_project"

    updated = project_store.update_project("stored_project", status="ingested", chunk_count=33, manifest_path=str(root / ".aegis_manifest.json"))
    assert updated is not None
    assert updated["status"] == "ingested"
    assert updated["chunk_count"] == 33

    fetched = project_store.get_project("stored_project")
    assert fetched is not None
    assert fetched["status"] == "ingested"
