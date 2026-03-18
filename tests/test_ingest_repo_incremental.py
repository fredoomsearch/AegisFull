from __future__ import annotations

import json
from pathlib import Path

from app.scripts import ingest_repo
from app.services.project_ingest_state import load_project_ingest_state


def test_ingest_repo_incremental_and_code_aware(monkeypatch, tmp_path: Path):
    root = tmp_path / "demo_project"
    root.mkdir()
    (root / "app.py").write_text(
        "class AuthService:\n"
        "    def login(self, user):\n"
        "        return user\n\n"
        "def refresh_token(token):\n"
        "    return token\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\nAuth service.\n", encoding="utf-8")

    store: dict[tuple[str, str], list[dict]] = {}
    removals: list[set[str]] = []

    def fake_add_documents(docs):
        added = 0
        for doc in docs:
            key = (doc["project_id"], doc["rel_path"])
            store.setdefault(key, []).append(doc)
            added += 1
        return added

    def fake_remove(project_id, rel_paths=None):
        rel_paths = set(rel_paths or set())
        removals.append(rel_paths)
        removed = 0
        for rel_path in list(rel_paths):
            removed += len(store.pop((project_id, rel_path), []))
        return removed

    def fake_count(project_id):
        return sum(len(rows) for (pid, _), rows in store.items() if pid == project_id)

    monkeypatch.setattr(ingest_repo, "add_documents", fake_add_documents)
    monkeypatch.setattr(ingest_repo, "remove_project_documents", fake_remove)
    monkeypatch.setattr(ingest_repo, "count_project_chunks", fake_count)

    manifest_path = root / ".aegis_manifest.json"

    total_chunks = ingest_repo.ingest(
        root,
        max_files=50,
        max_file_bytes=200_000,
        max_total_bytes=2_000_000,
        project_id="demo_project",
        manifest_out=manifest_path,
    )
    assert total_chunks == fake_count("demo_project")

    app_docs = store[("demo_project", "app.py")]
    assert {doc["chunk_type"] for doc in app_docs} >= {"module", "symbol", "window"}
    assert any(doc.get("symbol") == "login" for doc in app_docs)
    assert any(doc.get("symbol") == "refresh_token" for doc in app_docs)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["project_id"] == "demo_project"
    assert manifest["stats"]["chunk_count"] == total_chunks
    assert ".aegis_manifest.json" not in manifest["file_tree"]
    assert ".aegis_ingest_state.json" not in manifest["file_tree"]

    state = load_project_ingest_state(root)
    assert state["project_id"] == "demo_project"
    first_hash = state["file_hashes"]["app.py"]

    before_reingest_docs = sum(len(rows) for rows in store.values())
    removals.clear()

    total_chunks_second = ingest_repo.ingest(
        root,
        max_files=50,
        max_file_bytes=200_000,
        max_total_bytes=2_000_000,
        project_id="demo_project",
        manifest_out=manifest_path,
    )

    assert total_chunks_second == fake_count("demo_project")
    assert {"__manifest__/files.tsv"} in removals
    assert sum(len(rows) for rows in store.values()) >= before_reingest_docs

    (root / "app.py").write_text(
        "class AuthService:\n"
        "    def login(self, user):\n"
        "        return user\n\n"
        "def refresh_token(token):\n"
        "    return token\n\n"
        "def logout(user):\n"
        "    return user\n",
        encoding="utf-8",
    )

    removals.clear()
    ingest_repo.ingest(
        root,
        max_files=50,
        max_file_bytes=200_000,
        max_total_bytes=2_000_000,
        project_id="demo_project",
        manifest_out=manifest_path,
    )

    assert any("app.py" in rels for rels in removals)
    new_state = load_project_ingest_state(root)
    assert new_state["file_hashes"]["app.py"] != first_hash
    assert any(doc.get("symbol") == "logout" for doc in store[("demo_project", "app.py")])
