from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from app.api import files as files_api
from app.services import project_store
from app.services.project_manifest import save_project_manifest


def test_files_tree_content_and_delete_project(monkeypatch: pytest.MonkeyPatch):
    root = Path("data/uploads") / f"surface_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
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
    (root / "app" / "consumer.py").write_text(
        "from app.service import login\n\n\ndef use_login():\n    return login()\n",
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
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    save_project_manifest(root, root.name, chunk_count=10, chunked_files=9)
    project_id = root.name
    project_store.register_project(project_id, root, source="upload-zip", status="uploaded")
    removed_projects: list[str] = []
    monkeypatch.setattr(
        files_api,
        "remove_project_documents",
        lambda value: removed_projects.append(value) or 7,
    )

    try:
        tree = asyncio.run(files_api.project_tree(project_id=project_id, max_depth=3))
        data = tree.model_dump()
        flat = str(data)
        assert "service.py" in flat

        content = asyncio.run(files_api.project_content(project_id=project_id, path="app/service.py"))
        assert "def login" in content["content"]
        content_prefixed = asyncio.run(
            files_api.project_content(project_id=project_id, path=f"{project_id}/app/service.py")
        )
        assert "def login" in content_prefixed["content"]
        content_workspace_prefixed = asyncio.run(
            files_api.project_content(project_id=project_id, path=f"data/uploads/{project_id}/app/service.py")
        )
        assert "def login" in content_workspace_prefixed["content"]
        saved = asyncio.run(
            files_api.save_project_content(
                files_api.SaveContentRequest(
                    project_id=project_id,
                    path="app/service.py",
                    content="def login():\n    return 'updated'\n",
                )
            )
        )
        assert saved["saved"] is True
        updated = asyncio.run(files_api.project_content(project_id=project_id, path="app/service.py"))
        assert "updated" in updated["content"]
        preview = asyncio.run(
            files_api.diff_project_content(
                files_api.SaveContentRequest(
                    project_id=project_id,
                    path="app/service.py",
                    content="def login():\n    return 'preview'\n",
                )
            )
        )
        assert preview["changed"] is True
        assert "preview" in preview["diff"]
        created = asyncio.run(
            files_api.save_project_content(
                files_api.SaveContentRequest(
                    project_id=project_id,
                    path="app/new_service.py",
                    content="def created():\n    return 'ok'\n",
                    create=True,
                )
            )
        )
        assert created["saved"] is True
        assert created["created"] is True
        created_content = asyncio.run(files_api.project_content(project_id=project_id, path="app/new_service.py"))
        assert "def created" in created_content["content"]
        created_dir = asyncio.run(
            files_api.create_project_directory(
                files_api.CreateDirectoryRequest(
                    project_id=project_id,
                    path="app/generated",
                )
            )
        )
        assert created_dir["created"] is True
        moved_dir = asyncio.run(
            files_api.move_project_path(
                files_api.MovePathRequest(
                    project_id=project_id,
                    path="app/generated",
                    new_path="app/generated_renamed",
                )
            )
        )
        assert moved_dir["moved"] is True
        assert moved_dir["is_dir"] is True
        batch_result = asyncio.run(
            files_api.batch_apply_project_changes(
                files_api.BatchApplyRequest(
                    project_id=project_id,
                    operations=[
                        files_api.BatchApplyOperation(op="mkdir", path="docs"),
                        files_api.BatchApplyOperation(
                            op="write",
                            path="docs/notes.md",
                            content="# Notes\n",
                            create=True,
                        ),
                    ],
                )
            )
        )
        assert batch_result["applied_count"] == 2
        notes = asyncio.run(files_api.project_content(project_id=project_id, path="docs/notes.md"))
        assert "# Notes" in notes["content"]
        renamed = asyncio.run(
            files_api.rename_project_content(
                files_api.RenameContentRequest(
                    project_id=project_id,
                    path="app/new_service.py",
                    new_path="app/renamed_service.py",
                )
            )
        )
        assert renamed["renamed"] is True
        renamed_content = asyncio.run(
            files_api.project_content(project_id=project_id, path="app/renamed_service.py")
        )
        assert "def created" in renamed_content["content"]
        deleted_file = asyncio.run(
            files_api.delete_project_content(
                files_api.DeleteContentRequest(
                    project_id=project_id,
                    path="app/renamed_service.py",
                )
            )
        )
        assert deleted_file["deleted"] is True
        with pytest.raises(HTTPException) as exc:
            asyncio.run(files_api.project_content(project_id=project_id, path="app/renamed_service.py"))
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            asyncio.run(files_api.project_content(project_id=project_id, path="../README.md"))
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                files_api.save_project_content(
                    files_api.SaveContentRequest(
                        project_id=project_id,
                        path="../README.md",
                        content="nope",
                    )
                )
            )
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                files_api.diff_project_content(
                    files_api.SaveContentRequest(
                        project_id=project_id,
                        path="app/missing.py",
                        content="print('x')\n",
                    )
                )
            )
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                files_api.rename_project_content(
                    files_api.RenameContentRequest(
                        project_id=project_id,
                        path="app/service.py",
                        new_path="../escape.py",
                    )
                )
        )
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                files_api.move_project_path(
                    files_api.MovePathRequest(
                        project_id=project_id,
                        path="app/generated_renamed",
                        new_path="app/generated_renamed/nested",
                    )
                )
            )
        assert exc.value.status_code == 400
        idea_apply = asyncio.run(files_api.apply_project_idea_starter(project_id, "ci"))
        assert idea_apply["idea_id"] == "ci"
        workflow = asyncio.run(
            files_api.project_content(
                project_id=project_id,
                path=".github/workflows/ci.yml",
            )
        )
        assert "pytest -q" in workflow["content"]
        readme_apply = asyncio.run(files_api.apply_project_idea_starter(project_id, "readme"))
        assert readme_apply["idea_id"] == "readme"
        readme = asyncio.run(files_api.project_content(project_id=project_id, path="README.md"))
        assert project_id in readme["content"]

        symbols = asyncio.run(files_api.project_symbols(project_id=project_id, q="login", limit=20))
        assert symbols["items"]
        assert any(item.get("symbol") == "login" for item in symbols["items"])

        architecture = asyncio.run(files_api.project_architecture(project_id=project_id, lang="en"))
        assert architecture["architecture"]["backend"] is True
        assert "Detected layers" in architecture["summary"]
        ideas = asyncio.run(files_api.project_improvement_ideas(project_id=project_id, lang="en"))
        assert ideas["items"]
        assert any(item.get("id") == "tests" for item in ideas["items"])
        intelligence = asyncio.run(files_api.project_intelligence(project_id=project_id))
        assert intelligence["summary"]["files_scanned"] >= 6
        assert intelligence["summary"]["route_count"] >= 2
        assert intelligence["summary"]["runtime_surface_count"] >= 1
        assert any(item.get("path") == "app/service.py" for item in intelligence["summary"]["hotspots"])
        assert any(item.get("path") == "app/routes.py" and int(item.get("route_count") or 0) >= 2 for item in intelligence["summary"]["route_hotspots"])
        assert any(item.get("method") == "GET" and item.get("route") == "/login" for item in intelligence["summary"]["routes"])
        assert any(item.get("resolved_route") == "/auth/login" and item.get("handler") == "login_route" for item in intelligence["summary"]["routes"])
        assert any(item.get("path") == "app/main.py" and item.get("app_name") == "app" and int(item.get("served_route_count") or 0) >= 2 for item in intelligence["summary"]["runtime_surfaces"])
        assert any(item.get("symbol") == "login" for item in intelligence["summary"]["symbol_hotspots"])
        assert any(item.get("symbol") == "login" for item in intelligence["summary"]["symbol_call_hotspots"])
        assert any(item.get("symbol") == "login_route" and "route-handler" in (item.get("reasons") or []) for item in intelligence["summary"]["public_api_symbols"])
        assert any(item.get("symbol") == "dead_helper" and item.get("path") == "app/orphan.py" for item in intelligence["summary"]["isolated_symbol_candidates"])
        assert any(item.get("env") == "API_KEY" for item in intelligence["summary"]["env_var_hotspots"])
        assert any("app/format_a.py" in item.get("paths", []) and "app/format_b.py" in item.get("paths", []) for item in intelligence["summary"]["duplicate_logic_clusters"])
        impact = asyncio.run(files_api.project_impact(project_id=project_id, q="app/service.py", limit=8))
        assert "app/service.py" in impact["report"]["matched_files"]
        assert any(item.get("path") == "app/consumer.py" for item in impact["report"]["imported_by"])
        impact_symbol = asyncio.run(files_api.project_impact(project_id=project_id, q="login", limit=8))
        assert any(item.get("path") == "app/service.py" for item in impact_symbol["report"]["defined_in"])
        assert any(item.get("path") == "app/consumer.py" for item in impact_symbol["report"]["referenced_by_files"])
        assert any(item.get("from_path") == "app/consumer.py" and item.get("to_path") == "app/service.py" for item in impact_symbol["report"]["call_edges_to"])
        assert any(item.get("method") == "GET" and item.get("resolved_route") == "/auth/login" for item in impact_symbol["report"]["routes_in_scope"])
        assert any(item.get("path") == "app/main.py" and item.get("app_name") == "app" for item in impact_symbol["report"]["runtime_surfaces_in_scope"])
        assert any(item.get("symbol") == "login_route" for item in impact_symbol["report"]["public_api_symbols_in_scope"])
        assert any(item.get("symbol") == "login" for item in impact_symbol["report"]["refactor_candidates"])
        assert impact_symbol["report"]["rename_scope"]["safety"]["level"] in {"low", "medium", "high"}
        impact_env = asyncio.run(files_api.project_impact(project_id=project_id, q="config.py", limit=8))
        assert any(item.get("env") == "API_KEY" for item in impact_env["report"]["env_vars_in_scope"])
        impact_routes = asyncio.run(files_api.project_impact(project_id=project_id, q="routes.py", limit=8))
        assert any(item.get("method") == "POST" and item.get("resolved_route") == "/auth/token" for item in impact_routes["report"]["routes_in_scope"])
        assert any(item.get("path") == "app/main.py" and int(item.get("served_route_count") or 0) >= 2 for item in impact_routes["report"]["runtime_surfaces_in_scope"])
        impact_orphan = asyncio.run(files_api.project_impact(project_id=project_id, q="orphan.py", limit=8))
        assert any(item.get("symbol") == "dead_helper" for item in impact_orphan["report"]["isolated_symbols_in_scope"])
        impact_dup = asyncio.run(files_api.project_impact(project_id=project_id, q="normalize_email", limit=8))
        assert any("app/format_b.py" in item.get("paths", []) for item in impact_dup["report"]["duplicate_logic_neighbors"])
        rename_plan = asyncio.run(
            files_api.project_symbol_rename_plan(
                project_id,
                files_api.SymbolRenamePlanRequest(symbol="login", new_symbol="authenticate", limit=8),
            )
        )
        assert rename_plan["plan"]["operation_count"] >= 2
        assert "app/service.py" in rename_plan["plan"]["changed_paths"]
        assert any("authenticate" in item.get("content", "") for item in rename_plan["plan"]["operations"])
        assert rename_plan["plan"]["rename_safety"]["level"] in {"low", "medium", "high"}

        deleted = asyncio.run(files_api.delete_project_endpoint(files_api.DeleteProjectRequest(project_id=project_id)))
        assert deleted["status"] == "ok"
        assert deleted["retrieval_removed"] == 7
        assert not root.exists()
        assert project_store.get_project(project_id) is None
        assert removed_projects == [project_id]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_register_root_workspace_only_unregisters(monkeypatch: pytest.MonkeyPatch):
    root = Path("tmp") / f"workspace_proj_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    save_project_manifest(root, root.name, chunk_count=2, chunked_files=1)
    project_id = "workspace_proj"
    removed_projects: list[str] = []
    monkeypatch.setattr(
        files_api,
        "remove_project_documents",
        lambda value: removed_projects.append(value) or 2,
    )

    try:
        registered = asyncio.run(files_api.register_root(files_api.RegisterRootRequest(path=str(root), project_id=project_id)))
        assert registered["project_id"] == project_id

        tree = asyncio.run(files_api.project_tree(project_id=project_id, max_depth=3))
        assert "service.py" in str(tree.model_dump())

        content = asyncio.run(files_api.project_content(project_id=project_id, path="app/service.py"))
        assert "def login" in content["content"]
        with pytest.raises(HTTPException) as exc:
            asyncio.run(files_api.project_excerpt(project_id=project_id, path="../README.md"))
        assert exc.value.status_code == 400

        deleted = asyncio.run(files_api.delete_project_endpoint(files_api.DeleteProjectRequest(project_id=project_id)))
        assert deleted["status"] == "ok"
        assert deleted["deleted_path"] is False
        assert deleted["unregistered_only"] is True
        assert deleted["retrieval_removed"] == 2
        assert root.exists()
        assert project_store.get_project(project_id) is None
        assert removed_projects == [project_id]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_delete_project_by_id_allows_unregister_only_for_external_root(monkeypatch: pytest.MonkeyPatch):
    root = Path("/tmp") / f"external_proj_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    project_id = f"external_{uuid.uuid4().hex[:8]}"
    removed_projects: list[str] = []
    monkeypatch.setattr(
        files_api,
        "remove_project_documents",
        lambda value: removed_projects.append(value) or 0,
    )
    project_store.register_project(project_id, root, source="workspace", status="uploaded")

    try:
        deleted = asyncio.run(files_api.delete_project_endpoint(files_api.DeleteProjectRequest(project_id=project_id)))
        assert deleted["status"] == "ok"
        assert deleted["deleted_path"] is False
        assert deleted["unregistered_only"] is True
        assert deleted["project_id"] == project_id
        assert root.exists()
        assert project_store.get_project(project_id) is None
        assert removed_projects == [project_id]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_batch_apply_preview_and_review_token():
    root = Path("tmp") / f"workspace_preview_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    save_project_manifest(root, root.name, chunk_count=2, chunked_files=1)
    project_id = f"preview_{uuid.uuid4().hex[:8]}"
    project_store.register_project(project_id, root, source="register-root", status="uploaded")

    try:
        preview = asyncio.run(
            files_api.preview_batch_project_changes(
                files_api.BatchApplyRequest(
                    project_id=project_id,
                    operations=[
                        files_api.BatchApplyOperation(
                            op="write",
                            path="app/service.py",
                            content="def login():\n    return 'preview'\n",
                        ),
                        files_api.BatchApplyOperation(op="mkdir", path="docs"),
                    ],
                )
            )
        )
        assert preview["operation_count"] == 2
        assert preview["changed_count"] == 2
        assert preview["review_token"]
        assert "preview" in preview["combined_diff"]
        assert any(item["op"] == "mkdir" for item in preview["items"])

        applied = asyncio.run(
            files_api.batch_apply_project_changes(
                files_api.BatchApplyRequest(
                    project_id=project_id,
                    operations=[
                        files_api.BatchApplyOperation(
                            op="write",
                            path="app/service.py",
                            content="def login():\n    return 'preview'\n",
                        ),
                        files_api.BatchApplyOperation(op="mkdir", path="docs"),
                    ],
                    review_token=preview["review_token"],
                )
            )
        )
        assert applied["reviewed"] is True

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                files_api.batch_apply_project_changes(
                    files_api.BatchApplyRequest(
                        project_id=project_id,
                        operations=[
                            files_api.BatchApplyOperation(op="mkdir", path="docs-again"),
                        ],
                        review_token="bad-token",
                    )
                )
            )
        assert exc.value.status_code == 400
        assert exc.value.detail["review_required"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)


def test_batch_apply_rolls_back_on_failure():
    root = Path("tmp") / f"workspace_rollback_{uuid.uuid4().hex[:8]}"
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "service.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    save_project_manifest(root, root.name, chunk_count=2, chunked_files=1)
    project_id = f"rollback_{uuid.uuid4().hex[:8]}"
    project_store.register_project(project_id, root, source="register-root", status="uploaded")

    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                files_api.batch_apply_project_changes(
                    files_api.BatchApplyRequest(
                        project_id=project_id,
                        operations=[
                            files_api.BatchApplyOperation(
                                op="write",
                                path="docs/notes.md",
                                content="# Notes\n",
                                create=True,
                            ),
                            files_api.BatchApplyOperation(op="bogus", path="docs/notes.md"),
                        ],
                    )
                )
            )
        assert exc.value.status_code == 400
        assert exc.value.detail["rolled_back"] is True
        assert not (root / "docs" / "notes.md").exists()
        assert not (root / "docs").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        project_store.delete_project(project_id)
